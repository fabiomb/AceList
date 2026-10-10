"""checks of source entries run from Explorar

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11 12:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_STATUSES = "'alive', 'no_peers', 'not_found', 'error'"


def upgrade() -> None:
    # Batch mode: SQLite cannot add a CHECK constraint to an existing table.
    with op.batch_alter_table("source_entry") as batch:
        batch.add_column(sa.Column("check_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("check_peers", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("checked_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            op.f("ck_source_entry_check_status_valid"), f"check_status IN ({_STATUSES})"
        )


def downgrade() -> None:
    with op.batch_alter_table("source_entry") as batch:
        batch.drop_constraint(op.f("ck_source_entry_check_status_valid"), type_="check")
        batch.drop_column("checked_at")
        batch.drop_column("check_peers")
        batch.drop_column("check_status")
