"""add new node suggestion fields

Revision ID: a9b1c2d3
Revises: c5d6e7f8
Create Date: 2026-08-17 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9b1c2d3"
down_revision: str | None = "c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 Candidate 增加新节点建议字段，均为可空建议值。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("new_node_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("new_node_parent_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("new_node_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：移除新节点建议字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("new_node_reason")
        batch_op.drop_column("new_node_parent_id")
        batch_op.drop_column("new_node_name")
