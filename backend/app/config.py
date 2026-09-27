from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BUDGET_", extra="ignore")

    database_url: str = "sqlite:///./data/budget.db"
    # Secret used to sign access tokens and to encrypt secrets stored in the DB.
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cookie_secure: bool = False  # True behind TLS in production
    cors_origins: list[str] = ["http://localhost:5173"]
    anthropic_api_key: str | None = None
    ai_model_default: str = "claude-opus-5"
    scheduler_enabled: bool = True
    backup_dir: Path = Path("./data/backups")
    max_upload_mb: int = 10
    reporting_currency: str = "EUR"


@lru_cache
def get_settings() -> Settings:
    return Settings()
