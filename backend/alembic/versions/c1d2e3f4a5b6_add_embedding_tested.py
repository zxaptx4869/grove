"""add embedding tested flag

Revision ID: c1d2e3f4a5b6
Revises: b7e8c9d0e1f2
Create Date: 2026-08-26 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b7e8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """记录 embedding 是否执行过连接测试。"""
    op.add_column(
        "ai_provider_settings",
        sa.Column("embedding_tested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """回滚：移除测试标记字段。"""
    op.drop_column("ai_provider_settings", "embedding_tested")
