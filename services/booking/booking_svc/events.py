"""`booking.confirmed` events.

EVENT_BACKEND picks the publisher: `log` only logs, `http` pushes to the local ticket-pdf
function. Publishing is best effort and runs after the response: a
failed publish is logged with the booking id and can be redone via /republish.
"""

import asyncio
import base64
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

import httpx

from booking_svc.models import Booking

logger = logging.getLogger("booking_svc.events")

EVENT_TYPE = "booking.confirmed"
EVENT_VERSION = 1


class EventPublisher(Protocol):
    async def publish(self, payload: dict) -> None: ...

    async def aclose(self) -> None: ...


class LogPublisher:
    """Logs the event instead of sending it (EVENT_BACKEND=log)."""

    async def publish(self, payload: dict) -> None:
        logger.info(
            EVENT_TYPE,
            extra={"booking_id": payload["booking_id"], "seat_count": len(payload["seats"])},
        )

    async def aclose(self) -> None:
        return None


def push_envelope(payload: dict) -> dict:
    """The body a Pub/Sub push subscription delivers. The local publisher sends exactly
    this, so ticket-pdf runs the same code path locally and in the cloud."""
    return {
        "message": {
            "data": base64.b64encode(json.dumps(payload).encode()).decode(),
            "attributes": {
                "type": EVENT_TYPE,
                "version": str(EVENT_VERSION),
                "request_id": payload.get("request_id") or "",
            },
            "messageId": uuid.uuid4().hex,
            "publishTime": datetime.now(UTC).isoformat(),
        },
        "subscription": "local/booking-confirmed-ticket-pdf",
    }


class HttpPushPublisher:
    """Local stand-in for Pub/Sub push (EVENT_BACKEND=http): POSTs the push envelope straight to
    the ticket-pdf container. A non-2xx answer raises, so publish_with_retries retries it."""

    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = url
        self.client = httpx.AsyncClient(timeout=10.0, transport=transport)

    async def publish(self, payload: dict) -> None:
        response = await self.client.post(self.url, json=push_envelope(payload))
        response.raise_for_status()

    async def aclose(self) -> None:
        await self.client.aclose()


def make_publisher(backend: str, ticket_function_url: str = "") -> EventPublisher:
    if backend == "log":
        return LogPublisher()
    if backend == "http":
        return HttpPushPublisher(ticket_function_url)
    raise NotImplementedError(f"EVENT_BACKEND={backend!r} is not supported")


def build_payload(booking: Booking, request_id: str | None) -> dict:
    """The v1 event contract."""
    return {
        "type": EVENT_TYPE,
        "version": EVENT_VERSION,
        "booking_id": str(booking.id),
        "user_id": booking.user_id,
        "buyer_email": booking.user_email,
        "buyer_name": booking.user_name,
        "event": {
            "id": booking.event_id,
            "title": booking.event_title,
            "venue": booking.venue,
            "city": booking.city,
            "starts_at": booking.event_starts_at.isoformat(),
        },
        "seats": [
            {"seat_id": s.seat_id, "section_name": s.section_name, "price_cents": s.price_cents}
            for s in booking.seats
        ],
        "total_price_cents": booking.total_price_cents,
        "confirmed_at": booking.created_at.astimezone(UTC).isoformat(),
        "request_id": request_id,
    }


async def publish_with_retries(
    publisher: EventPublisher, payload: dict, attempts: int = 3, base_delay_s: float = 0.5
) -> bool:
    """Best effort: retry with exponential backoff, never raise into the request."""
    for attempt in range(1, attempts + 1):
        try:
            await publisher.publish(payload)
            return True
        except Exception:
            logger.warning(
                "publish failed",
                exc_info=True,
                extra={"booking_id": payload["booking_id"], "attempt": attempt},
            )
            if attempt < attempts:
                await asyncio.sleep(base_delay_s * 2 ** (attempt - 1))
    logger.error(
        "booking.confirmed not published; ticket must be recovered by republishing",
        extra={"booking_id": payload["booking_id"], "at": datetime.now(UTC).isoformat()},
    )
    return False
