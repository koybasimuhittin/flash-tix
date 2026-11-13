from flashtix_common.config import BaseServiceSettings


class WorkerSettings(BaseServiceSettings):
    service_name: str = "worker"

    # Read-only reporting role on bookingdb: the worker can never change bookings.
    report_database_url: str = (
        "postgresql+asyncpg://report_reader:report-local@127.0.0.1:5433/bookingdb"
    )
    report_db_pool_size: int = 2
    report_db_max_overflow: int = 2

    local_storage_dir: str = "/data/storage"  # shared with booking-service, which serves files
