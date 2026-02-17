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

    # Logging (optional)
    LOG_DIR: str = "logs"
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
