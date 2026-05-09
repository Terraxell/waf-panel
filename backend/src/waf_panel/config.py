"""Runtime configuration for the gateway."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "waf"
    postgres_password: str = "waf_dev_only"
    postgres_db: str = "waf_panel"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ClickHouse
    ch_host: str = "clickhouse"
    ch_http_port: int = 8123
    ch_user: str = "waf"
    ch_password: str = "waf_dev_only"
    ch_db: str = "waf_logs"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: str = Field("dev-secret-do-not-use", min_length=8)
    jwt_ttl_minutes: int = 60
    jwt_algorithm: str = "HS256"

    # Cookie auth (ADR-0014). Browser SPA uses cookies; CLI/CI keep
    # using the Authorization: Bearer header. The session JWT is
    # httpOnly (XSS-safe), the CSRF token is JS-readable so the SPA
    # can echo it in X-CSRF-Token. Double-submit equality is the check.
    cookie_session_name: str = "waf_session"
    cookie_csrf_name: str = "waf_csrf"

    # ml-service
    ml_service_url: str = "http://ml-service:8001"
    ml_service_timeout_ms: int = 20

    # Misc
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"

    # Deploy environment guard. Production refuses to start with
    # default JWT secret. Dev / test stays untouched.
    waf_env: str = "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor."""
    return Settings()
