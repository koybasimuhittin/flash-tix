from flashtix_common.config import BaseServiceSettings


class CatalogSettings(BaseServiceSettings):
    service_name: str = "catalog"

    # CATALOG_ prefix so the monolith (E7) can hold every service's DB settings at once.
    catalog_database_url: str = (
        "postgresql+asyncpg://catalog_user:catalog-local@127.0.0.1:5433/catalogdb"
    )
    catalog_db_pool_size: int = 5
    catalog_db_max_overflow: int = 5

    redis_url: str = "redis://127.0.0.1:6380/0"
    catalog_cache_enabled: bool = True  # off for cache-on/off load-test comparisons
    catalog_cache_ttl_seconds: int = 30
