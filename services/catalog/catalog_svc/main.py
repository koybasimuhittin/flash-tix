from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from catalog_svc.cache import CatalogCache
from catalog_svc.config import CatalogSettings
from catalog_svc.models import Base
from catalog_svc.routes import CatalogState, router
from flashtix_common.db import init_schema, make_engine, make_sessionmaker
from flashtix_common.health import db_check, make_health_router, redis_check
from flashtix_common.logging import setup_logging
from flashtix_common.middleware import RequestContextMiddleware
from flashtix_common.redis import make_redis
from flashtix_common.security import TokenVerifier

SCHEMA_LOCK_KEY = 1002


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = CatalogSettings()
    engine = make_engine(
        settings.catalog_database_url,
        settings.catalog_db_pool_size,
        settings.catalog_db_max_overflow,
    )
    redis = make_redis(settings.redis_url)
    await init_schema(engine, Base.metadata, lock_key=SCHEMA_LOCK_KEY)
    app.state.catalog = CatalogState(
        settings=settings,
        engine=engine,
        sessionmaker=make_sessionmaker(engine),
        cache=CatalogCache(
            redis, settings.catalog_cache_ttl_seconds, settings.catalog_cache_enabled
        ),
    )
    app.state.token_verifier = TokenVerifier.from_file(
        settings.jwt_public_key_path, settings.jwt_issuer, settings.jwt_audience
    )
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    settings = CatalogSettings()
    setup_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="catalog-service", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)
    app.include_router(router)

    async def database_ready() -> None:
        await db_check(app.state.catalog.engine)()

    async def redis_ready() -> None:
        await redis_check(app.state.catalog.cache.redis)()

    app.include_router(make_health_router({"db": database_ready, "redis": redis_ready}))
    return app


app = create_app()
