"""add attachment ocr text

Revision ID: f6a7c8d9
Revises: e4f6b8a0c2
Create Date: 2026-08-14 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7c8d9"
down_revision: str | None = "e4f6b8a0c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 attachments 增加 ocr_text。"""
    op.add_column("attachments", sa.Column("ocr_text", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚 attachments.ocr_text。"""
    op.drop_column("attachments", "ocr_text")
