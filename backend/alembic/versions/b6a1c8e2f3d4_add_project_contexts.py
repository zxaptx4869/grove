"""add project contexts

Revision ID: b6a1c8e2f3d4
Revises: cadf6172f4a8
Create Date: 2026-08-13 22:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6a1c8e2f3d4"
down_revision: str | None = "cadf6172f4a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 project_contexts。"""
    op.create_table(
        "project_contexts",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("project_summary", sa.Text(), nullable=True),
        sa.Column("current_focus", sa.Text(), nullable=True),
        sa.Column("directory_topics", sa.Text(), nullable=True),
        sa.Column("user_corrections", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_contexts_project_id"),
        "project_contexts",
        ["project_id"],
        unique=True,
    )


def downgrade() -> None:
    """回滚 project_contexts。"""
    op.drop_index(op.f("ix_project_contexts_project_id"), table_name="project_contexts")
    op.drop_table("project_contexts")
