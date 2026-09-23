"""add source capture key

Revision ID: c8e1a4b7d9f2
Revises: fe5f6a7b8c9d
Create Date: 2026-09-23 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e1a4b7d9f2"
down_revision: str | None = "fe5f6a7b8c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """sources 增加采集幂等键与 Workspace 内唯一索引。"""
    op.add_column("sources", sa.Column("capture_key", sa.String(length=128), nullable=True))
    # 用唯一索引而非表级唯一约束：SQLite 不支持对既有表 ADD CONSTRAINT，唯一索引两方言等价
    op.create_index(
        "uq_sources_workspace_capture_key",
        "sources",
        ["workspace_id", "capture_key"],
        unique=True,
    )


def downgrade() -> None:
    """回滚 sources.capture_key 与唯一索引。"""
    op.drop_index("uq_sources_workspace_capture_key", table_name="sources")
    op.drop_column("sources", "capture_key")
