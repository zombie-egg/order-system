"""kds board display title (per-store kitchen display configuration)

Adds the optional ``display_title`` column on ``kitchen_station`` so each store
can present its own kitchen-display board title. Together with the existing
``name`` (board/station name) and ``active`` (board enabled) fields this lets an
administrator configure every store's board while a store manager is limited to
their own store.

Revision ID: 9d2a3b4c5e6f
Revises: 9c1a2b3d4e5f
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2a3b4c5e6f"
down_revision: str | None = "9c1a2b3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("kitchen_station") as batch:
        batch.add_column(sa.Column("display_title", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("kitchen_station") as batch:
        batch.drop_column("display_title")
