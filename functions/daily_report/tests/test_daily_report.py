"""daily-report through functions-framework's real app. The integration test writes bookings
as booking_user into the local compose Postgres and reads them back as report_reader."""

import asyncio
import os
import random
import socket
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import functions_framework
import psycopg
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "main.py"
DB = ("127.0.0.1", 5433)
BOOKING_URL = (
    f"postgresql://booking_user:{os.environ.get('BOOKING_DB_PASSWORD', 'booking-local')}"
    f"@{DB[0]}:{DB[1]}/bookingdb"
)
REPORT_URL = (
    f"postgresql://report_reader:{os.environ.get('REPORT_DB_PASSWORD', 'report-local')}"
    f"@{DB[0]}:{DB[1]}/bookingdb"
)


@pytest.fixture
def storage(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("REPORT_DATABASE_URL", REPORT_URL)
    return tmp_path


@pytest.fixture
def client(storage):
    app = functions_framework.create_app(target="generate_report", source=str(SOURCE))
    return app.test_client()


# --- pure logic ----------------------------------------------------------------------------


def test_default_day_is_yesterday_in_istanbul():
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("daily_report_main", SOURCE)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    # 22:30 UTC on the 13th is already 01:30 on the 14th in Istanbul → yesterday is the 13th.
    assert module.report_day(None, datetime(2026, 11, 13, 22, 30, tzinfo=UTC)) == date(2026, 11, 13)
    assert module.report_day("2026-11-01") == date(2026, 11, 1)
    with pytest.raises(ValueError):
        module.report_day("01-11-2026")

    start, end = module.day_bounds(date(2026, 11, 13))
    assert start == datetime(2026, 11, 12, 21, 0, tzinfo=UTC)  # Istanbul is UTC+3
    assert end == datetime(2026, 11, 13, 21, 0, tzinfo=UTC)
    assert module.to_csv([]) == b"event_id,event_title,bookings,seats,revenue_cents\r\n"


def test_bad_date_is_400_before_touching_the_database(client):
    response = client.get("/?date=13-11-2026")
    assert response.status_code == 400


# --- against the compose Postgres --------------------------------------------------------


@pytest.fixture(scope="module")
def bookings_schema() -> None:
    """Create booking-service's tables if they don't exist yet, exactly as the service does
    (same models, same advisory lock), so these tests never depend on test ordering.
    Skips without Postgres, unless REQUIRE_DB=1 (CI), where a missing database is a failure."""
    try:
        with socket.create_connection(DB, timeout=1):
            pass
    except OSError:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail(f"REQUIRE_DB=1 but postgres on {DB[0]}:{DB[1]} is unreachable")
        pytest.skip(f"local postgres on {DB[0]}:{DB[1]} is not running")

    from booking_svc.main import SCHEMA_LOCK_KEY
    from booking_svc.models import Base
    from flashtix_common.db import init_schema, make_engine

    async def create() -> None:
        engine = make_engine(BOOKING_URL.replace("postgresql://", "postgresql+asyncpg://"))
        try:
            await init_schema(engine, Base.metadata, lock_key=SCHEMA_LOCK_KEY)
        finally:
            await engine.dispose()

    asyncio.run(create())


@pytest.mark.usefixtures("bookings_schema")
def test_report_counts_exactly_one_istanbul_day(client, storage):
    day = date(2025, 3, 12)  # far from any real data
    rock, jazz = random.randint(10**9, 2 * 10**9), random.randint(10**9, 2 * 10**9)
    rows = [
        # (event, title, created_at UTC, seats, cents)
        (rock, "Rock Night", datetime(2025, 3, 11, 20, 59, 59, tzinfo=UTC), 1, 100),  # 11th 23:59
        (rock, "Rock Night", datetime(2025, 3, 11, 21, 0, 0, tzinfo=UTC), 2, 3000),  # 12th 00:00
        (rock, "Rock Night", datetime(2025, 3, 12, 12, 0, 0, tzinfo=UTC), 1, 1500),
        (jazz, "Jazz Night", datetime(2025, 3, 12, 20, 59, 59, tzinfo=UTC), 4, 2000),  # 23:59:59
        (jazz, "Jazz Night", datetime(2025, 3, 12, 21, 0, 0, tzinfo=UTC), 1, 500),  # 13th 00:00
    ]
    ids = [uuid.uuid4() for _ in rows]
    with psycopg.connect(BOOKING_URL) as conn:
        for booking_id, (event, title, created, seats, cents) in zip(ids, rows, strict=True):
            conn.execute(
                """INSERT INTO bookings (id, user_id, user_email, user_name, event_id, event_title,
                       event_starts_at, venue, city, status, seat_count, total_price_cents,
                       created_at)
                   VALUES (%s, 1, 'r@example.com', 'R', %s, %s, now(), 'Hall', 'Istanbul',
                           'confirmed', %s, %s, %s)""",
                (booking_id, event, title, seats, cents, created),
            )
    try:
        response = client.get(f"/?date={day.isoformat()}")
    finally:
        with psycopg.connect(BOOKING_URL) as conn:
            conn.execute("DELETE FROM bookings WHERE id = ANY(%s)", (ids,))

    assert response.status_code == 200
    summary = response.get_json()
    assert (summary["events"], summary["bookings"], summary["seats"]) == (2, 3, 7)
    assert summary["revenue_cents"] == 6500
    csv_text = (storage / "reports" / "2025-03-12.csv").read_text()
    assert csv_text.splitlines() == [
        "event_id,event_title,bookings,seats,revenue_cents",
        f"{rock},Rock Night,2,3,4500",
        f"{jazz},Jazz Night,1,4,2000",
    ]


@pytest.mark.usefixtures("bookings_schema")
def test_report_reader_cannot_write():
    with psycopg.connect(REPORT_URL) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM bookings WHERE false")
