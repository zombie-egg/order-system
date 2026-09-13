"""Store-scoped product options and takeaway fees.

Revision ID: a4e7f9012b3c
Revises: 9d2a3b4c5e6f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4e7f9012b3c"
down_revision: str | None = "9d2a3b4c5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("option_group", sa.Column("store_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE option_group AS og
        SET store_id = (
            SELECT s.id FROM store AS s
            JOIN legal_entity AS le ON le.id = s.legal_entity_id
            WHERE le.tenant_id = og.tenant_id
            ORDER BY s.created_at, s.id
            LIMIT 1
        )
        """
    )
    with op.batch_alter_table("option_group") as batch:
        batch.alter_column("store_id", nullable=False)
        batch.create_index("ix_option_group_store_id", ["store_id"])
        batch.drop_constraint("uq_option_group_tenant_id_code", type_="unique")
        batch.create_unique_constraint("uq_option_group_store_id_code", ["store_id", "code"])
        batch.create_foreign_key("fk_option_group_store_id", "store", ["store_id"], ["id"])

    op.add_column(
        "product_option_rule",
        sa.Column("default_option_value_id", sa.Uuid(), nullable=True),
    )
    with op.batch_alter_table("product_option_rule") as batch:
        batch.create_foreign_key(
            "fk_product_option_rule_default_value",
            "option_value",
            ["default_option_value_id"],
            ["id"],
        )

    op.add_column(
        "store_operating_policy",
        sa.Column("takeaway_fee_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "store_operating_policy",
        sa.Column("takeaway_fee_minor", sa.BigInteger(), server_default="0", nullable=False),
    )
    with op.batch_alter_table("store_operating_policy") as batch:
        batch.create_check_constraint(
            "takeaway_fee_minor_nonnegative",
            "takeaway_fee_minor >= 0",
        )

    for table, enum_name in (
        ("price_quote", "quote_fulfillment_type"),
        ("sales_order", "order_fulfillment_type"),
    ):
        op.add_column(
            table,
            sa.Column(
                "fulfillment_type",
                sa.Enum(
                    "DINE_IN",
                    "TAKEAWAY",
                    name=enum_name,
                    native_enum=False,
                    create_constraint=True,
                ),
                server_default="DINE_IN",
                nullable=False,
            ),
        )
        op.add_column(
            table,
            sa.Column("packaging_fee_minor", sa.BigInteger(), server_default="0", nullable=False),
        )
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(
                "packaging_fee_minor_nonnegative",
                "packaging_fee_minor >= 0",
            )


def downgrade() -> None:
    for table, _enum_name in (
        ("sales_order", "order_fulfillment_type"),
        ("price_quote", "quote_fulfillment_type"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint("packaging_fee_minor_nonnegative", type_="check")
            batch.drop_column("packaging_fee_minor")
            batch.drop_column("fulfillment_type")
    with op.batch_alter_table("store_operating_policy") as batch:
        batch.drop_constraint(
            "takeaway_fee_minor_nonnegative", type_="check"
        )
        batch.drop_column("takeaway_fee_minor")
        batch.drop_column("takeaway_fee_enabled")
    with op.batch_alter_table("product_option_rule") as batch:
        batch.drop_constraint("fk_product_option_rule_default_value", type_="foreignkey")
        batch.drop_column("default_option_value_id")
    with op.batch_alter_table("option_group") as batch:
        batch.drop_constraint("fk_option_group_store_id", type_="foreignkey")
        batch.drop_constraint("uq_option_group_store_id_code", type_="unique")
        batch.create_unique_constraint("uq_option_group_tenant_id_code", ["tenant_id", "code"])
        batch.drop_index("ix_option_group_store_id")
        batch.drop_column("store_id")
