"""add embedding retrieval

Revision ID: b7e8c9d0e1f2
Revises: 7c7cf705d962
Create Date: 2026-08-26 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e8c9d0e1f2"
down_revision: str | None = "7c7cf705d962"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """扩展模型配置并创建 Entry 向量表。"""
    op.add_column(
        "ai_provider_settings",
        sa.Column("embedding_provider", sa.String(length=32), nullable=False, server_default="doubao"),
    )
    op.add_column(
        "ai_provider_settings",
        sa.Column(
            "embedding_model",
            sa.String(length=128),
            nullable=False,
            server_default="doubao-embedding-vision-251215",
        ),
    )
    op.add_column(
        "ai_provider_settings",
        sa.Column("embedding_key_tail", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "ai_provider_settings",
        sa.Column("embedding_available", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "entry_embeddings",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "model"),
    )
    op.create_index(
        op.f("ix_entry_embeddings_workspace_id"),
        "entry_embeddings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entry_embeddings_project_id"),
        "entry_embeddings",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entry_embeddings_entry_id"),
        "entry_embeddings",
        ["entry_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删除向量表并移除配置字段。"""
    op.drop_index(op.f("ix_entry_embeddings_entry_id"), table_name="entry_embeddings")
    op.drop_index(op.f("ix_entry_embeddings_project_id"), table_name="entry_embeddings")
    op.drop_index(op.f("ix_entry_embeddings_workspace_id"), table_name="entry_embeddings")
    op.drop_table("entry_embeddings")
    op.drop_column("ai_provider_settings", "embedding_available")
    op.drop_column("ai_provider_settings", "embedding_key_tail")
    op.drop_column("ai_provider_settings", "embedding_model")
    op.drop_column("ai_provider_settings", "embedding_provider")
