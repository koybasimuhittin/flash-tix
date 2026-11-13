import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flashtix_common.logging import JsonFormatter, request_id_var
from flashtix_common.middleware import RequestContextMiddleware


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, slow_request_ms=500)

    @app.get("/ok")
    async def ok() -> dict:
        logging.getLogger("test").info("inside handler")
        return {"request_id": request_id_var.get()}

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("boom")

    return TestClient(app, raise_server_exceptions=False)


def test_incoming_request_id_is_used_and_echoed(client):
    response = client.get("/ok", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"
    assert response.json() == {"request_id": "abc-123"}


def test_request_id_is_generated_when_missing(client):
    response = client.get("/ok")
    generated = response.headers["x-request-id"]
    assert uuid.UUID(generated).version == 4
    assert response.json() == {"request_id": generated}


def test_oversized_request_id_is_replaced(client):
    response = client.get("/ok", headers={"X-Request-ID": "x" * 500})
    assert uuid.UUID(response.headers["x-request-id"])


def test_failed_request_is_logged_at_warning(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="flashtix.request"):
        assert client.get("/boom").status_code == 500
    record = next(r for r in caplog.records if r.getMessage() == "request")
    assert record.levelno == logging.WARNING
    assert (record.path, record.status) == ("/boom", 500)


def test_unhandled_error_returns_json_500_with_request_id(client):
    response = client.get("/boom", headers={"X-Request-ID": "req-500"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-500"
    assert response.json() == {"detail": {"code": "INTERNAL_ERROR"}}


def test_unhandled_error_is_handled_not_reraised():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/boom")
    async def boom() -> dict:
        raise RuntimeError("boom")

    # raise_server_exceptions=True would re-raise anything that escaped the app.
    assert TestClient(app).get("/boom").status_code == 500


class _RequestIdCapture(logging.Handler):
    """Records the request id that was current when each record was emitted."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[tuple[logging.LogRecord, str | None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.seen.append((record, request_id_var.get()))


def test_exception_is_logged_with_its_request_id(client):
    capture = _RequestIdCapture()
    request_logger = logging.getLogger("flashtix.request")
    request_logger.addHandler(capture)
    try:
        client.get("/boom", headers={"X-Request-ID": "req-exc"})
    finally:
        request_logger.removeHandler(capture)
    record, request_id = next((r, rid) for r, rid in capture.seen if r.exc_info)
    assert record.levelno == logging.ERROR
    assert request_id == "req-exc"
    assert (record.method, record.path) == ("GET", "/boom")
    assert json.loads(JsonFormatter("test").format(record))["exc"].endswith("RuntimeError: boom")


def test_fast_successful_request_is_logged_at_debug(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="flashtix.request"):
        client.get("/ok")
    record = next(r for r in caplog.records if r.name == "flashtix.request")
    assert record.levelno == logging.DEBUG


def test_json_formatter_includes_context_and_extra_fields():
    record = logging.LogRecord(
        "flashtix.test", logging.INFO, __file__, 1, "hold %s", ("A-1-1",), None
    )
    record.event_id = 7
    token = request_id_var.set("req-1")
    try:
        line = json.loads(JsonFormatter("booking").format(record))
    finally:
        request_id_var.reset(token)
    assert line["service"] == "booking"
    assert line["request_id"] == "req-1"
    assert line["msg"] == "hold A-1-1"
    assert line["level"] == "INFO"
    assert line["event_id"] == 7
