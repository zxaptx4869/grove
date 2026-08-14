"""add extractions and candidates

Revision ID: d8f5a2e4c6
Revises: c9d4a1f2e3b5
Create Date: 2026-08-14 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f5a2e4c6"
down_revision: str | None = "c9d4a1f2e3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 extractions 与 candidates。"""
    op.create_table(
        "extractions",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("discarded_count", sa.Integer(), nullable=False),
        sa.Column("discarded_reason_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_extractions_source_id"), "extractions", ["source_id"], unique=False)

    op.create_table(
        "candidates",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("extraction_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("main_type", sa.String(length=16), nullable=False),
        sa.Column("info_nature", sa.String(length=16), nullable=True),
        sa.Column("applicable_condition", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence_refs", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("risk_flags", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["extraction_id"], ["extractions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidates_extraction_id"), "candidates", ["extraction_id"], unique=False)
    op.create_index(op.f("ix_candidates_source_id"), "candidates", ["source_id"], unique=False)


def downgrade() -> None:
    """回滚 candidates 与 extractions。"""
    op.drop_index(op.f("ix_candidates_source_id"), table_name="candidates")
    op.drop_index(op.f("ix_candidates_extraction_id"), table_name="candidates")
    op.drop_table("candidates")
    op.drop_index(op.f("ix_extractions_source_id"), table_name="extractions")
    op.drop_table("extractions")
