"""persist batch directory

Revision ID: b2c3d4e5
Revises: a9b1c2d3
Create Date: 2026-08-17 23:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5"
down_revision: str | None = "a9b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 Candidate 增加用户确认目录字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("user_node_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """回滚：移除用户确认目录字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_column("user_node_id")
