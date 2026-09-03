"""add knowledge agent composite answer snapshots

Revision ID: fa1b2c3d4e5f
Revises: e9f0a1b2c3d4
Create Date: 2026-09-03 18:00:00.000000

为 Knowledge Agent Run 增加可空的复合回答计划、执行检查点与逐项覆盖快照。
迁移不回填、不猜测旧 Run；SQLite 与 MySQL 8 都使用普通 Text 可空列。
降级只移除本 revision 新增列，不改动既有回答、结构化结果或正式知识。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fa1b2c3d4e5f"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加三个可空复合回答 JSON 快照列。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("composite_answer_plan_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("composite_answer_execution_json", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("composite_answer_coverage_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """只删除本迁移新增的复合回答快照列。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("composite_answer_coverage_json")
        batch_op.drop_column("composite_answer_execution_json")
        batch_op.drop_column("composite_answer_plan_json")
