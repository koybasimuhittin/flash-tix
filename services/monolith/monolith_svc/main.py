"""The same three services as one process (monolith vs microservices comparison).

Nothing is rewritten: each service already exposes its FastAPI `router` and `lifespan`, so this
file mounts the routers and runs the three lifespans inside one AsyncExitStack. Each lifespan
puts its state under its own name (`app.state.auth`, `.catalog`, `.booking`), and the services
keep their own database pools exactly as in the microservice deployment.

The one real difference is booking → catalog: in the microservices it is an HTTP call over the
network, here booking's catalog client is pointed at this very app through an in-process
ASGI transport, so the request never leaves the process. That hop is what is compared.

Connection pools: one monolith replica opens all three services' pools, so its maximum is
the sum of AUTH_, CATALOG_ and BOOKING_DB_POOL_SIZE + _MAX_OVERFLOW. Size them so that
replicas × that sum stays below Postgres max_connections.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI

from auth_svc.main import lifespan as auth_lifespan
from auth_svc.routes import router as auth_router
from booking_svc.main import lifespan as booking_lifespan
from booking_svc.routes import router as booking_router
from catalog_svc.main import lifespan as catalog_lifespan
from catalog_svc.routes import router as catalog_router
from flashtix_common.config import BaseServiceSettings
from flashtix_common.health import db_check, make_health_router, redis_check
from flashtix_common.logging import setup_logging
from flashtix_common.middleware import RequestContextMiddleware


class MonolithSettings(BaseServiceSettings):
    service_name: str = "monolith"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # booking's lifespan builds its catalog client with this transport: in-process calls.
    app.state.catalog_transport = httpx.ASGITransport(app=app)
    async with AsyncExitStack() as stack:
        for service_lifespan in (auth_lifespan, catalog_lifespan, booking_lifespan):
            await stack.enter_async_context(service_lifespan(app))
        yield


def create_app() -> FastAPI:
    settings = MonolithSettings()
    setup_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="flashtix-monolith", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)
    for router in (auth_router, catalog_router, booking_router):
        app.include_router(router)

    async def auth_db() -> None:
        await db_check(app.state.auth.engine)()

    async def catalog_db() -> None:
        await db_check(app.state.catalog.engine)()

    async def booking_db() -> None:
        await db_check(app.state.booking.engine)()

    async def redis() -> None:
        await redis_check(app.state.booking.holds.redis)()

    app.include_router(
        make_health_router(
            {"auth_db": auth_db, "catalog_db": catalog_db, "booking_db": booking_db, "redis": redis}
        )
    )
    return app
