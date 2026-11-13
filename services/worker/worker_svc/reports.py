"""Daily sales report: bookings, seats and revenue per event for one Europe/Istanbul day."""

import csv
import io
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REPORT_TZ = ZoneInfo("Europe/Istanbul")
COLUMNS = ["event_id", "event_title", "bookings", "seats", "revenue_cents"]
SQL = text(
    """
    SELECT event_id, event_title, COUNT(*) AS bookings, SUM(seat_count) AS seats,
           SUM(total_price_cents) AS revenue_cents
    FROM bookings
    WHERE created_at >= :start AND created_at < :end
    GROUP BY event_id, event_title
    ORDER BY revenue_cents DESC, event_id
    """
)


def report_day(raw: str | None, now: datetime | None = None) -> date:
    """`YYYY-MM-DD`, or yesterday in Istanbul. Raises ValueError for anything else."""
    if raw:
        return date.fromisoformat(raw)
    now = now or datetime.now(UTC)
    return now.astimezone(REPORT_TZ).date() - timedelta(days=1)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """[00:00, next 00:00) of that day in Istanbul, as UTC instants for the query."""
    start = datetime.combine(day, dtime.min, tzinfo=REPORT_TZ)
    end = datetime.combine(day + timedelta(days=1), dtime.min, tzinfo=REPORT_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def report_name(day: date) -> str:
    return f"reports/{day.isoformat()}.csv"


def to_csv(rows: list[tuple]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode()


async def fetch_rows(engine: AsyncEngine, day: date) -> list[tuple]:
    start, end = day_bounds(day)
    async with engine.connect() as conn:
        result = await conn.execute(SQL, {"start": start, "end": end})
        return [tuple(row) for row in result.all()]
