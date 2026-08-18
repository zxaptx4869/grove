"""add entry relation suggestion fields

Revision ID: d1e2f3a4
Revises: b2c3d4e5
Create Date: 2026-08-18 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4"
down_revision: str | None = "b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 Candidate 增加与已有 Entry 的关系建议字段，均为可空建议值。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(
            sa.Column(
                "relation_status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("relation_target_entry_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("relation_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("revision_draft", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：移除关系建议字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("revision_draft")
        batch_op.drop_column("relation_reason")
        batch_op.drop_column("relation_target_entry_id")
        batch_op.drop_column("relation_status")
