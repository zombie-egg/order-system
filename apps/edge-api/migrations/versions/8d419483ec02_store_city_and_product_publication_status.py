"""store city and product publication status

Adds the two columns the simplified administration workflow needs: a store
city, used to search stores and to derive a readable store code, and a product
publication status so a draft can be prepared without reaching the customer
terminal. Existing products are backfilled as published.

Revision ID: 8d419483ec02
Revises: 7207959333e0
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d419483ec02"
down_revision: str | None = "7207959333e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The value check is declared once, explicitly, rather than through
# create_constraint: under this project's naming convention SQLAlchemy emits the
# enum's CHECK under two different names, which then makes a SQLite table
# rebuild reference a column the downgrade has already dropped.
PRODUCT_STATUS = sa.Enum(
    "DRAFT",
    "PUBLISHED",
    name="product_status",
    native_enum=False,
    create_constraint=False,
)
# Bare name: the project's naming convention expands it to
# ck_product_product_status.
PRODUCT_STATUS_CHECK = "product_status"


def upgrade() -> None:
    with op.batch_alter_table("product", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                PRODUCT_STATUS,
                server_default="PUBLISHED",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            PRODUCT_STATUS_CHECK,
            "status IN ('DRAFT', 'PUBLISHED')",
        )
        batch_op.create_index(batch_op.f("ix_product_status"), ["status"], unique=False)

    with op.batch_alter_table("store", schema=None) as batch_op:
        batch_op.add_column(sa.Column("city", sa.String(length=120), nullable=True))
        batch_op.create_index(batch_op.f("ix_store_city"), ["city"], unique=False)


def downgrade() -> None:
    # SQLite rebuilds the table to drop a column, so the index has to go first
    # in its own statement; dropping both inside one batch block makes the
    # rebuild reference an index that no longer exists.
    op.drop_index(op.f("ix_store_city"), table_name="store")
    with op.batch_alter_table("store", schema=None) as batch_op:
        batch_op.drop_column("city")

    op.drop_index(op.f("ix_product_status"), table_name="product")
    # The value check has to go before the column: SQLite rebuilds the table
    # from its reflected definition, so a surviving CHECK would reference a
    # column that no longer exists.
    with op.batch_alter_table("product", schema=None) as batch_op:
        batch_op.drop_constraint(PRODUCT_STATUS_CHECK, type_="check")
        batch_op.drop_column("status")
