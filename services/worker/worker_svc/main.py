from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from flashtix_common.db import make_engine
from flashtix_common.health import db_check, make_health_router
from flashtix_common.logging import setup_logging
from flashtix_common.middleware import RequestContextMiddleware
from worker_svc.config import WorkerSettings
from worker_svc.files import LocalFiles
from worker_svc.routes import WorkerState, router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = WorkerSettings()
    engine = make_engine(
        settings.report_database_url, settings.report_db_pool_size, settings.report_db_max_overflow
    )
    app.state.worker = WorkerState(
        settings=settings, engine=engine, files=LocalFiles(settings.local_storage_dir)
    )
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    settings = WorkerSettings()
    setup_logging(settings.service_name, settings.log_level)
    app = FastAPI(title="worker", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware, slow_request_ms=settings.slow_request_ms)
    app.include_router(router)

    async def database_ready() -> None:
        await db_check(app.state.worker.engine)()

    app.include_router(make_health_router({"db": database_ready}))
    return app
