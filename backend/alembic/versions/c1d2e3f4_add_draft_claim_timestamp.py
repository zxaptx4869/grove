"""add draft claim timestamp

Revision ID: c1d2e3f4
Revises: b0c1d2e3
Create Date: 2026-08-18 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4"
down_revision: str | None = "b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为草稿增加后台处理认领时间。"""
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """回滚：删除认领时间列。"""
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.drop_column("claimed_at")
