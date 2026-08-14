"""add entries and entry source evidences

Revision ID: a1b2c3d4
Revises: f6a7c8d9
Create Date: 2026-08-14 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4"
down_revision: str | None = "f6a7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 entries 与 entry_source_evidences，并为 candidates 增加 entry_id。"""
    op.create_table(
        "entries",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("main_type", sa.String(length=16), nullable=False),
        sa.Column("info_nature", sa.String(length=16), nullable=True),
        sa.Column("applicable_condition", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_entries_project_id"), "entries", ["project_id"], unique=False)
    op.create_index(op.f("ix_entries_node_id"), "entries", ["node_id"], unique=False)

    op.create_table(
        "entry_source_evidences",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("attachment_id", sa.BigInteger(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["entry_id"], ["entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attachment_id"], ["attachments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_entry_source_evidences_entry_id"),
        "entry_source_evidences",
        ["entry_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_entry_source_evidences_source_id"),
        "entry_source_evidences",
        ["source_id"],
        unique=False,
    )

    with op.batch_alter_table("candidates") as batch_op:
        batch_op.add_column(sa.Column("entry_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            "fk_candidates_entry_id",
            "entries",
            ["entry_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_candidates_entry_id", ["entry_id"], unique=False)


def downgrade() -> None:
    """回滚 Entry 相关表与字段。"""
    with op.batch_alter_table("candidates") as batch_op:
        batch_op.drop_index("ix_candidates_entry_id")
        batch_op.drop_constraint("fk_candidates_entry_id", type_="foreignkey")
        batch_op.drop_column("entry_id")
    op.drop_index(op.f("ix_entry_source_evidences_source_id"), table_name="entry_source_evidences")
    op.drop_index(op.f("ix_entry_source_evidences_entry_id"), table_name="entry_source_evidences")
    op.drop_table("entry_source_evidences")
    op.drop_index(op.f("ix_entries_node_id"), table_name="entries")
    op.drop_index(op.f("ix_entries_project_id"), table_name="entries")
    op.drop_table("entries")
