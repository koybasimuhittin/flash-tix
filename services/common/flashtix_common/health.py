import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

Check = Callable[[], Awaitable[object]]


def make_health_router(checks: dict[str, Check], timeout_s: float = 1.0) -> APIRouter:
    """Probe endpoints for K8s and compose healthchecks (not routed through the gateway).

    /healthz (liveness): 200 while the process is up.
    /readyz (readiness): 200 only when every dependency check passes within the timeout,
    so a new pod gets no traffic until it can actually serve it.
    """
    router = APIRouter()

    @router.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz", include_in_schema=False)
    async def readyz() -> JSONResponse:
        results = await asyncio.gather(*(_run(check, timeout_s) for check in checks.values()))
        details = dict(zip(checks, results, strict=True))
        ready = all(result == "ok" for result in results)
        return JSONResponse(
            {"status": "ok" if ready else "unavailable", "checks": details},
            status_code=200 if ready else 503,
        )

    return router


async def _run(check: Check, timeout_s: float) -> str:
    try:
        await asyncio.wait_for(check(), timeout_s)
        return "ok"
    except TimeoutError:
        return "timeout"
    except Exception as exc:
        return f"error: {type(exc).__name__}"


def db_check(engine: AsyncEngine) -> Check:
    async def check() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    return check


def redis_check(client: Redis) -> Check:
    return client.ping
