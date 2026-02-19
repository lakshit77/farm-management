"""Application settings loaded from environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. Loaded from .env and environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    API_V1_STR: str = "/api/v1"

    # PostgreSQL (use postgresql+asyncpg://user:pass@host:port/dbname in .env)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/showgroundlive"

    # Wellington / n8n integration (set in .env)
    WELLINGTON_API_BASE_URL: str = "https://sglapi.wellingtoninternational.com"
    WELLINGTON_CUSTOMER_ID: str = ""
    WELLINGTON_FARM_NAME: str = ""
    WELLINGTON_USERNAME: str = ""
    WELLINGTON_PASSWORD: str = ""

    # API key for n8n / external callers (Bearer token). If empty, key check is skipped.
    API_SECRET_KEY: str = ""

    # CORS: comma-separated origins (e.g. http://localhost:5175). When empty, uses default localhost dev origins.
    CORS_ORIGINS: str = ""

    # Logging (optional)
    LOG_DIR: str = "logs"
    LOG_LEVEL: str = "INFO"

    # Venue timezone for schedule times (Wellington FL = America/New_York).
    # API returns times in venue local; we convert to UTC for free-time calculation.
    VENUE_TIMEZONE: str = "America/New_York"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
