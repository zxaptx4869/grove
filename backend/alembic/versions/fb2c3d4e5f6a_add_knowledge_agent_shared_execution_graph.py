"""add knowledge agent shared execution graph snapshots

Revision ID: fb2c3d4e5f6a
Revises: fa1b2c3d4e5f
Create Date: 2026-09-04 10:00:00.000000

为 Knowledge Agent Run 增加可空的共享执行图与 state 快照列，不回填旧 Run。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fb2c3d4e5f6a"
down_revision: str | None = "fa1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """追加两个可空 TEXT 快照字段，兼容 SQLite/MySQL 8。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("shared_execution_graph_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("shared_execution_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """仅删除本迁移新增字段，不修改历史 Run 内容。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("shared_execution_state_json")
        batch_op.drop_column("shared_execution_graph_json")
