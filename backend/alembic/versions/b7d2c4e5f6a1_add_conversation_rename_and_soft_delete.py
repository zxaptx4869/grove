"""add conversation rename source and soft delete timestamp

Revision ID: b7d2c4e5f6a1
Revises: c8e1a4b7d9f2
Create Date: 2026-10-12 10:00:00.000000

知识对话补齐命名归属与软删：`title_source` 标记标题来自自动命名还是用户，
`deleted_at` 记录删除时间。软删不物理删除记录，也不依赖数据库级联。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d2c4e5f6a1"
down_revision: str | None = "c8e1a4b7d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """knowledge_conversations 增加标题来源与删除时间。"""
    with op.batch_alter_table("knowledge_conversations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "title_source",
                sa.String(length=16),
                nullable=False,
                server_default="auto",
            )
        )
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    """回滚标题来源与删除时间：软删期间隐藏的对话重新可见。"""
    with op.batch_alter_table("knowledge_conversations") as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("title_source")
