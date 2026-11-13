import json
import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from flashtix_common.logging import request_id_var

logger = logging.getLogger("flashtix.request")

_MAX_REQUEST_ID_LEN = 128
_INTERNAL_ERROR_BODY = json.dumps({"detail": {"code": "INTERNAL_ERROR"}}).encode()


class RequestContextMiddleware:
    """Pure ASGI middleware (cheaper than BaseHTTPMiddleware under load).

    - Takes X-Request-ID from the caller (the gateway sets it) or generates a UUID4.
    - Makes it available to every log line through `request_id_var` and echoes it back.
    - Logs each request at DEBUG, or at WARNING when it failed (5xx) or was slow.
    - Turns unhandled exceptions into a JSON 500 itself. Starlette's own error handler sits
      outside this middleware, where the request id is already gone from logs and headers.
    """

    def __init__(self, app: ASGIApp, slow_request_ms: int = 500) -> None:
        self.app = app
        self.slow_request_ms = slow_request_ms

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        status = 500
        response_started = False
        start = time.perf_counter()
        # When the client got the last byte. Background tasks (e.g. publishing an event after a
        # purchase) run after that but still inside this call, and must not count as latency.
        finished: float | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started, finished
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                headers = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = time.perf_counter()

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            status = 500
            logger.exception(
                "unhandled error", extra={"method": scope["method"], "path": scope["path"]}
            )
            # Already-started responses can't be replaced: re-raise so the server aborts the
            # connection. Otherwise the error is fully handled here (logged with its request id,
            # client got a 500), so swallow it instead of letting the server log it a second time.
            if response_started:
                raise
            await send_with_request_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send_with_request_id({"type": "http.response.body", "body": _INTERNAL_ERROR_BODY})
        finally:
            duration_ms = round(((finished or time.perf_counter()) - start) * 1000, 1)
            slow_or_failed = status >= 500 or duration_ms > self.slow_request_ms
            logger.log(
                logging.WARNING if slow_or_failed else logging.DEBUG,
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            request_id = value.decode("latin-1").strip()
            if 0 < len(request_id) <= _MAX_REQUEST_ID_LEN and request_id.isprintable():
                return request_id
    return None
