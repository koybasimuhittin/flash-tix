from typing import Literal

from flashtix_common.config import BaseServiceSettings


class BookingSettings(BaseServiceSettings):
    service_name: str = "booking"

    # BOOKING_ prefix so the monolith (E7) can hold every service's DB settings at once.
    booking_database_url: str = (
        "postgresql+asyncpg://booking_user:booking-local@127.0.0.1:5433/bookingdb"
    )
    booking_db_pool_size: int = 5
    booking_db_max_overflow: int = 5

    redis_url: str = "redis://127.0.0.1:6380/0"

    catalog_url: str = "http://catalog-service:8000"
    catalog_event_cache_ttl_seconds: float = 60  # a stale sales_open_at for up to this is fine

    hold_ttl_seconds: int = 600
    max_seats_per_booking: int = 6
    purchase_grace_seconds: int = 30  # holds can't lapse between verify and commit
    mock_payment_latency_ms: int = 0  # simulates an external payment provider

    # `http` pushes to the local ticket-pdf container.
    event_backend: Literal["http", "pubsub", "log"] = "log"
    ticket_function_url: str = "http://ticket-pdf:8080/"  # EVENT_BACKEND=http only
    storage_backend: Literal["local", "gcs"] = "local"
    local_storage_dir: str = "/data/storage"
