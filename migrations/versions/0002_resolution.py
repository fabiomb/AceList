"""channel resolution and screenshot size

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07 22:40:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_RESOLUTIONS = "'480p', '720p', '1080p', '4k', 'other'"


def upgrade() -> None:
    # Batch mode: SQLite cannot add a CHECK constraint to an existing table.
    with op.batch_alter_table("channel") as batch:
        batch.add_column(sa.Column("resolution", sa.String(length=8), nullable=True))
        batch.create_check_constraint(
            op.f("ck_channel_resolution_valid"), f"resolution IN ({_RESOLUTIONS})"
        )
        batch.create_index("ix_channel_resolution", ["resolution"])
    with op.batch_alter_table("check_result") as batch:
        batch.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("height", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("check_result") as batch:
        batch.drop_column("height")
        batch.drop_column("width")
    with op.batch_alter_table("channel") as batch:
        batch.drop_index("ix_channel_resolution")
        batch.drop_constraint(op.f("ck_channel_resolution_valid"), type_="check")
        batch.drop_column("resolution")
