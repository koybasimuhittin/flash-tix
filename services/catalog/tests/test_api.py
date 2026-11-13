"""Endpoint tests against the real local Postgres (127.0.0.1:5433) and Redis (127.0.0.1:6380):
`docker compose up -d --wait postgres redis`. Skipped when either isn't reachable."""

import os
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from redis import Redis

from catalog_svc.cache import detail_key, event_version_key

DB = ("127.0.0.1", 5433)
REDIS = ("127.0.0.1", 6380)


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


@pytest.fixture(scope="module")
def private_key(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path_factory.mktemp("keys") / "public.pem"
    path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return key, path


def _make_client(private_key, cache_enabled: bool, redis=REDIS):
    _, public_path = private_key
    password = os.environ.get("CATALOG_DB_PASSWORD", "catalog-local")
    with pytest.MonkeyPatch.context() as env:
        env.setenv(
            "CATALOG_DATABASE_URL",
            f"postgresql+asyncpg://catalog_user:{password}@{DB[0]}:{DB[1]}/catalogdb",
        )
        env.setenv("REDIS_URL", f"redis://{redis[0]}:{redis[1]}/0")
        env.setenv("JWT_PUBLIC_KEY_PATH", str(public_path))
        env.setenv("CATALOG_CACHE_ENABLED", str(cache_enabled).lower())
        from catalog_svc.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture(scope="module")
def client(private_key):
    yield from _make_client(private_key, cache_enabled=True)


@pytest.fixture(scope="module")
def uncached_client(private_key):
    yield from _make_client(private_key, cache_enabled=False)


@pytest.fixture(scope="module")
def redis_down_client(private_key):
    # Nothing listens on port 1; the Redis client connects lazily, so startup still works.
    yield from _make_client(private_key, cache_enabled=True, redis=("127.0.0.1", 1))


def token(private_key, user_id: int, role: str) -> dict[str, str]:
    now = int(time.time())
    claims = {
        "iss": "flashtix-auth",
        "aud": "flashtix",
        "sub": str(user_id),
        "email": f"user{user_id}@example.com",
        "name": "Test",
        "role": role,
        "iat": now,
        "exp": now + 600,
    }
    encoded = jwt.encode(claims, private_key[0], algorithm="RS256")
    return {"Authorization": f"Bearer {encoded}"}


@pytest.fixture
def organizer(private_key):
    return token(private_key, 9_000_000 + uuid.uuid4().int % 1_000_000, "organizer")


@pytest.fixture
def customer(private_key):
    return token(private_key, 8_000_000 + uuid.uuid4().int % 1_000_000, "customer")


def unique_city() -> str:
    return f"Testcity-{uuid.uuid4().hex[:10]}"


def event_body(city: str, **overrides) -> dict:
    starts = datetime.now(UTC) + timedelta(days=30)
    body = {
        "title": "Rock Night",
        "description": "Loud.",
        "venue": "Big Hall",
        "city": city,
        "starts_at": starts.isoformat(),
        "sales_open_at": (starts - timedelta(days=10)).isoformat(),
        "sections": [
            {"code": "A", "name": "Front", "price_cents": 15000, "rows": 5, "seats_per_row": 20},
            {"code": "B", "name": "Back", "price_cents": 9000, "rows": 10, "seats_per_row": 30},
        ],
    }
    return body | overrides


def create(client, headers, city: str, **overrides):
    return client.post("/api/events", json=event_body(city, **overrides), headers=headers)


def test_organizer_creates_event(client, organizer):
    response = create(client, organizer, unique_city())
    assert response.status_code == 201
    event = response.json()
    assert event["capacity"] == 5 * 20 + 10 * 30
    assert event["min_price_cents"] == 9000
    assert [s["code"] for s in event["sections"]] == ["A", "B"]
    assert [s["sort_order"] for s in event["sections"]] == [0, 1]


def test_customer_and_anonymous_cannot_create(client, customer):
    city = unique_city()
    forbidden = create(client, customer, city)
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == {"code": "FORBIDDEN"}
    assert create(client, {}, city).status_code == 401


def section(**overrides) -> dict:
    return {"code": "A", "name": "x", "price_cents": 1, "rows": 1, "seats_per_row": 1} | overrides


@pytest.mark.parametrize(
    "overrides",
    [
        {"sections": []},
        {"sections": [section(), section(name="y")]},
        {"sections": [section(rows=51)]},
        {"sections": [section(seats_per_row=61)]},
        {"sections": [section(code="a1")]},
        {"sales_open_at": (datetime.now(UTC) + timedelta(days=60)).isoformat()},
        {"starts_at": "2030-01-01T20:00:00"},  # timezone required
    ],
    ids=["no-sections", "duplicate-codes", "too-many-rows", "too-many-seats", "bad-code",
         "sales-after-start", "naive-datetime"],
)  # fmt: skip
def test_invalid_events_are_422(client, organizer, overrides):
    assert create(client, organizer, unique_city(), **overrides).status_code == 422


def test_detail_is_cached_and_404_for_unknown(client, organizer):
    event_id = create(client, organizer, unique_city()).json()["id"]
    first = client.get(f"/api/events/{event_id}")
    second = client.get(f"/api/events/{event_id}")
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("MISS", "HIT")
    assert first.json() == second.json()

    missing = client.get("/api/events/999999999")
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "EVENT_NOT_FOUND"}


def test_list_is_cached_and_a_new_event_invalidates_it(client, organizer):
    city = unique_city()
    create(client, organizer, city, title="First")
    first = client.get("/api/events", params={"city": city})
    second = client.get("/api/events", params={"city": f"  {city.upper()} "})  # same query
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("MISS", "HIT")
    assert [e["title"] for e in second.json()] == ["First"]
    assert set(first.json()[0]) == {
        "id", "title", "venue", "city", "starts_at", "sales_open_at", "min_price_cents", "capacity"
    }  # fmt: skip

    create(client, organizer, city, title="Second")
    after_write = client.get("/api/events", params={"city": city})
    assert after_write.headers["x-cache"] == "MISS"
    assert {e["title"] for e in after_write.json()} == {"First", "Second"}


def test_list_search_and_past_events(client, organizer):
    city = unique_city()
    past_start = datetime.now(UTC) - timedelta(days=1)
    create(client, organizer, city, title="Jazz 100%_Live", venue="Club")
    create(
        client, organizer, city, title="Old Show",
        starts_at=past_start.isoformat(),
        sales_open_at=(past_start - timedelta(days=5)).isoformat(),
    )  # fmt: skip
    titles = [e["title"] for e in client.get("/api/events", params={"city": city}).json()]
    assert titles == ["Jazz 100%_Live"]  # past events are not listed
    found = client.get("/api/events", params={"city": city, "q": "100%_"}).json()
    assert [e["title"] for e in found] == ["Jazz 100%_Live"]
    assert client.get("/api/events", params={"city": city, "q": "100%x"}).json() == []


def test_patch_invalidates_detail_and_lists(client, organizer):
    city = unique_city()
    event_id = create(client, organizer, city).json()["id"]
    client.get(f"/api/events/{event_id}")
    client.get("/api/events", params={"city": city})

    sales_open = datetime.now(UTC) + timedelta(seconds=120)
    patched = client.patch(
        f"/api/events/{event_id}",
        json={"title": "Flash Sale!", "sales_open_at": sales_open.isoformat()},
        headers=organizer,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Flash Sale!"

    detail = client.get(f"/api/events/{event_id}")
    assert detail.headers["x-cache"] == "MISS"
    assert detail.json()["title"] == "Flash Sale!"
    listed = client.get("/api/events", params={"city": city})
    assert listed.headers["x-cache"] == "MISS"
    assert listed.json()[0]["title"] == "Flash Sale!"


def test_patch_rules(client, organizer, customer, private_key):
    event_id = create(client, organizer, unique_city()).json()["id"]
    other_organizer = token(private_key, 7_000_000 + uuid.uuid4().int % 1_000_000, "organizer")
    url = f"/api/events/{event_id}"
    assert client.patch(url, json={"title": "x"}, headers=customer).status_code == 403
    not_owner = client.patch(url, json={"title": "x"}, headers=other_organizer)
    assert (not_owner.status_code, not_owner.json()["detail"]) == (
        403, {"code": "NOT_EVENT_OWNER"},
    )  # fmt: skip
    late = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    bad_schedule = client.patch(url, json={"sales_open_at": late}, headers=organizer)
    assert bad_schedule.status_code == 422
    assert bad_schedule.json()["detail"] == {"code": "SALES_OPEN_AFTER_START"}
    assert client.get(url).json()["title"] == "Rock Night"  # nothing was changed
    assert client.patch("/api/events/999999999", json={}, headers=organizer).status_code == 404


def test_mine_lists_only_own_events_and_is_not_cached(client, organizer, customer, private_key):
    past_start = datetime.now(UTC) - timedelta(days=2)
    older = create(
        client, organizer, unique_city(), title="Past",
        starts_at=past_start.isoformat(),
        sales_open_at=(past_start - timedelta(days=1)).isoformat(),
    ).json()  # fmt: skip
    newer = create(client, organizer, unique_city(), title="Future").json()
    other = token(private_key, 6_000_000 + uuid.uuid4().int % 1_000_000, "organizer")
    create(client, other, unique_city(), title="Someone else's")

    mine = client.get("/api/events/mine", headers=organizer)
    assert mine.status_code == 200
    assert mine.headers["x-cache"] == "BYPASS"
    assert [e["id"] for e in mine.json()] == [newer["id"], older["id"]]
    assert mine.json()[0]["capacity"] == 400

    assert client.get("/api/events/mine", headers=customer).status_code == 403
    assert client.get("/api/events/mine").status_code == 401  # route matched, not /{id} → 422


def test_cache_disabled_bypasses(uncached_client, organizer):
    event_id = create(uncached_client, organizer, unique_city()).json()["id"]
    for _ in range(2):
        assert uncached_client.get(f"/api/events/{event_id}").headers["x-cache"] == "BYPASS"
        assert uncached_client.get("/api/events").headers["x-cache"] == "BYPASS"


def test_probes(client):
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"db": "ok", "redis": "ok"}


def test_a_late_cache_write_cannot_resurrect_an_old_detail(client, organizer):
    event_id = create(client, organizer, unique_city()).json()["id"]
    cache = Redis(host=REDIS[0], port=REDIS[1], decode_responses=True)
    before = int(cache.get(event_version_key(event_id)) or 0)
    stale = client.get(f"/api/events/{event_id}").text  # a reader that read the DB before...

    patched = client.patch(f"/api/events/{event_id}", json={"title": "Renamed"}, headers=organizer)
    assert patched.status_code == 200
    # ...stores its body only after the write committed: it lands under the old version.
    cache.set(detail_key(event_id, before), stale)

    detail = client.get(f"/api/events/{event_id}")
    assert (detail.headers["x-cache"], detail.json()["title"]) == ("MISS", "Renamed")
    cache.close()


def test_redis_down_serves_from_the_database(redis_down_client, client, organizer):
    city = unique_city()
    event_id = create(client, organizer, city).json()["id"]

    detail = redis_down_client.get(f"/api/events/{event_id}")
    assert (detail.status_code, detail.headers["x-cache"]) == (200, "BYPASS")
    listed = redis_down_client.get("/api/events", params={"city": city})
    assert (listed.status_code, listed.headers["x-cache"]) == (200, "BYPASS")
    assert [event["id"] for event in listed.json()] == [event_id]
