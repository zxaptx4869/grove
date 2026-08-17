"""drop routing suggestion indexes

Revision ID: c5d6e7f8
Revises: b3c4d5e6
Create Date: 2026-08-17 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8"
down_revision: str | None = "b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """推荐字段为写多读少的建议值，移除多余索引。"""
    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_index("ix_sources_recommended_project_id")
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_index("ix_candidates_recommended_node_id")


def downgrade() -> None:
    """回滚：恢复推荐字段索引。"""
    with op.batch_alter_table("sources") as batch_op:
        batch_op.create_index(
            "ix_sources_recommended_project_id",
            ["recommended_project_id"],
            unique=False,
        )
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.create_index(
            "ix_candidates_recommended_node_id",
            ["recommended_node_id"],
            unique=False,
        )
