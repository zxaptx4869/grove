"""add embedding status index

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-08-26 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 Worker 的待处理轮询加速：按状态与创建时间排序。"""
    op.create_index(
        op.f("ix_entry_embeddings_status_created_at"),
        "entry_embeddings",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：移除状态索引。"""
    op.drop_index(
        op.f("ix_entry_embeddings_status_created_at"),
        table_name="entry_embeddings",
    )
