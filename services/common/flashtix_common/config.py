from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Settings every service shares. Each service subclasses this with its own fields.

    Values come from environment variables (case-insensitive), e.g. SLOW_REQUEST_MS=500.
    """

    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "service"
    log_level: str = "INFO"
    slow_request_ms: int = 500

    jwt_public_key_path: str = "/secrets/jwt_public.pem"
    jwt_issuer: str = "flashtix-auth"
    jwt_audience: str = "flashtix"
