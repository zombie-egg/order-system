"""tenant branding (merchant logo and display name)

Adds the two optional columns the kiosk header needs to show the merchant's own
branding: a display name (falls back to the tenant name) and a logo URL. Both
are configured by an administrator from the admin console.

Revision ID: 9c1a2b3d4e5f
Revises: 8d419483ec02
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9c1a2b3d4e5f"
down_revision: str | None = "8d419483ec02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tenant") as batch:
        batch.add_column(sa.Column("brand_name", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("logo_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenant") as batch:
        batch.drop_column("logo_url")
        batch.drop_column("brand_name")
