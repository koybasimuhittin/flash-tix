"""The monolith serves the whole API from one process: auth, catalog and booking together, with
booking → catalog as an in-process call. Runs against the compose Postgres (127.0.0.1:5433) and
Redis (127.0.0.1:6380, database 14); skipped without them unless REQUIRE_DB=1."""

import os
import socket
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

DB, REDIS = ("127.0.0.1", 5433), ("127.0.0.1", 6380)
ORGANIZER = ("monolith-organizer@example.com", "monolith-organizer-pass")


def _reachable(address: tuple[str, int]) -> bool:
    try:
        with socket.create_connection(address, timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if not (_reachable(DB) and _reachable(REDIS)):
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail("REQUIRE_DB=1 but the compose postgres/redis are unreachable")
        pytest.skip("compose postgres (5433) and redis (6380) are not both running")

    keys = tmp_path_factory.mktemp("keys")
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
         "-out", str(keys / "private.pem")],
        check=True, capture_output=True,
    )  # fmt: skip
    subprocess.run(
        ["openssl", "pkey", "-in", str(keys / "private.pem"), "-pubout",
         "-out", str(keys / "public.pem")],
        check=True, capture_output=True,
    )  # fmt: skip

    def url(user: str, db: str, default_password: str) -> str:
        password = os.environ.get(f"{user.split('_')[0].upper()}_DB_PASSWORD", default_password)
        return f"postgresql+asyncpg://{user}:{password}@{DB[0]}:{DB[1]}/{db}"

    with pytest.MonkeyPatch.context() as env:
        env.setenv("AUTH_DATABASE_URL", url("auth_user", "authdb", "auth-local"))
        env.setenv("CATALOG_DATABASE_URL", url("catalog_user", "catalogdb", "catalog-local"))
        env.setenv("BOOKING_DATABASE_URL", url("booking_user", "bookingdb", "booking-local"))
        env.setenv("REDIS_URL", f"redis://{REDIS[0]}:{REDIS[1]}/14")
        env.setenv("JWT_PRIVATE_KEY_PATH", str(keys / "private.pem"))
        env.setenv("JWT_PUBLIC_KEY_PATH", str(keys / "public.pem"))
        env.setenv("BCRYPT_ROUNDS", "4")
        env.setenv("BOOTSTRAP_ORGANIZER_EMAIL", ORGANIZER[0])
        env.setenv("BOOTSTRAP_ORGANIZER_PASSWORD", ORGANIZER[1])
        env.setenv("EVENT_BACKEND", "log")
        env.setenv("STORAGE_BACKEND", "local")
        env.setenv("LOCAL_STORAGE_DIR", str(tmp_path_factory.mktemp("storage")))
        from monolith_svc.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


def login(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_one_process_serves_the_whole_flow(client):
    organizer = login(client, *ORGANIZER)
    now = datetime.now(UTC)
    created = client.post(
        "/api/events",
        json={
            "title": f"Monolith check {uuid.uuid4().hex[:8]}",
            "description": "",
            "venue": "Hall",
            "city": "İstanbul",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "sales_open_at": (now - timedelta(minutes=1)).isoformat(),
            "sections": [
                {"code": "A", "name": "Front", "price_cents": 1000, "rows": 2, "seats_per_row": 3}
            ],
        },
        headers=organizer,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    email = f"monolith-{uuid.uuid4().hex[:10]}@example.com"
    registered = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "M"}
    )
    assert registered.status_code == 201
    customer = login(client, email, "password123")

    # booking validates the event through its catalog client, in-process here.
    held = client.post(
        "/api/booking/holds", json={"event_id": event_id, "seats": ["A-1-1"]}, headers=customer
    )
    assert held.status_code == 200, held.text
    bought = client.post(
        "/api/booking/purchase",
        json={"event_id": event_id, "seats": ["A-1-1"], "payment": {"method": "mock"}},
        headers=customer,
    )
    assert bought.status_code == 201, bought.text
    assert bought.json()["total_price_cents"] == 1000

    mine = client.get("/api/booking/me", headers=customer).json()
    assert [seat["seat_id"] for seat in mine[0]["seats"]] == ["A-1-1"]


def test_readiness_covers_every_dependency(client):
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {
        "auth_db": "ok",
        "catalog_db": "ok",
        "booking_db": "ok",
        "redis": "ok",
    }
