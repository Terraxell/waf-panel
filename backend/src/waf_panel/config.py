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

    # ── Postgres ────────────────────────────────────────────────────
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

    # ── ClickHouse ──────────────────────────────────────────────────
    ch_host: str = "clickhouse"
    ch_http_port: int = 8123
    ch_user: str = "waf"
    ch_password: str = "waf_dev_only"
    ch_db: str = "waf_logs"

    # ── Redis ───────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Auth ────────────────────────────────────────────────────────
    jwt_secret: str = Field("dev-secret-do-not-use", min_length=8)
    jwt_ttl_minutes: int = 60
    jwt_algorithm: str = "HS256"

    # ── ml-service (Sprint 8) ───────────────────────────────────────
    ml_service_url: str = "http://ml-service:8001"
    ml_service_timeout_ms: int = 20

    # ── Misc ────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"

    # ── Deploy environment (Sprint 11 hotfix) ───────────────────────
    # WHY: in production we refuse to start with a default JWT secret.
    #      Set WAF_ENV=production before deploying — explicit operator
    #      acknowledgment that secrets are configured.
    waf_env: str = "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton accessor."""
    return Settings()
