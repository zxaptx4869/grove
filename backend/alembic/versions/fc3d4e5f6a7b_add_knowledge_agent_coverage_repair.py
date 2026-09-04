"""add knowledge agent bounded coverage repair snapshots

Revision ID: fc3d4e5f6a7b
Revises: fb2c3d4e5f6a
Create Date: 2026-09-04 14:00:00.000000

为 Knowledge Agent Run 增加可空的覆盖补查基线、计划与执行快照，不回填旧 Run。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fc3d4e5f6a7b"
down_revision: str | None = "fb2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """追加五个可空 TEXT 快照字段，兼容 SQLite/MySQL 8。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(sa.Column("coverage_repair_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("coverage_repair_plan_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("coverage_repair_execution_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("coverage_repair_graph_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("coverage_repair_graph_state_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """仅删除本迁移新增字段。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("coverage_repair_graph_state_json")
        batch_op.drop_column("coverage_repair_graph_json")
        batch_op.drop_column("coverage_repair_execution_json")
        batch_op.drop_column("coverage_repair_plan_json")
        batch_op.drop_column("coverage_repair_json")
