from collections.abc import AsyncIterator, Callable

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str, pool_size: int = 5, max_overflow: int = 5) -> AsyncEngine:
    """Pool sizes are per replica; replicas × (pool + overflow) must stay < max_connections."""
    return create_async_engine(
        url, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def make_session_dependency(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncIterator[AsyncSession]]:
    """FastAPI dependency yielding one session per request."""

    async def get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    return get_session


async def init_schema(engine: AsyncEngine, metadata: MetaData, lock_key: int) -> None:
    """Create missing tables. Many replicas may boot at once (HPA scale-up), so a Postgres
    advisory lock makes them take turns instead of racing on CREATE TABLE.

    The lock is transaction-scoped: Postgres releases it on commit *or* rollback, so a failing
    create_all surfaces its own error and never leaves a lock behind on a pooled connection."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        await conn.run_sync(metadata.create_all)
