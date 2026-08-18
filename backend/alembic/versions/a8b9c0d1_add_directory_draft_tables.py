"""add directory draft tables

Revision ID: a8b9c0d1
Revises: f7a8b9c0
Create Date: 2026-08-18 17:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1"
down_revision: str | None = "f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建目录草稿与草稿节点表。"""
    op.create_table(
        "directory_drafts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next_action", sa.String(length=16), nullable=False),
        sa.Column("clarify_batches", sa.Integer(), nullable=False),
        sa.Column("clarify_json", sa.Text(), nullable=True),
        sa.Column("clarify_answers_json", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("is_fallback", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
    )
    op.create_index(
        "ix_directory_drafts_project_id",
        "directory_drafts",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "directory_draft_nodes",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            primary_key=True,
        ),
        sa.Column(
            "draft_id",
            sa.BigInteger(),
            sa.ForeignKey("directory_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            sa.ForeignKey("directory_draft_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
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
    )
    op.create_index(
        "ix_directory_draft_nodes_draft_id",
        "directory_draft_nodes",
        ["draft_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删除草稿节点与草稿表。"""
    op.drop_index("ix_directory_draft_nodes_draft_id", table_name="directory_draft_nodes")
    op.drop_table("directory_draft_nodes")
    op.drop_index("ix_directory_drafts_project_id", table_name="directory_drafts")
    op.drop_table("directory_drafts")
