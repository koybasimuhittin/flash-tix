"""make oversell: proof that no seat was sold twice and no event sold beyond its capacity.

Sold seats live in bookingdb, capacities in catalog's database, and one SQL query can't join
across databases. So this script counts sold seats with psql inside the postgres container and
reads each event's capacity through the catalog API. Run it after every load test.
Exit code 0 = clean, 1 = oversell found.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flashtix_client import ROOT, api, fail, ok  # noqa: E402

DUPLICATES_SQL = """
SELECT count(*) FROM (
  SELECT 1 FROM booking_seats GROUP BY event_id, seat_id HAVING count(*) > 1
) AS duplicates
"""
SOLD_SQL = "SELECT event_id, count(*) FROM booking_seats GROUP BY event_id ORDER BY event_id"


def psql(sql: str) -> list[list[str]]:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres",
         "psql", "-U", "postgres", "-d", "bookingdb", "-tA", "-F", ",", "-c", sql],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        fail(f"psql failed: {result.stderr.strip()}")
    return [line.split(",") for line in result.stdout.splitlines() if line]


def check(event_ids: set[int] | None = None) -> None:
    """Fails (exit 1) on any oversell. `event_ids` limits the capacity check to some events."""
    duplicates = int(psql(DUPLICATES_SQL)[0][0])
    if duplicates:
        fail(f"{duplicates} seat(s) sold more than once")
    ok("no seat sold twice")

    checked = unknown = 0
    for event_id, sold in ((int(e), int(s)) for e, s in psql(SOLD_SQL)):
        if event_ids is not None and event_id not in event_ids:
            continue
        status, event = api("GET", f"/api/events/{event_id}")
        if status == 404:
            unknown += 1  # bookings left by booking-service's tests (they mock the catalog)
            continue
        if status != 200:
            fail(f"GET /api/events/{event_id}: {status}")
        if sold > event["capacity"]:
            fail(f"event {event_id}: {sold} seats sold > capacity {event['capacity']}")
        checked += 1
    note = f" ({unknown} unknown to catalog, skipped)" if unknown else ""
    ok(f"sold <= capacity for {checked} event(s){note}")


if __name__ == "__main__":
    check()
