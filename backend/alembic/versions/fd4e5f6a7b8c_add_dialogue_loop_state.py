"""add bounded production dialogue loop state snapshot

Revision ID: fd4e5f6a7b8c
Revises: fc3d4e5f6a7b
Create Date: 2026-09-15 10:00:00.000000

为正式 Knowledge Agent Run 增加可空的 dialogue-loop 生产状态快照。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fd4e5f6a7b8c"
down_revision: str | None = "fc3d4e5f6a7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """追加可空 TEXT 快照字段，兼容 SQLite/MySQL 8。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("dialogue_loop_state_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """仅删除本迁移新增字段。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("dialogue_loop_state_json")
