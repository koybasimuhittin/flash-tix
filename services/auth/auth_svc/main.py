import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from auth_svc.config import AuthSettings
from auth_svc.crypto import TokenIssuer, hash_password
from auth_svc.models import Base, User
from auth_svc.routes import AuthState, router
from flashtix_common.db import init_schema, make_engine, make_sessionmaker
from flashtix_common.health import db_check, make_health_router
from flashtix_common.logging import setup_logging
from flashtix_common.middleware import RequestContextMiddleware
from flashtix_common.security import TokenVerifier

logger = logging.getLogger("auth_svc")

SCHEMA_LOCK_KEY = 1001


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = AuthSettings()
    engine = make_engine(
        settings.auth_database_url, settings.auth_db_pool_size, settings.auth_db_max_overflow
    )
    await init_schema(engine, Base.metadata, lock_key=SCHEMA_LOCK_KEY)
    state = AuthState(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        issuer=TokenIssuer.from_file(
            settings.jwt_private_key_path,
            settings.jwt_issuer,
            settings.jwt_audience,
            settings.access_token_ttl_seconds,
        ),
        dummy_hash=await run_in_threadpool(
            hash_password, "not-a-real-password", settings.bcrypt_rounds
        ),
    )
    app.state.auth = state
    app.state.token_verifier = TokenVerifier.from_file(
        settings.jwt_public_key_path, settings.jwt_issuer, settings.jwt_audience
    )
    await bootstrap_organizer(state)
    try:
        yield
    finally:
        await engine.dispose()


async def bootstrap_organizer(state: AuthState) -> None:
    """Create the organizer account from BOOTSTRAP_ORGANIZER_* if it doesn't exist yet.
    Safe when several replicas start at once: the unique email makes all but one insert fail."""
    settings = state.settings
    if not (settings.bootstrap_organizer_email and settings.bootstrap_organizer_password):
        return
    email = settings.bootstrap_organizer_email.lower()
    async with state.sessionmaker() as session:
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            if existing.role != "organizer":
                # Never promote an existing account: someone may have registered this email.
                logger.warning("bootstrap organizer email belongs to a non-organizer account")
            return
        password_hash = await run_in_threadpool(
            hash_password, settings.bootstrap_organizer_password, settings.bcrypt_rounds
        )
        session.add(
            User(
                email=email,
                name=settings.bootstrap_organizer_name,
                password_hash=password_hash,
                role="organizer",
            )
        )
        try:
            await session.commit()
            logger.info("bootstrap organizer created", extra={"email": email})
        except IntegrityError:
            await session.rollback()  # another replica created it first


def create_app() -> FastAPI:
    settings = AuthSettings()
    setup_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="auth-service", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)
    app.include_router(router)

    async def database_ready() -> None:
        await db_check(app.state.auth.engine)()

    app.include_router(make_health_router({"db": database_ready}))
    return app


app = create_app()
