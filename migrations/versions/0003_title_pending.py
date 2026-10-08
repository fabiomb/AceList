"""provisional channel titles

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07 23:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel") as batch:
        batch.add_column(
            sa.Column("title_pending", sa.Boolean(), server_default=sa.false(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("channel") as batch:
        batch.drop_column("title_pending")
