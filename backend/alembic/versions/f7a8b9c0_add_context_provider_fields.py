"""add context provider fields

Revision ID: f7a8b9c0
Revises: e5f6a7b8
Create Date: 2026-08-18 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0"
down_revision: str | None = "e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为项目上下文快照增加生成来源与降级标记。"""
    with op.batch_alter_table("project_contexts") as batch_op:
        batch_op.add_column(sa.Column("provider", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_fallback",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    """回滚：移除生成来源字段。"""
    with op.batch_alter_table("project_contexts") as batch_op:
        batch_op.drop_column("is_fallback")
        batch_op.drop_column("model")
        batch_op.drop_column("provider")
