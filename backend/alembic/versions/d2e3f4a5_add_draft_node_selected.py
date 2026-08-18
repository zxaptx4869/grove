"""add draft node selected

Revision ID: d2e3f4a5
Revises: c1d2e3f4
Create Date: 2026-08-18 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5"
down_revision: str | None = "c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """草稿节点增加是否采用的勾选标记，默认采用。"""
    with op.batch_alter_table("directory_draft_nodes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "selected",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    """回滚：删除采用标记列。"""
    with op.batch_alter_table("directory_draft_nodes") as batch_op:
        batch_op.drop_column("selected")
