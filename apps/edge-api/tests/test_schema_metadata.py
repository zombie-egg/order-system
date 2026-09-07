from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Dialect
from sqlalchemy.schema import CreateTable

from app.persistence import models  # noqa: F401
from app.persistence.base import Base
from app.persistence.types import UtcDateTime

EXPECTED_TABLES = frozenset(
    {
        "audit_log",
        "category",
        "category_translation",
        "fulfillment_endpoint",
        "fulfillment_event",
        "fulfillment_ticket",
        "fulfillment_ticket_item",
        "idempotency_record",
        "kiosk_device",
        "kitchen_station",
        "legal_entity",
        "login_throttle",
        "manual_review_action",
        "manual_review_case",
        "option_group",
        "option_group_translation",
        "option_value",
        "option_value_translation",
        "order_discount_line",
        "order_item",
        "order_item_option",
        "order_status_event",
        "order_tax_line",
        "outbox_event",
        "payment_attempt",
        "payment_terminal",
        "payment_transaction",
        "permission",
        "price_book",
        "price_book_item",
        "price_book_option_item",
        "price_quote",
        "price_quote_discount_line",
        "price_quote_item",
        "price_quote_item_option",
        "price_quote_tax_line",
        "product",
        "product_option_rule",
        "product_translation",
        "promotion",
        "psp_webhook_event",
        "receipt",
        "reconciliation_issue",
        "reconciliation_run",
        "refund",
        "role",
        "role_permission",
        "sales_order",
        "store",
        "store_number_sequence",
        "store_operating_policy",
        "store_price_book_assignment",
        "store_product_availability",
        "tax_policy_version",
        "tax_rate",
        "tenant",
        "user_account",
        "user_store_role",
    }
)

POLYMORPHIC_UUID_COLUMNS = frozenset(
    {
        "audit_log.actor_device_id",
        "audit_log.target_id",
        "idempotency_record.resource_id",
        "outbox_event.aggregate_id",
        "reconciliation_issue.resource_id",
    }
)

SUPPORTED_DIALECTS: tuple[Dialect, ...] = (
    sqlite.dialect(),
    postgresql.dialect(),  # type: ignore[no-untyped-call]
)


def test_metadata_contains_the_complete_phase_3_schema() -> None:
    assert frozenset(Base.metadata.tables) == EXPECTED_TABLES


def test_constraint_and_index_names_are_clear_and_unique_per_table() -> None:
    named_constraint_types = (
        CheckConstraint,
        ForeignKeyConstraint,
        PrimaryKeyConstraint,
        UniqueConstraint,
    )

    for table in Base.metadata.tables.values():
        constraints = [
            constraint
            for constraint in table.constraints
            if isinstance(constraint, named_constraint_types)
        ]
        names = [str(constraint.name) for constraint in constraints]

        assert all(constraint.name is not None for constraint in constraints), table.name
        assert not [name for name, count in Counter(names).items() if count > 1], table.name
        assert not [name for name in names if name.endswith("_")], table.name
        assert not [name for name in names if len(name) > 63], table.name

        index_names = [str(index.name) for index in table.indexes]
        assert all(index.name is not None for index in table.indexes), table.name
        assert len(index_names) == len(set(index_names)), table.name
        assert not [name for name in index_names if len(name) > 63], table.name


def test_uuid_money_timestamp_and_enum_storage_contracts() -> None:
    enum_count = 0

    for table in Base.metadata.tables.values():
        for column in table.columns:
            qualified_name = f"{table.name}.{column.name}"
            if (
                column.name == "id"
                or column.foreign_keys
                or qualified_name in POLYMORPHIC_UUID_COLUMNS
            ):
                assert isinstance(column.type, Uuid), qualified_name

            if column.name.endswith("_minor"):
                assert isinstance(column.type, BigInteger), qualified_name

            if column.name.endswith("_at") or column.name in {"valid_from", "valid_to"}:
                assert isinstance(column.type, UtcDateTime), qualified_name

            if isinstance(column.type, SAEnum):
                enum_count += 1
                assert column.type.native_enum is False, qualified_name
                assert column.type.create_constraint is True, qualified_name
                assert column.type.name, qualified_name
                enum_class = column.type.enum_class
                assert enum_class is not None, qualified_name
                assert column.type.enums == [member.value for member in enum_class], qualified_name

    assert enum_count == 34


@pytest.mark.parametrize("dialect", SUPPORTED_DIALECTS)
def test_every_table_compiles_for_supported_dialects(dialect: Dialect) -> None:
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert f"CREATE TABLE {table.name}" in ddl


def test_utc_datetime_normalizes_values_and_rejects_naive_datetimes() -> None:
    column_type = UtcDateTime()
    dialect = sqlite.dialect()
    local_time = datetime(2026, 8, 12, 10, 30, tzinfo=timezone(timedelta(hours=2)))

    bound = column_type.process_bind_param(local_time, dialect)
    assert bound == datetime(2026, 8, 12, 8, 30, tzinfo=UTC)
    assert column_type.process_result_value(bound.replace(tzinfo=None), dialect) == bound

    with pytest.raises(ValueError, match="Naive datetimes"):
        column_type.process_bind_param(datetime(2026, 8, 12, 8, 30), dialect)


def test_uuid_primary_keys_use_python_uuid_values() -> None:
    for table in Base.metadata.tables.values():
        if "id" not in table.columns:
            continue
        id_column = table.c.id
        assert isinstance(id_column.type, Uuid), table.name
        assert id_column.type.as_uuid is True, table.name
        assert id_column.type.python_type is UUID, table.name
