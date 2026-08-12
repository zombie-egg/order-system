from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import get_settings
from app.persistence import models  # noqa: F401
from app.persistence.base import Base

EDGE_API_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = EDGE_API_ROOT / "alembic.ini"
MIGRATION = EDGE_API_ROOT / "migrations" / "versions" / "7207959333e0_phase_3_backend_schema.py"
REVISION = "7207959333e0"


def _database_url(database: Path) -> str:
    return f"sqlite+aiosqlite:///{database.resolve().as_posix()}"


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def _table_names(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        return {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def _revision(database: Path) -> str | None:
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    return None if row is None else str(row[0])


def test_initial_migration_is_application_independent() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "app." not in source
    assert "UtcDateTime" not in source
    assert source.count("op.create_table(") == len(Base.metadata.tables)
    assert source.count("op.drop_table(") == len(Base.metadata.tables)


def test_empty_database_upgrade_downgrade_upgrade_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "schema-roundtrip.db"
    monkeypatch.setenv("DATABASE_URL", _database_url(database))
    get_settings.cache_clear()
    config = _alembic_config()

    try:
        command.upgrade(config, "head")
        expected_tables = set(Base.metadata.tables) | {"alembic_version"}
        assert _table_names(database) == expected_tables
        assert _revision(database) == REVISION
        command.check(config)

        command.downgrade(config, "base")
        assert _table_names(database) <= {"alembic_version", "sqlite_sequence"}

        command.upgrade(config, "head")
        assert _table_names(database) == expected_tables
        assert _revision(database) == REVISION
    finally:
        get_settings.cache_clear()


def test_key_database_constraints_reject_corrupt_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "schema-constraints.db"
    monkeypatch.setenv("DATABASE_URL", _database_url(database))
    get_settings.cache_clear()
    config = _alembic_config()
    command.upgrade(config, "head")

    now = "2026-08-12 08:00:00+00:00"
    first_id = "1" * 32
    second_id = "2" * 32
    third_id = "3" * 32
    fourth_id = "4" * 32

    try:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "INSERT INTO tenant (code, name, active, id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("TENANT", "Tenant", 1, first_id, now, now),
            )

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO tenant (code, name, active, id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("TENANT", "Duplicate", 1, second_id, now, now),
                )

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO price_book "
                    "(tenant_id, code, version, currency, prices_include_tax, status, id, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (first_id, "PB", 1, "EUR", 1, "NOT_A_STATUS", second_id, now, now),
                )

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO price_book_item (price_book_id, product_id, price_minor) "
                    "VALUES (?, ?, ?)",
                    (first_id, second_id, -1),
                )

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO promotion "
                    "(store_id, code, name, promotion_type, value, minimum_total_minor, "
                    "starts_at, ends_at, active, id, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        first_id,
                        "TOO_HIGH",
                        "Too high",
                        "PERCENTAGE",
                        1_000_001,
                        0,
                        now,
                        None,
                        1,
                        third_id,
                        now,
                        now,
                    ),
                )

            connection.execute(
                "INSERT INTO price_quote_item "
                "(quote_id, line_number, product_id, sku_snapshot, name_snapshot, quantity, "
                "prices_include_tax, unit_price_minor, option_total_minor, discount_minor, "
                "tax_category_code, tax_rate_ppm, net_minor, tax_minor, line_total_minor, "
                "preparation_snapshot, allergen_snapshot, id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    first_id,
                    1,
                    second_id,
                    "DRINK",
                    "Drink",
                    1,
                    1,
                    500,
                    -100,
                    0,
                    "STANDARD",
                    150_000,
                    347,
                    53,
                    400,
                    "{}",
                    "{}",
                    fourth_id,
                ),
            )
            connection.commit()
    finally:
        get_settings.cache_clear()
