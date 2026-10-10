"""sources uploaded from a file have no URL

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 12:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source") as batch:
        batch.alter_column("url", existing_type=sa.String(length=1000), nullable=True)


def downgrade() -> None:
    # File sources cannot be kept without a URL; their entries go with them.
    op.execute(
        "DELETE FROM source_entry WHERE source_id IN (SELECT id FROM source WHERE url IS NULL)"
    )
    op.execute("DELETE FROM source WHERE url IS NULL")
    with op.batch_alter_table("source") as batch:
        batch.alter_column("url", existing_type=sa.String(length=1000), nullable=False)
