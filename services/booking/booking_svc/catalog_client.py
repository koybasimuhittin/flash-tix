"""booking's only synchronous dependency: event data from catalog-service.

Results are cached in-process for CATALOG_EVENT_CACHE_TTL_SECONDS, so a flash sale doesn't
turn every hold into a catalog request. A sales_open_at that is stale for up to the TTL is
an accepted trade-off.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from flashtix_common.logging import request_id_var

logger = logging.getLogger("booking_svc.catalog_client")

_MAX_CACHED_EVENTS = 10_000


class EventNotFound(Exception):
    pass


class CatalogUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SectionInfo:
    code: str
    name: str
    price_cents: int
    rows: int
    seats_per_row: int


@dataclass(frozen=True)
class EventInfo:
    id: int
    title: str
    venue: str
    city: str
    starts_at: datetime
    sales_open_at: datetime
    sections: dict[str, SectionInfo]  # keyed by section code


def _utc(value: str) -> datetime:
    # Booking responses promise UTC timestamps with an explicit offset, and the
    # event start is snapshotted into bookings, so normalize whatever offset catalog sent.
    return datetime.fromisoformat(value).astimezone(UTC)


def parse_event(data: dict) -> EventInfo:
    return EventInfo(
        id=data["id"],
        title=data["title"],
        venue=data["venue"],
        city=data["city"],
        starts_at=_utc(data["starts_at"]),
        sales_open_at=_utc(data["sales_open_at"]),
        sections={
            section["code"]: SectionInfo(
                code=section["code"],
                name=section["name"],
                price_cents=section["price_cents"],
                rows=section["rows"],
                seats_per_row=section["seats_per_row"],
            )
            for section in data["sections"]
        },
    )


class CatalogClient:
    def __init__(
        self,
        base_url: str,
        cache_ttl_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # One client per process: connections to catalog are kept alive and reused.
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=2.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            transport=transport,
        )
        self._ttl = cache_ttl_seconds
        self._cache: dict[int, tuple[float, EventInfo]] = {}

    async def get_event(self, event_id: int) -> EventInfo:
        now = time.monotonic()
        cached = self._cache.get(event_id)
        if cached is not None and cached[0] > now:
            return cached[1]

        request_id = request_id_var.get()
        headers = {"X-Request-ID": request_id} if request_id else {}
        try:
            response = await self._http.get(f"/api/events/{event_id}", headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("catalog unreachable", extra={"event_id": event_id})
            raise CatalogUnavailable from exc
        if response.status_code == 404:
            raise EventNotFound(event_id)
        if response.status_code != 200:
            logger.warning(
                "catalog error", extra={"event_id": event_id, "status": response.status_code}
            )
            raise CatalogUnavailable(response.status_code)

        event = parse_event(response.json())
        if len(self._cache) >= _MAX_CACHED_EVENTS:
            self._cache.clear()
        self._cache[event_id] = (now + self._ttl, event)
        return event

    async def aclose(self) -> None:
        await self._http.aclose()
