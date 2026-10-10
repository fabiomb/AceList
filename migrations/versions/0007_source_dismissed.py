"""channels removed from a source by the user

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11 10:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_dismissed",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_source_dismissed_source_id_source"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_dismissed")),
        sa.UniqueConstraint("source_id", "content_id", name=op.f("uq_source_dismissed_source_id")),
    )


def downgrade() -> None:
    op.drop_table("source_dismissed")
