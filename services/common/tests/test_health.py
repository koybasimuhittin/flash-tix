import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from flashtix_common.health import make_health_router


async def passing() -> None:
    return None


async def failing() -> None:
    raise ConnectionError("db down")


async def hanging() -> None:
    await asyncio.sleep(10)


def client_with(checks) -> TestClient:
    app = FastAPI()
    app.include_router(make_health_router(checks, timeout_s=0.1))
    return TestClient(app)


def test_healthz_is_always_ok():
    assert client_with({"db": failing}).get("/healthz").status_code == 200


def test_readyz_ok_when_all_checks_pass():
    response = client_with({"db": passing, "redis": passing}).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"db": "ok", "redis": "ok"}}


def test_readyz_503_reports_each_failure():
    response = client_with({"db": failing, "redis": hanging, "cache": passing}).get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"] == {
        "db": "error: ConnectionError",
        "redis": "timeout",
        "cache": "ok",
    }
