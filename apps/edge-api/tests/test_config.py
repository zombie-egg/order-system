from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///./var/dev.db",
        "SQLITE+AIOSQLITE:///./var/dev.db",
        "postgresql+asyncpg://smartdrink:secret@127.0.0.1:5432/smartdrink",
        "mysql+aiomysql://smartdrink:secret@127.0.0.1:3306/smartdrink",
    ],
)
def test_settings_reject_unsupported_database_drivers(database_url: str) -> None:
    with pytest.raises(ValidationError, match=r"sqlite\+aiosqlite or postgresql\+psycopg"):
        Settings(database_url=database_url)


def test_api_port_must_be_a_valid_tcp_port() -> None:
    with pytest.raises(ValidationError):
        Settings(api_port=0)


def test_log_level_is_validated_before_application_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(log_level="TRACE")  # type: ignore[arg-type]


def test_jwt_secret_is_validated_in_every_environment() -> None:
    with pytest.raises(ValidationError, match="at least 32 UTF-8 bytes"):
        Settings(app_env="test", jwt_secret="too-short")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("login_max_failures", 2),
        ("login_failure_window_seconds", 59),
        ("login_lockout_seconds", 29),
        ("login_password_verify_concurrency", 0),
    ],
)
def test_login_throttle_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Settings).validate_python({field: value})


def test_production_settings_fail_closed() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production")

    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(
            app_env="production",
            jwt_secret="a-production-secret-with-at-least-32-characters",
            mock_payment_enabled=False,
            database_url="sqlite+aiosqlite:///./var/production.db",
        )

    settings = Settings(
        app_env="production",
        jwt_secret="a-production-secret-with-at-least-32-characters",
        mock_payment_enabled=False,
        database_url="postgresql+psycopg://smartdrink:secret@127.0.0.1:5432/smartdrink",
    )
    assert settings.app_env == "production"


def test_staging_uses_the_same_database_and_mock_payment_boundary_as_production() -> None:
    with pytest.raises(ValidationError, match="MOCK_PAYMENT_ENABLED"):
        Settings(
            app_env="staging",
            jwt_secret="a-staging-secret-with-at-least-32-characters",
            database_url="postgresql+psycopg://smartdrink:secret@127.0.0.1:5432/smartdrink",
        )

    settings = Settings(
        app_env="staging",
        jwt_secret="a-staging-secret-with-at-least-32-characters",
        mock_payment_enabled=False,
        database_url=(
            "postgresql+psycopg://smartdrink:secret@127.0.0.1:5432/smartdrink?connect_timeout=10"
        ),
    )
    assert settings.app_env == "staging"
