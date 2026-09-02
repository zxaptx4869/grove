"""add knowledge agent basis plan snapshot

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-02 18:00:00.000000

保存规划器已经通过服务端校验的最小 basis 计划，使崩溃恢复只能重放原先
选中的用户消息句柄，而不会扩大到当前允许集合中的其他消息。旧行保持可空；
恢复旧行时采用空用户陈述子集，不猜测原规划结果。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加可空的 basis 计划快照。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("planned_basis_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """删除 basis 计划快照。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("planned_basis_json")
