"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-07 17:03:15.785488
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category")),
        sa.UniqueConstraint("name", name=op.f("uq_category_name")),
    )
    op.create_table(
        "setting",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=1000), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_setting")),
    )
    op.create_table(
        "channel",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_id", sa.String(length=40), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=2), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(content_id) = 40 AND content_id NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_channel_content_id_format"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_channel_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel")),
        sa.UniqueConstraint("content_id", name=op.f("uq_channel_content_id")),
    )
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_channel_category_id"), ["category_id"], unique=False)
        batch_op.create_index("ix_channel_country", ["country"], unique=False)
        batch_op.create_index("ix_channel_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_channel_language", ["language"], unique=False)
        batch_op.create_index("ix_channel_title", ["title"], unique=False)

    op.create_table(
        "check_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("peers", sa.Integer(), nullable=True),
        sa.Column("speed_down", sa.Integer(), nullable=True),
        sa.Column("infohash", sa.String(length=40), nullable=True),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('alive', 'no_peers', 'not_found', 'error')",
            name=op.f("ck_check_result_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["channel_id"],
            ["channel.id"],
            name=op.f("fk_check_result_channel_id_channel"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_result")),
    )
    with op.batch_alter_table("check_result", schema=None) as batch_op:
        batch_op.create_index(
            "ix_check_result_channel_id_checked_at", ["channel_id", "checked_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("check_result", schema=None) as batch_op:
        batch_op.drop_index("ix_check_result_channel_id_checked_at")

    op.drop_table("check_result")
    with op.batch_alter_table("channel", schema=None) as batch_op:
        batch_op.drop_index("ix_channel_title")
        batch_op.drop_index("ix_channel_language")
        batch_op.drop_index("ix_channel_created_at")
        batch_op.drop_index("ix_channel_country")
        batch_op.drop_index(batch_op.f("ix_channel_category_id"))

    op.drop_table("channel")
    op.drop_table("setting")
    op.drop_table("category")
