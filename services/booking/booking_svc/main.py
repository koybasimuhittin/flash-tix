from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from booking_svc.catalog_client import CatalogClient
from booking_svc.config import BookingSettings
from booking_svc.events import make_publisher
from booking_svc.holds import HoldStore
from booking_svc.models import SCHEMA_LOCK_KEY, Base
from booking_svc.routes import BookingState, router
from booking_svc.storage import make_storage
from flashtix_common.db import init_schema, make_engine, make_sessionmaker
from flashtix_common.health import db_check, make_health_router, redis_check
from flashtix_common.logging import setup_logging
from flashtix_common.middleware import RequestContextMiddleware
from flashtix_common.redis import make_redis
from flashtix_common.security import TokenVerifier


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = BookingSettings()
    engine = make_engine(
        settings.booking_database_url,
        settings.booking_db_pool_size,
        settings.booking_db_max_overflow,
    )
    redis = make_redis(settings.redis_url)
    await init_schema(engine, Base.metadata, lock_key=SCHEMA_LOCK_KEY)
    # Tests (and later the monolith) can route catalog calls through their own transport.
    transport: httpx.AsyncBaseTransport | None = getattr(app.state, "catalog_transport", None)
    catalog = CatalogClient(
        settings.catalog_url, settings.catalog_event_cache_ttl_seconds, transport
    )
    publisher = make_publisher(settings.event_backend, settings.worker_url)
    app.state.booking = BookingState(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        holds=HoldStore(redis),
        catalog=catalog,
        publisher=publisher,
        storage=make_storage(settings.storage_backend, settings.local_storage_dir),
    )
    app.state.token_verifier = TokenVerifier.from_file(
        settings.jwt_public_key_path, settings.jwt_issuer, settings.jwt_audience
    )
    try:
        yield
    finally:
        await publisher.aclose()
        await catalog.aclose()
        await redis.aclose()
        await engine.dispose()


def create_app(catalog_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = BookingSettings()
    setup_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="booking-service", lifespan=lifespan)
    app.state.catalog_transport = catalog_transport
    app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)
    app.include_router(router)

    async def database_ready() -> None:
        await db_check(app.state.booking.engine)()

    async def redis_ready() -> None:
        await redis_check(app.state.booking.holds.redis)()

    app.include_router(make_health_router({"db": database_ready, "redis": redis_ready}))
    return app
