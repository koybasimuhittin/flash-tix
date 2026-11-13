"""Integration tests for init_schema against the compose postgres (`make up`).

Skipped when no database is reachable. Override the target with TEST_DATABASE_URL.
"""

import os

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, text
from sqlalchemy.exc import DBAPIError

from flashtix_common.db import init_schema, make_engine

DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres-local@127.0.0.1:5433/postgres"
)
LOCK_KEY = 990_001
PROBE_TABLE = "init_schema_probe"

pytestmark = pytest.mark.anyio


@pytest.fixture
async def engine():
    engine = make_engine(DB_URL, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"postgres not reachable at {DB_URL}: {exc}")
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {PROBE_TABLE}"))
    await engine.dispose()


async def advisory_locks_held(lock_key: int) -> int:
    """Count from a separate engine, so it is a different Postgres session."""
    observer = make_engine(DB_URL, pool_size=1, max_overflow=0)
    try:
        async with observer.connect() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :key"),
                {"key": lock_key},
            )
            return result.scalar_one()
    finally:
        await observer.dispose()


async def test_creates_missing_tables_and_releases_lock(engine):
    metadata = MetaData()
    Table(PROBE_TABLE, metadata, Column("id", Integer, primary_key=True))

    await init_schema(engine, metadata, LOCK_KEY)
    await init_schema(engine, metadata, LOCK_KEY)  # second run is a no-op

    async with engine.connect() as conn:
        exists = await conn.scalar(
            text("SELECT to_regclass(:name) IS NOT NULL"), {"name": PROBE_TABLE}
        )
    assert exists
    assert await advisory_locks_held(LOCK_KEY) == 0


async def test_failure_surfaces_real_error_and_leaves_no_lock(engine):
    metadata = MetaData()
    Table(
        PROBE_TABLE,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("broken", Integer, server_default=text("no_such_function()")),
    )

    with pytest.raises(DBAPIError) as raised:
        await init_schema(engine, metadata, LOCK_KEY)

    assert "no_such_function" in str(raised.value)
    assert "InFailedSQLTransaction" not in repr(raised.value)
    assert await advisory_locks_held(LOCK_KEY) == 0
