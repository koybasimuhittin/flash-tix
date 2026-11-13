"""make smoke: end-to-end check of the whole stack through the gateway.

Creates its own fresh event each run (as the bootstrap organizer), so it can be rerun at any time;
a seeded event would already have B-1-1 sold after the first run. Exits non-zero on any failure.
Stdlib + threads only.
"""

import sys
import threading
import time
import urllib.parse
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_oversell  # noqa: E402
from flashtix_client import api, fail, login, ok, organizer_token  # noqa: E402

CONCURRENT_BUYERS = 20
TICKET_TIMEOUT_S = 30


def new_user(tag: str) -> str:
    email = f"smoke-{tag}-{uuid.uuid4().hex[:10]}@example.com"
    status, body = api(
        "POST", "/api/auth/register", {"email": email, "password": "smoke-password", "name": tag}
    )
    if status != 201:
        fail(f"register {email}: {status} {body}")
    return login(email, "smoke-password")


def hold(token: str, event_id: int, seats: list[str]) -> tuple[int, object]:
    return api("POST", "/api/booking/holds", {"event_id": event_id, "seats": seats}, token=token)


def purchase(token: str, event_id: int, seats: list[str]) -> tuple[int, object]:
    body = {"event_id": event_id, "seats": seats, "payment": {"method": "mock"}}
    return api("POST", "/api/booking/purchase", body, token=token)


def create_event() -> tuple[int, str]:
    now = datetime.now(UTC)
    title = f"Smoke test {now:%Y-%m-%d %H:%M:%S} {uuid.uuid4().hex[:6]}"
    status, event = api(
        "POST",
        "/api/events",
        {
            "title": title,
            "description": "Created by make smoke.",
            "venue": "Smoke Hall",
            "city": "İstanbul",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "sales_open_at": (now - timedelta(minutes=1)).isoformat(),
            "sections": [
                {"code": code, "name": name, "price_cents": cents, "rows": 2, "seats_per_row": 5}
                for code, name, cents in (("A", "Front", 10_000), ("B", "Back", 5_000))
            ],
        },
        token=organizer_token(),
    )
    if status != 201:
        fail(f"create smoke event: {status} {event}")
    return event["id"], title


def race_for_one_seat(event_id: int) -> None:
    """20 fresh users try to hold and buy B-1-1 at the same moment: exactly one may win."""
    tokens = list(
        ThreadPoolExecutor(max_workers=CONCURRENT_BUYERS).map(
            new_user, [f"racer{i}" for i in range(CONCURRENT_BUYERS)]
        )
    )
    start_line = threading.Barrier(CONCURRENT_BUYERS)

    def attempt(token: str) -> int:
        start_line.wait()  # release every hold at once
        if hold(token, event_id, ["B-1-1"])[0] != 200:
            return 0
        return 1 if purchase(token, event_id, ["B-1-1"])[0] == 201 else 0

    with ThreadPoolExecutor(max_workers=CONCURRENT_BUYERS) as pool:
        winners = sum(pool.map(attempt, tokens))
    if winners != 1:
        fail(f"{winners} of {CONCURRENT_BUYERS} concurrent buyers got B-1-1 (expected exactly 1)")
    ok(f"{CONCURRENT_BUYERS} concurrent buyers → exactly 1 got B-1-1")


def main() -> None:
    event_id, title = create_event()
    ok(f"fresh event {event_id} on sale")

    u1, u2 = new_user("u1"), new_user("u2")
    ok("registered and logged in two users")

    status, events = api("GET", f"/api/events?q={urllib.parse.quote(title)}")
    if status != 200 or not any(event["id"] == event_id for event in events):
        fail(f"event {event_id} not in the upcoming list: {status}")
    ok("event listed by catalog")

    status, body = hold(u1, event_id, ["A-1-1", "A-1-2"])
    if status != 200:
        fail(f"u1 hold: {status} {body}")
    status, body = hold(u2, event_id, ["A-1-2"])
    if status != 409 or body["detail"].get("seats") != ["A-1-2"]:
        fail(f"u2 hold should be 409 listing A-1-2, got {status} {body}")
    ok("u1 holds A-1-1,A-1-2; u2 gets 409 for A-1-2")

    status, booking = purchase(u1, event_id, ["A-1-1", "A-1-2"])
    if status != 201:
        fail(f"u1 purchase: {status} {booking}")
    status, availability = api("GET", f"/api/booking/events/{event_id}/availability")
    if status != 200 or not {"A-1-1", "A-1-2"} <= set(availability["sold"]):
        fail(f"availability after purchase: {status} {availability}")
    ok("purchase 201; both seats shown as sold")

    deadline = time.monotonic() + TICKET_TIMEOUT_S
    while True:
        status, pdf = api("GET", f"/api/booking/{booking['id']}/ticket", token=u1)
        if status == 200 and isinstance(pdf, bytes) and pdf.startswith(b"%PDF"):
            break
        if time.monotonic() > deadline:
            fail(f"ticket not ready after {TICKET_TIMEOUT_S} s (last status {status})")
        time.sleep(0.5)
    ok(f"ticket PDF ready ({len(pdf)} bytes)")

    race_for_one_seat(event_id)

    check_oversell.check()
    print("smoke test passed", flush=True)


if __name__ == "__main__":
    main()
