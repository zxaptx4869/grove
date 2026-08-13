"""add sources and attachments

Revision ID: d02b2fa14592
Revises: 8b7c4d1e9f20
Create Date: 2026-08-13 18:51:01.774760
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d02b2fa14592"
down_revision: str | None = "8b7c4d1e9f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 sources 与 attachments。"""
    op.create_table(
        "sources",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sources_workspace_id"), "sources", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sources_project_id"), "sources", ["project_id"], unique=False)

    op.create_table(
        "attachments",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_path", sa.String(length=255), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attachments_source_id"), "attachments", ["source_id"], unique=False)


def downgrade() -> None:
    """回滚 sources 与 attachments。"""
    op.drop_index(op.f("ix_attachments_source_id"), table_name="attachments")
    op.drop_table("attachments")
    op.drop_index(op.f("ix_sources_project_id"), table_name="sources")
    op.drop_index(op.f("ix_sources_workspace_id"), table_name="sources")
    op.drop_table("sources")
