from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import MockPaymentScenario

SUPPORTED_DATABASE_URL_PREFIXES = (
    "sqlite+aiosqlite://",
    "postgresql+psycopg://",
)
SETTINGS_ENV_FILE = os.environ.get("SMART_DRINK_ENV_FILE", ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SETTINGS_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "SipPilot Edge API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    jwt_secret: str = "development-only-change-before-production"
    jwt_issuer: str = "smart-drink-edge"
    jwt_audience: str = "smart-drink-operations"
    access_token_minutes: int = Field(default=30, ge=5, le=240)
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_failure_window_seconds: int = Field(default=900, ge=60, le=86_400)
    login_lockout_seconds: int = Field(default=900, ge=30, le=86_400)
    login_password_verify_concurrency: int = Field(default=4, ge=1, le=16)
    quote_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    kds_online_window_seconds: int = Field(default=30, ge=5, le=300)
    mock_payment_enabled: bool = True
    mock_payment_scenario: MockPaymentScenario = MockPaymentScenario.APPROVED

    default_country: str = "NL"
    default_currency: str = "EUR"
    default_locale: str = "nl-NL"
    business_timezone: str = "Europe/Amsterdam"

    database_url: str = "sqlite+aiosqlite:///./var/dev.db"
    # Local edge deployments keep product imagery beside the database. In a cloud
    # deployment this path should point to persistent mounted storage (or be
    # replaced by an object-storage adapter).
    media_storage_dir: str = "./var/media"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:5175",
        ]
    )

    @model_validator(mode="after")
    def validate_runtime_boundaries(self) -> Settings:
        if not self.database_url.startswith(SUPPORTED_DATABASE_URL_PREFIXES):
            raise ValueError("DATABASE_URL must use sqlite+aiosqlite or postgresql+psycopg")
        if len(self.jwt_secret.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 UTF-8 bytes")

        if self.app_env in {"staging", "production"}:
            environment_name = self.app_env.capitalize()
            if self.jwt_secret == "development-only-change-before-production":
                raise ValueError(f"JWT_SECRET must be changed in {self.app_env}")
            if self.mock_payment_enabled:
                raise ValueError(f"MOCK_PAYMENT_ENABLED must be false in {self.app_env}")
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError(f"{environment_name} DATABASE_URL must use PostgreSQL via psycopg")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
