"""make seed: demo events created through the API as the bootstrap organizer.

Idempotent by title: existing events are kept. The flash-sale event is re-armed on every run
(sales open 2 minutes from now), which is what the demo and the load tests need.
Stdlib only, so it runs on any machine with Python 3.12+.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flashtix_client import api, fail, ok, organizer_token  # noqa: E402

FLASH_SALE_TITLE = "FlashTix Launch Night (flash sale)"
FLASH_SALE_OPENS_IN = timedelta(minutes=2)


def section(code: str, name: str, price_try: int, rows: int, seats_per_row: int) -> dict:
    return {
        "code": code,
        "name": name,
        "price_cents": price_try * 100,
        "rows": rows,
        "seats_per_row": seats_per_row,
    }


EVENTS = [
    {  # capacity 1000: the flash-sale target for demos and load tests
        "title": FLASH_SALE_TITLE,
        "venue": "Volkswagen Arena",
        "city": "İstanbul",
        "days_ahead": 14,
        "sections": [
            section("A", "Front", 1500, 5, 20),
            section("B", "Middle", 900, 10, 30),
            section("C", "Back", 450, 15, 40),
        ],
    },
    {
        "title": "Bosphorus Jazz Evening",
        "venue": "Zorlu PSM",
        "city": "İstanbul",
        "days_ahead": 7,
        "sections": [section("A", "Stalls", 800, 8, 20), section("B", "Balcony", 500, 6, 20)],
    },
    {
        "title": "Anatolian Rock Fest",
        "venue": "Congresium",
        "city": "Ankara",
        "days_ahead": 21,
        "sections": [section("A", "Floor", 700, 10, 30)],
    },
    {
        "title": "Aegean Indie Night",
        "venue": "Kültürpark Açıkhava",
        "city": "İzmir",
        "days_ahead": 10,
        "sections": [section("A", "Front", 600, 5, 25), section("B", "Back", 350, 10, 25)],
    },
    {
        "title": "Classical Sundays: Vivaldi",
        "venue": "Süreyya Opera",
        "city": "İstanbul",
        "days_ahead": 30,
        "sections": [section("A", "Parterre", 650, 12, 18), section("B", "Loge", 950, 4, 10)],
    },
    {
        "title": "Stand-up Comedy Night",
        "venue": "Bostancı Gösteri Merkezi",
        "city": "İstanbul",
        "days_ahead": 5,
        "sections": [section("A", "Hall", 400, 15, 30)],
    },
]


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def main() -> None:
    token = organizer_token()
    status, mine = api("GET", "/api/events/mine", token=token)
    if status != 200:
        fail(f"GET /api/events/mine: {status} {mine}")
    existing = {event["title"]: event for event in mine}
    now = datetime.now(UTC)

    for spec in EVENTS:
        is_flash_sale = spec["title"] == FLASH_SALE_TITLE
        sales_open_at = now + FLASH_SALE_OPENS_IN if is_flash_sale else now - timedelta(hours=1)
        if spec["title"] in existing:
            event_id = existing[spec["title"]]["id"]
            if is_flash_sale:  # re-arm the countdown for the next demo / load test
                status, body = api(
                    "PATCH",
                    f"/api/events/{event_id}",
                    {"sales_open_at": iso(sales_open_at)},
                    token=token,
                )
                if status != 200:
                    fail(f"re-arming the flash sale: {status} {body}")
                ok(f"flash sale re-armed  id={event_id}  sales open {iso(sales_open_at)}")
            else:
                ok(f"exists               id={event_id}  {spec['title']}")
            continue

        body = {
            "title": spec["title"],
            "description": f"Demo event at {spec['venue']}.",
            "venue": spec["venue"],
            "city": spec["city"],
            "starts_at": iso(now + timedelta(days=spec["days_ahead"])),
            "sales_open_at": iso(sales_open_at),
            "sections": spec["sections"],
        }
        status, created = api("POST", "/api/events", body, token=token)
        if status != 201:
            fail(f"creating {spec['title']!r}: {status} {created}")
        label = "flash sale created  " if is_flash_sale else "created             "
        ok(f"{label} id={created['id']}  capacity={created['capacity']}  {spec['title']}")


if __name__ == "__main__":
    main()
