"""add routing suggestion fields

Revision ID: b3c4d5e6
Revises: a7b6c5d4
Create Date: 2026-08-17 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6"
down_revision: str | None = "a7b6c5d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 Source 与 Candidate 增加项目/目录推荐字段。"""
    with op.batch_alter_table("sources") as batch_op:
        batch_op.add_column(sa.Column("recommended_project_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("project_recommendation_reason", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_sources_recommended_project_id",
            ["recommended_project_id"],
            unique=False,
        )

    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("recommended_node_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("node_alternatives", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("node_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "routing_status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.create_index(
            "ix_candidates_recommended_node_id",
            ["recommended_node_id"],
            unique=False,
        )


def downgrade() -> None:
    """回滚：移除项目/目录推荐字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_index("ix_candidates_recommended_node_id")
        batch_op.drop_column("routing_status")
        batch_op.drop_column("node_reason")
        batch_op.drop_column("node_alternatives")
        batch_op.drop_column("recommended_node_id")

    with op.batch_alter_table("sources") as batch_op:
        batch_op.drop_index("ix_sources_recommended_project_id")
        batch_op.drop_column("project_recommendation_reason")
        batch_op.drop_column("recommended_project_id")
