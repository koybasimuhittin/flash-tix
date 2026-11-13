import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from booking_svc.catalog_client import parse_event
from booking_svc.events import WorkerPublisher, build_payload, publish_with_retries
from booking_svc.models import SEAT_UNIQUE_CONSTRAINT, Booking, BookingSeat
from booking_svc.routes import is_seat_conflict
from booking_svc.seats import (
    SeatRequestError,
    check_seat_request,
    check_seats_exist,
    price_seats,
)

EVENT = parse_event(
    {
        "id": 7,
        "title": "Rock Night",
        "venue": "Big Hall",
        "city": "Istanbul",
        "starts_at": "2026-12-20T20:00:00+03:00",
        "sales_open_at": "2026-11-01T10:00:00Z",
        "sections": [
            {"code": "A", "name": "Front", "price_cents": 150_000, "rows": 5, "seats_per_row": 20},
            {"code": "B", "name": "Back", "price_cents": 50_000, "rows": 10, "seats_per_row": 30},
        ],
    }
)


def test_parse_event_reads_catalog_detail():
    assert EVENT.sales_open_at == datetime(2026, 11, 1, 10, tzinfo=UTC)
    assert EVENT.sections["B"].seats_per_row == 30


def test_too_many_seats():
    with pytest.raises(SeatRequestError) as exc:
        check_seat_request([f"A-1-{n}" for n in range(1, 8)], max_seats=6)
    assert exc.value.code == "TOO_MANY_SEATS"


def test_duplicate_seats_are_listed():
    with pytest.raises(SeatRequestError) as exc:
        check_seat_request(["A-1-1", "A-1-2", "A-1-1"], max_seats=6)
    assert (exc.value.code, exc.value.seats) == ("DUPLICATE_SEATS", ["A-1-1"])


def test_seats_must_exist_in_the_layout():
    check_seats_exist(EVENT, ["A-5-20", "B-10-30"])
    with pytest.raises(SeatRequestError) as exc:
        check_seats_exist(EVENT, ["A-6-1", "C-1-1", "A-01-1", "B-1-1", "nonsense"])
    assert exc.value.code == "INVALID_SEATS"
    assert exc.value.seats == ["A-6-1", "C-1-1", "A-01-1", "nonsense"]


def test_prices_come_from_each_seats_section():
    priced = price_seats(EVENT, ["A-1-1", "B-2-3"])
    assert [(p.seat_id, p.section_name, p.price_cents) for p in priced] == [
        ("A-1-1", "Front", 150_000),
        ("B-2-3", "Back", 50_000),
    ]
    assert sum(p.price_cents for p in priced) == 200_000


def test_payload_matches_the_v1_contract():
    booking = Booking(
        id=uuid.uuid4(),
        user_id=42,
        user_email="ayse@example.com",
        user_name="Ayşe",
        event_id=7,
        event_title="Rock Night",
        event_starts_at=EVENT.starts_at,
        venue="Big Hall",
        city="Istanbul",
        seat_count=1,
        total_price_cents=150_000,
        created_at=datetime(2026, 11, 13, 18, tzinfo=UTC),
        seats=[BookingSeat(seat_id="A-3-12", section_name="Front", price_cents=150_000)],
    )
    payload = build_payload(booking, "req-1")
    assert payload["type"] == "booking.confirmed" and payload["version"] == 1
    assert payload["booking_id"] == str(booking.id)
    # All timestamps are UTC; the worker converts to Europe/Istanbul for display.
    assert payload["event"]["starts_at"] == "2026-12-20T17:00:00+00:00"
    assert payload["seats"] == [
        {"seat_id": "A-3-12", "section_name": "Front", "price_cents": 150_000}
    ]
    assert payload["confirmed_at"] == "2026-11-13T18:00:00+00:00"
    assert payload["request_id"] == "req-1"


class FlakyPublisher:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def publish(self, payload: dict) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("down")

    async def aclose(self) -> None:
        return None


@pytest.mark.anyio
async def test_publish_retries_then_succeeds():
    publisher = FlakyPublisher(failures=2)
    assert await publish_with_retries(publisher, {"booking_id": "b"}, base_delay_s=0) is True
    assert publisher.calls == 3


@pytest.mark.anyio
async def test_publish_gives_up_without_raising():
    publisher = FlakyPublisher(failures=5)
    assert await publish_with_retries(publisher, {"booking_id": "b"}, base_delay_s=0) is False
    assert publisher.calls == 3


@pytest.mark.anyio
async def test_worker_publisher_posts_the_event_to_the_worker():
    received = []

    def worker(request: httpx.Request) -> httpx.Response:
        received.append((request.url.path, json.loads(request.content)))
        return httpx.Response(204)

    payload = {"booking_id": "b-1", "request_id": "req-9", "seats": []}
    publisher = WorkerPublisher("http://worker:8000/", httpx.MockTransport(worker))
    await publisher.publish(payload)
    await publisher.aclose()
    assert received == [("/tickets", payload)]


@pytest.mark.anyio
async def test_worker_publisher_raises_on_server_errors_so_it_is_retried():
    publisher = WorkerPublisher(
        "http://worker:8000", httpx.MockTransport(lambda _: httpx.Response(500))
    )
    with pytest.raises(httpx.HTTPStatusError):
        await publisher.publish({"booking_id": "b-1", "seats": []})
    await publisher.aclose()


@pytest.mark.anyio
async def test_worker_publisher_does_not_retry_an_invalid_event():
    calls = []

    def worker(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(422)

    publisher = WorkerPublisher("http://worker:8000", httpx.MockTransport(worker))
    assert await publish_with_retries(publisher, {"booking_id": "b-1"}, base_delay_s=0) is True
    await publisher.aclose()
    assert len(calls) == 1  # logged and dropped, not retried


class _UniqueViolation(Exception):
    def __init__(self, constraint_name: str | None) -> None:
        super().__init__("duplicate key value")
        self.constraint_name = constraint_name


def _integrity_error(constraint: str | None, message: str = "") -> IntegrityError:
    original = Exception(message)
    original.__cause__ = _UniqueViolation(constraint) if constraint is not None else None
    return IntegrityError("INSERT …", {}, original)


def test_only_the_seat_constraint_means_seat_already_sold():
    assert is_seat_conflict(_integrity_error(SEAT_UNIQUE_CONSTRAINT))
    assert not is_seat_conflict(_integrity_error("bookings_pkey"))
    assert is_seat_conflict(_integrity_error(None, f'violates "{SEAT_UNIQUE_CONSTRAINT}"'))
    assert not is_seat_conflict(_integrity_error(None, "violates not-null constraint"))
