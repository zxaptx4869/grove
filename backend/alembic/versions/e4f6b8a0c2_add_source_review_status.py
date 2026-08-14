"""add source review status

Revision ID: e4f6b8a0c2
Revises: d8f5a2e4c6
Create Date: 2026-08-14 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f6b8a0c2"
down_revision: str | None = "d8f5a2e4c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 sources 增加 review_status。"""
    op.add_column(
        "sources",
        sa.Column(
            "review_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending_review",
        ),
    )


def downgrade() -> None:
    """回滚 sources.review_status。"""
    op.drop_column("sources", "review_status")
