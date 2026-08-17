"""drop sources.review_status cached column

Revision ID: a7b6c5d4
Revises: a1b2c3d4
Create Date: 2026-08-17 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b6c5d4"
down_revision: str | None = "a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """确认台改为实时派生审阅状态，删除 sources.review_status 缓存列。"""
    op.drop_column("sources", "review_status")


def downgrade() -> None:
    """回滚：恢复 sources.review_status。"""
    op.add_column(
        "sources",
        sa.Column(
            "review_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending_review",
        ),
    )
