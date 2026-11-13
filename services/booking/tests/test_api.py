"""Endpoint tests against the real local Postgres (127.0.0.1:5433) and Redis (127.0.0.1:6380,
database 15), with catalog-service replaced by an httpx MockTransport. Skipped without both."""

import asyncio
import os
import random
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from booking_svc.holds import hold_zset_key
from booking_svc.models import Booking, BookingSeat

DB = ("127.0.0.1", 5433)
REDIS = ("127.0.0.1", 6380)
TEST_REDIS_URL = f"redis://{REDIS[0]}:{REDIS[1]}/15"


def _reachable(address: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(address, timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable(DB) and _reachable(REDIS)),
    reason="local postgres (127.0.0.1:5433) and redis (127.0.0.1:6380) are not both running",
)

# --- catalog stand-in -------------------------------------------------------------------

EVENTS: dict[int, dict] = {}
CATALOG_DOWN_EVENT = 1


def catalog_handler(request: httpx.Request) -> httpx.Response:
    event_id = int(request.url.path.rsplit("/", 1)[-1])
    if event_id == CATALOG_DOWN_EVENT:
        raise httpx.ConnectError("catalog down", request=request)
    if event_id not in EVENTS:
        return httpx.Response(404, json={"detail": {"code": "EVENT_NOT_FOUND"}})
    return httpx.Response(200, json=EVENTS[event_id])


def make_event(sales_open_in_s: int = -60) -> int:
    event_id = random.randint(1_000_000_000, 2_000_000_000)
    now = datetime.now(UTC)
    EVENTS[event_id] = {
        "id": event_id,
        "title": "Rock Night",
        "venue": "Big Hall",
        "city": "Istanbul",
        "starts_at": (now + timedelta(days=30)).isoformat(),
        "sales_open_at": (now + timedelta(seconds=sales_open_in_s)).isoformat(),
        "sections": [
            {"code": "A", "name": "Front", "price_cents": 150_000, "rows": 5, "seats_per_row": 20},
            {"code": "B", "name": "Back", "price_cents": 50_000, "rows": 10, "seats_per_row": 30},
        ],
    }
    return event_id


# --- app under test -----------------------------------------------------------------------

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def storage_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("storage")


@pytest.fixture(scope="module")
def client(tmp_path_factory, storage_dir):
    public_path = tmp_path_factory.mktemp("keys") / "public.pem"
    public_path.write_bytes(
        _private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    password = os.environ.get("BOOKING_DB_PASSWORD", "booking-local")
    with pytest.MonkeyPatch.context() as env:
        env.setenv(
            "BOOKING_DATABASE_URL",
            f"postgresql+asyncpg://booking_user:{password}@{DB[0]}:{DB[1]}/bookingdb",
        )
        env.setenv("REDIS_URL", TEST_REDIS_URL)
        env.setenv("JWT_PUBLIC_KEY_PATH", str(public_path))
        env.setenv("CATALOG_URL", "http://catalog.test")
        env.setenv("LOCAL_STORAGE_DIR", str(storage_dir))
        from booking_svc.main import create_app

        app = create_app(catalog_transport=httpx.MockTransport(catalog_handler))
        with TestClient(app) as test_client:
            yield test_client


def auth(user_id: int, role: str = "customer") -> dict[str, str]:
    now = int(time.time())
    claims = {
        "iss": "flashtix-auth",
        "aud": "flashtix",
        "sub": str(user_id),
        "email": f"user{user_id}@example.com",
        "name": f"User {user_id}",
        "role": role,
        "iat": now,
        "exp": now + 600,
    }
    return {"Authorization": f"Bearer {jwt.encode(claims, _private_key, algorithm='RS256')}"}


def new_user() -> int:
    return random.randint(10_000_000, 99_999_999)


def hold(client, user, event_id, seats):
    return client.post(
        "/api/booking/holds", json={"event_id": event_id, "seats": seats}, headers=auth(user)
    )


def purchase(client, user, event_id, seats):
    body = {"event_id": event_id, "seats": seats, "payment": {"method": "mock"}}
    return client.post("/api/booking/purchase", json=body, headers=auth(user))


def availability(client, event_id, user=None):
    headers = auth(user) if user else {}
    return client.get(f"/api/booking/events/{event_id}/availability", headers=headers).json()


def state(client):
    return client.app.state.booking


# --- holds ---------------------------------------------------------------------------------


def test_hold_then_conflict(client):
    event, u1, u2 = make_event(), new_user(), new_user()
    first = hold(client, u1, event, ["A-1-1", "A-1-2"])
    assert first.status_code == 200
    assert first.json()["seats"] == ["A-1-1", "A-1-2"]
    conflict = hold(client, u2, event, ["A-1-2", "A-1-3"])
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"code": "SEATS_UNAVAILABLE", "seats": ["A-1-2"]}
    seen = availability(client, event, u1)
    assert sorted(seen["held"]) == ["A-1-1", "A-1-2"]
    assert sorted(seen["my_holds"]) == ["A-1-1", "A-1-2"]
    assert availability(client, event)["my_holds"] == []  # anonymous viewer


@pytest.mark.parametrize(
    ("seats", "code"),
    [
        ([f"A-1-{n}" for n in range(1, 8)], "TOO_MANY_SEATS"),
        (["A-1-1", "A-1-1"], "DUPLICATE_SEATS"),
        (["A-9-1", "Z-1-1"], "INVALID_SEATS"),
    ],
)
def test_hold_rejects_bad_seat_lists(client, seats, code):
    response = hold(client, new_user(), make_event(), seats)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_unknown_event_and_unreachable_catalog(client):
    missing = hold(client, new_user(), 999, ["A-1-1"])
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "EVENT_NOT_FOUND")
    down = hold(client, new_user(), CATALOG_DOWN_EVENT, ["A-1-1"])
    assert (down.status_code, down.json()["detail"]["code"]) == (503, "CATALOG_UNAVAILABLE")


def test_sales_not_open(client):
    response = hold(client, new_user(), make_event(sales_open_in_s=3600), ["A-1-1"])
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "SALES_NOT_OPEN")


def test_holds_need_a_token(client):
    response = client.post("/api/booking/holds", json={"event_id": 1, "seats": ["A-1-1"]})
    assert response.status_code == 401


def test_release_frees_only_your_seats(client):
    event, u1, u2 = make_event(), new_user(), new_user()
    hold(client, u1, event, ["A-1-1"])
    hold(client, u2, event, ["A-1-2"])
    body = {"event_id": event, "seats": ["A-1-1", "A-1-2"]}
    assert client.post("/api/booking/holds/release", json=body, headers=auth(u1)).status_code == 204
    assert availability(client, event)["held"] == ["A-1-2"]
    assert hold(client, u2, event, ["A-1-1"]).status_code == 200


# --- purchase ------------------------------------------------------------------------------


def test_purchase_without_hold_is_409(client):
    response = purchase(client, new_user(), make_event(), ["A-1-1"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "HOLD_EXPIRED", "seats": ["A-1-1"]}


def test_full_purchase_flow(client, storage_dir):
    event, user, other = make_event(), new_user(), new_user()
    assert hold(client, user, event, ["A-1-1", "B-2-3"]).status_code == 200
    bought = purchase(client, user, event, ["A-1-1", "B-2-3"])
    assert bought.status_code == 201
    booking = bought.json()
    assert booking["total_price_cents"] == 200_000
    assert booking["seat_count"] == 2
    assert [s["section_name"] for s in booking["seats"]] == ["Front", "Back"]
    assert booking["ticket_ready"] is False

    seen = availability(client, event, user)
    assert (seen["sold"], seen["held"], seen["my_holds"]) == (["A-1-1", "B-2-3"], [], [])

    mine = client.get("/api/booking/me", headers=auth(user)).json()
    assert [b["id"] for b in mine] == [booking["id"]]
    detail = client.get(f"/api/booking/{booking['id']}", headers=auth(user))
    assert detail.status_code == 200
    other_view = client.get(f"/api/booking/{booking['id']}", headers=auth(other))
    assert other_view.status_code == 404

    tickets = storage_dir / "tickets"
    tickets.mkdir(exist_ok=True)
    (tickets / f"{booking['id']}.pdf").write_bytes(b"%PDF-1.4")
    assert client.get(f"/api/booking/{booking['id']}", headers=auth(user)).json()["ticket_ready"]


def test_purchase_publishes_booking_confirmed(client):
    published = []

    class Recorder:
        async def publish(self, payload: dict) -> None:
            published.append(payload)

        async def aclose(self) -> None:
            return None

    original = state(client).publisher
    state(client).publisher = Recorder()
    try:
        event, user = make_event(), new_user()
        hold(client, user, event, ["A-2-1"])
        booking = purchase(client, user, event, ["A-2-1"]).json()
    finally:
        state(client).publisher = original
    assert [p["booking_id"] for p in published] == [booking["id"]]
    assert published[0]["event"]["id"] == event


def bought_booking(client, seat="A-4-1") -> tuple[int, dict]:
    event, user = make_event(), new_user()
    assert hold(client, user, event, [seat]).status_code == 200
    response = purchase(client, user, event, [seat])
    assert response.status_code == 201
    return user, response.json()


def test_ticket_is_pending_until_the_pdf_exists(client, storage_dir):
    user, booking = bought_booking(client)
    url = f"/api/booking/{booking['id']}/ticket"
    pending = client.get(url, headers=auth(user))
    assert (pending.status_code, pending.json()) == (202, {"status": "pending"})

    (storage_dir / "tickets").mkdir(exist_ok=True)
    (storage_dir / "tickets" / f"{booking['id']}.pdf").write_bytes(b"%PDF-1.4 test")
    ready = client.get(url, headers=auth(user))
    assert ready.status_code == 200
    assert ready.headers["content-type"] == "application/pdf"
    assert f'filename="flashtix-{booking["id"]}.pdf"' in ready.headers["content-disposition"]
    assert ready.content == b"%PDF-1.4 test"
    assert client.get(f"/api/booking/{booking['id']}", headers=auth(user)).json()["ticket_ready"]


def test_ticket_of_someone_else_is_404(client):
    _, booking = bought_booking(client)
    other = client.get(f"/api/booking/{booking['id']}/ticket", headers=auth(new_user()))
    assert other.status_code == 404


def test_republish_by_owner_or_organizer(client):
    published = []

    class Recorder:
        async def publish(self, payload: dict) -> None:
            published.append(payload["booking_id"])

        async def aclose(self) -> None:
            return None

    user, booking = bought_booking(client)
    url = f"/api/booking/{booking['id']}/republish"
    original = state(client).publisher
    state(client).publisher = Recorder()
    try:
        assert client.post(url, headers=auth(user)).status_code == 202
        assert client.post(url, headers=auth(new_user(), role="organizer")).status_code == 202
        assert client.post(url, headers=auth(new_user())).status_code == 404
    finally:
        state(client).publisher = original
    assert published == [booking["id"], booking["id"]]


def test_expired_hold_cannot_be_bought(client):
    event, u1, u2 = make_event(), new_user(), new_user()
    hold(client, u1, event, ["A-1-1"])

    async def expire() -> None:
        await state(client).holds.redis.zadd(hold_zset_key(event), {"A-1-1": 1})

    client.portal.call(expire)
    response = purchase(client, u1, event, ["A-1-1"])
    assert (response.status_code, response.json()["detail"]["code"]) == (409, "HOLD_EXPIRED")
    assert hold(client, u2, event, ["A-1-1"]).status_code == 200


def test_sold_state_survives_redis_data_loss(client):
    event, buyer, other = make_event(), new_user(), new_user()
    hold(client, buyer, event, ["A-3-3"])
    assert purchase(client, buyer, event, ["A-3-3"]).status_code == 201

    async def lose_redis_data() -> None:
        await state(client).holds.redis.flushdb()  # database 15 only

    client.portal.call(lose_redis_data)
    assert availability(client, event)["sold"] == ["A-3-3"]  # rebuilt from Postgres
    retry = hold(client, other, event, ["A-3-3"])
    assert retry.json()["detail"] == {"code": "SEATS_UNAVAILABLE", "seats": ["A-3-3"]}


def test_database_constraint_is_the_final_guard(client):
    """Simulates the accepted race: Redis says the buyer holds the seat, but the seat was
    already sold in the database. UNIQUE(event_id, seat_id) must reject the second sale."""
    event, user = make_event(), new_user()
    assert hold(client, user, event, ["A-4-4"]).status_code == 200

    async def sell_behind_redis_back() -> None:
        async with state(client).sessionmaker() as session, session.begin():
            session.add(
                Booking(
                    user_id=1,
                    user_email="race@example.com",
                    user_name="Race",
                    event_id=event,
                    event_title="Rock Night",
                    event_starts_at=datetime.now(UTC),
                    venue="Big Hall",
                    city="Istanbul",
                    seat_count=1,
                    total_price_cents=150_000,
                    seats=[
                        BookingSeat(
                            event_id=event, seat_id="A-4-4", section_name="Front", price_cents=1
                        )
                    ],
                )
            )

    client.portal.call(sell_behind_redis_back)
    response = purchase(client, user, event, ["A-4-4"])
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "SEATS_ALREADY_SOLD", "seats": ["A-4-4"]}
    assert availability(client, event)["sold"] == ["A-4-4"]  # Redis re-synced


def test_concurrent_buyers_get_a_seat_exactly_once(client):
    event, users = make_event(), [new_user() for _ in range(20)]

    async def race() -> list[tuple[int, int | None]]:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:

            async def attempt(user: int) -> tuple[int, int | None]:
                held = await http.post(
                    "/api/booking/holds",
                    json={"event_id": event, "seats": ["B-1-1"]},
                    headers=auth(user),
                )
                if held.status_code != 200:
                    return held.status_code, None
                body = {"event_id": event, "seats": ["B-1-1"], "payment": {"method": "mock"}}
                bought = await http.post("/api/booking/purchase", json=body, headers=auth(user))
                return held.status_code, bought.status_code

            return await asyncio.gather(*(attempt(user) for user in users))

    results = client.portal.call(race)
    assert sorted(status for status, _ in results) == [200] + [409] * 19
    assert [bought for _, bought in results if bought is not None] == [201]


# --- routing -------------------------------------------------------------------------------


def test_organizer_stats_in_one_request(client):
    event, unknown = make_event(), make_event()
    buyer, holder = new_user(), new_user()
    hold(client, buyer, event, ["A-1-1", "A-1-2"])
    assert purchase(client, buyer, event, ["A-1-1", "A-1-2"]).status_code == 201
    hold(client, holder, event, ["B-1-1"])

    response = client.get(
        f"/api/booking/stats?event_ids={event},{unknown},{event}",
        headers=auth(new_user(), role="organizer"),
    )
    assert response.status_code == 200
    assert response.json() == [
        {"event_id": event, "sold": 2, "held": 1},
        {"event_id": unknown, "sold": 0, "held": 0},  # duplicates dropped, unknown → zeros
    ]


@pytest.mark.parametrize("query", ["", "abc", "1,x", ",".join(str(i) for i in range(101))])
def test_stats_rejects_bad_event_ids(client, query):
    response = client.get(
        f"/api/booking/stats?event_ids={query}", headers=auth(new_user(), role="organizer")
    )
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "INVALID_EVENT_IDS")


def test_daily_report_download(client, storage_dir):
    organizer = auth(new_user(), role="organizer")
    missing = client.get("/api/booking/reports/2026-11-12", headers=organizer)
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "REPORT_NOT_FOUND")

    (storage_dir / "reports").mkdir(exist_ok=True)
    (storage_dir / "reports" / "2026-11-12.csv").write_text("event_id,bookings\n7,3\n")
    report = client.get("/api/booking/reports/2026-11-12", headers=organizer)
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/csv")
    assert 'filename="flashtix-report-2026-11-12.csv"' in report.headers["content-disposition"]
    assert report.text == "event_id,bookings\n7,3\n"

    assert client.get("/api/booking/reports/12-11-2026", headers=organizer).status_code == 422
    # A traversal attempt never reaches storage: either the route doesn't match (404, the
    # decoded "/" splits the path) or the date doesn't parse (422).
    traversal = client.get("/api/booking/reports/..%2Fsecrets", headers=organizer)
    assert traversal.status_code in (404, 422)
    assert "REPORT_NOT_FOUND" not in traversal.text


def test_organizer_endpoints_are_forbidden_for_customers(client):
    # 403 (not 422) also proves /stats and /reports aren't swallowed by /{booking_id}.
    customer = auth(new_user())
    assert client.get("/api/booking/stats?event_ids=1", headers=customer).status_code == 403
    assert client.get("/api/booking/reports/2026-11-12", headers=customer).status_code == 403


def test_static_routes_are_not_captured_by_booking_id(client):
    user = new_user()
    assert client.get("/api/booking/me", headers=auth(user)).json() == []
    assert client.get("/api/booking/not-a-uuid", headers=auth(user)).status_code == 422
    missing = client.get(f"/api/booking/{uuid.uuid4()}", headers=auth(user))
    assert (missing.status_code, missing.json()["detail"]["code"]) == (404, "BOOKING_NOT_FOUND")


def test_probes(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").json()["checks"] == {"db": "ok", "redis": "ok"}
