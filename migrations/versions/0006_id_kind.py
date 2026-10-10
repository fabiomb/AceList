"""remember whether a channel's identifier is a Content ID or an infohash

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 18:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode: SQLite cannot add a CHECK constraint to an existing table.
    with op.batch_alter_table("channel") as batch:
        batch.add_column(sa.Column("id_kind", sa.String(length=10), nullable=True))
        batch.create_check_constraint(
            op.f("ck_channel_id_kind_valid"), "id_kind IN ('content_id', 'infohash')"
        )


def downgrade() -> None:
    with op.batch_alter_table("channel") as batch:
        batch.drop_constraint(op.f("ck_channel_id_kind_valid"), type_="check")
        batch.drop_column("id_kind")
