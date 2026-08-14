"""add ai provider settings

Revision ID: c9d4a1f2e3b5
Revises: b6a1c8e2f3d4
Create Date: 2026-08-14 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4a1f2e3b5"
down_revision: str | None = "b6a1c8e2f3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 ai_provider_settings。"""
    op.create_table(
        "ai_provider_settings",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("text_provider", sa.String(length=32), nullable=False),
        sa.Column("text_model", sa.String(length=128), nullable=False),
        sa.Column("text_key_tail", sa.String(length=8), nullable=True),
        sa.Column("text_available", sa.Boolean(), nullable=False),
        sa.Column("vision_provider", sa.String(length=32), nullable=False),
        sa.Column("vision_model", sa.String(length=128), nullable=False),
        sa.Column("vision_key_tail", sa.String(length=8), nullable=True),
        sa.Column("vision_available", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    op.create_index(
        op.f("ix_ai_provider_settings_workspace_id"),
        "ai_provider_settings",
        ["workspace_id"],
        unique=True,
    )


def downgrade() -> None:
    """回滚 ai_provider_settings。"""
    op.drop_index(
        op.f("ix_ai_provider_settings_workspace_id"), table_name="ai_provider_settings"
    )
    op.drop_table("ai_provider_settings")
