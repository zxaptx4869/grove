"""add processing tasks and source status

Revision ID: cadf6172f4a8
Revises: d02b2fa14592
Create Date: 2026-08-13 21:37:49.709934
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cadf6172f4a8"
down_revision: str | None = "d02b2fa14592"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增处理任务表并为 Source 增加处理状态。"""
    op.add_column(
        "sources",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="waiting"),
    )
    op.create_table(
        "processing_tasks",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )


def downgrade() -> None:
    """回滚处理任务表与 Source 状态字段。"""
    op.drop_table("processing_tasks")
    op.drop_column("sources", "status")
