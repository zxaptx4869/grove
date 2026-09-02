"""add knowledge agent structured query plan snapshot

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-09-02 21:00:00.000000

为 Knowledge Agent Run 增加可空的规范化结构化查询计划快照。迁移不回填、
不猜测旧 Run；SQLite 与 MySQL 8 都使用普通 Text 可空列。降级只移除新增列，
不改动旧结果快照、回答或正式知识。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加可空的规范化结构化查询计划快照。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("structured_query_plan_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """只删除本迁移新增的计划快照列。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("structured_query_plan_json")
