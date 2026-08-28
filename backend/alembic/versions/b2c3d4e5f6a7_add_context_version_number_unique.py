"""add unique constraint on context version number

Revision ID: b2c3d4e5f6a7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-28 19:00:00.000000

为 knowledge_context_versions 增加 (conversation_id, version_number) 唯一约束，
在数据库层保证不可变版本链的版本号不重复（应用层由单活动 Run 串行保护，
这里作为防御性约束）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增版本号唯一约束（SQLite 用批量重建，MySQL 直接加约束）。"""
    with op.batch_alter_table("knowledge_context_versions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_knowledge_context_version_number",
            ["conversation_id", "version_number"],
        )


def downgrade() -> None:
    """回滚：删除版本号唯一约束。"""
    with op.batch_alter_table("knowledge_context_versions") as batch_op:
        batch_op.drop_constraint(
            "uq_knowledge_context_version_number",
            type_="unique",
        )
