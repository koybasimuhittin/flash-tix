from flashtix_common.config import BaseServiceSettings


class AuthSettings(BaseServiceSettings):
    service_name: str = "auth"

    jwt_private_key_path: str = "/secrets/jwt_private.pem"
    access_token_ttl_seconds: int = 3600
    bcrypt_rounds: int = 12

    # AUTH_ prefix so the monolith (E7) can hold every service's DB settings at once.
    auth_database_url: str = "postgresql+asyncpg://auth_user:auth-local@127.0.0.1:5433/authdb"
    auth_db_pool_size: int = 5
    auth_db_max_overflow: int = 5

    bootstrap_organizer_email: str | None = None
    bootstrap_organizer_password: str | None = None
    bootstrap_organizer_name: str = "Organizer"
