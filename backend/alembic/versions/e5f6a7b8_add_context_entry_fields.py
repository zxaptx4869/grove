"""add context entry fields

Revision ID: e5f6a7b8
Revises: d1e2f3a4
Create Date: 2026-08-18 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8"
down_revision: str | None = "d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为项目上下文快照增加版本、更新原因与 Entry 相关字段。"""
    with op.batch_alter_table("project_contexts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("last_update_reason", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("entries_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("recent_themes", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：移除上下文新增字段。"""
    with op.batch_alter_table("project_contexts") as batch_op:
        batch_op.drop_column("recent_themes")
        batch_op.drop_column("entries_summary")
        batch_op.drop_column("last_update_reason")
        batch_op.drop_column("version")
