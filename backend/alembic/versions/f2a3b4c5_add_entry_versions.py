"""add entry version snapshots

Revision ID: f2a3b4c5
Revises: e1a2b3c4
Create Date: 2026-08-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5"
down_revision: str | None = "e1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 Entry 版本快照表，并为既有 Entry 回填版本 1。"""
    op.create_table(
        "entry_versions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("main_type", sa.String(length=16), nullable=False),
        sa.Column("info_nature", sa.String(length=16), nullable=True),
        sa.Column("applicable_condition", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("change_type", sa.String(length=16), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_id", "version_number"),
    )
    op.create_index("ix_entry_versions_entry_id", "entry_versions", ["entry_id"])
    op.execute(
        sa.text(
            """
            INSERT INTO entry_versions (
                entry_id, version_number, title, content, main_type,
                info_nature, applicable_condition, note, node_id,
                change_type, change_summary, created_at
            )
            SELECT id, 1, title, content, main_type,
                info_nature, applicable_condition, note, node_id,
                'created', NULL, created_at
            FROM entries
            """
        )
    )


def downgrade() -> None:
    """回滚：删除 Entry 版本快照表。"""
    op.drop_index("ix_entry_versions_entry_id", table_name="entry_versions")
    op.drop_table("entry_versions")
