"""add directory draft kind and target node

Revision ID: e1a2b3c4
Revises: d2e3f4a5
Create Date: 2026-08-19 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4"
down_revision: str | None = "d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """目录草稿增加 kind 与 target_node_id，支持节点拓展。"""
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=16),
                nullable=False,
                server_default="draft",
            )
        )
        batch_op.add_column(
            sa.Column(
                "target_node_id",
                sa.BigInteger(),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_directory_drafts_target_node_id_nodes",
            "nodes",
            ["target_node_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_directory_drafts_target_node_id",
            ["target_node_id"],
            unique=False,
        )


def downgrade() -> None:
    """回滚：删除 target_node_id 与 kind 列。"""
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.drop_index("ix_directory_drafts_target_node_id")
        batch_op.drop_constraint(
            "fk_directory_drafts_target_node_id_nodes",
            type_="foreignkey",
        )
        batch_op.drop_column("target_node_id")
        batch_op.drop_column("kind")
