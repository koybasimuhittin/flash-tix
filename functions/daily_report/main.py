"""daily-report: one CSV of the day's sales per event.

Cloud Scheduler calls this HTTP function every night (03:00 Europe/Istanbul, OIDC-authenticated);
locally `make report` calls the container. It connects to bookingdb as the read-only
`report_reader` role (Direct VPC egress to the data VM in the cloud), aggregates one Istanbul
calendar day, writes reports/<date>.csv and returns a JSON summary.
"""

import csv
import io
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import functions_framework
import psycopg

REPORT_TZ = ZoneInfo("Europe/Istanbul")
COLUMNS = ["event_id", "event_title", "bookings", "seats", "revenue_cents"]
SQL = """
    SELECT event_id, event_title, COUNT(*) AS bookings, SUM(seat_count) AS seats,
           SUM(total_price_cents) AS revenue_cents
    FROM bookings
    WHERE created_at >= %(start)s AND created_at < %(end)s
    GROUP BY event_id, event_title
    ORDER BY revenue_cents DESC, event_id
"""


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": "daily-report",
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, default=str)


logger = logging.getLogger("daily_report")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logger.handlers[:] = [_handler]
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
logger.propagate = False


def report_day(raw: str | None, now: datetime | None = None) -> date:
    """`?date=YYYY-MM-DD`, or yesterday in Istanbul. Raises ValueError for anything else."""
    if raw:
        return date.fromisoformat(raw)
    now = now or datetime.now(UTC)
    return now.astimezone(REPORT_TZ).date() - timedelta(days=1)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[00:00, next 00:00) of that day in Istanbul, as UTC instants for the query."""
    start = datetime.combine(day, dtime.min, tzinfo=REPORT_TZ)
    end = datetime.combine(day + timedelta(days=1), dtime.min, tzinfo=REPORT_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def to_csv(rows: list[tuple]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode()


def fetch_rows(day: date) -> list[tuple]:
    start, end = day_bounds(day)
    with psycopg.connect(os.environ["REPORT_DATABASE_URL"], connect_timeout=5) as conn:
        return conn.execute(SQL, {"start": start, "end": end}).fetchall()


_gcs_client = None


def save(name: str, data: bytes) -> None:
    """STORAGE_BACKEND=local writes to the shared folder, gcs to the bucket."""
    if os.environ.get("STORAGE_BACKEND", "local") == "gcs":
        global _gcs_client
        if _gcs_client is None:
            from google.cloud import storage  # imported lazily: local mode needs no credentials

            _gcs_client = storage.Client()
        blob = _gcs_client.bucket(os.environ["GCS_BUCKET"]).blob(name)
        blob.upload_from_string(data, content_type="text/csv")
        return
    path = Path(os.environ.get("LOCAL_STORAGE_DIR", "/data/storage")) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.partial")
    partial.write_bytes(data)
    os.replace(partial, path)  # booking-service never serves a half-written CSV


@functions_framework.http
def generate_report(request):
    try:
        day = report_day(request.args.get("date"))
    except ValueError:
        return ({"error": "date must be YYYY-MM-DD"}, 400)

    started = time.perf_counter()
    rows = fetch_rows(day)  # a database error → 500, so Cloud Scheduler's retry policy applies
    name = f"reports/{day.isoformat()}.csv"
    save(name, to_csv(rows))
    summary = {
        "date": day.isoformat(),
        "object": name,
        "events": len(rows),
        "bookings": sum(row[2] for row in rows),
        "seats": sum(row[3] for row in rows),
        "revenue_cents": sum(row[4] for row in rows),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    logger.info("report written", extra={"fields": summary})
    return (summary, 200)
