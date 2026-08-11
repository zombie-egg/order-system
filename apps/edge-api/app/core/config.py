from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Smart Drink Edge API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    default_country: str = "NL"
    default_currency: str = "EUR"
    default_locale: str = "nl-NL"
    business_timezone: str = "Europe/Amsterdam"

    database_url: str = "sqlite+aiosqlite:///./var/dev.db"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
        ]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
