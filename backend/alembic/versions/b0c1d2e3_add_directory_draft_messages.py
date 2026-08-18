"""add directory draft messages

Revision ID: b0c1d2e3
Revises: a8b9c0d1
Create Date: 2026-08-18 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0c1d2e3"
down_revision: str | None = "a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加草稿会话轮数并创建对话消息表。"""
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "conversation_rounds",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "directory_draft_messages",
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
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_directory_draft_messages_draft_id",
        "directory_draft_messages",
        ["draft_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚：删除消息表与会话轮数列。"""
    op.drop_index("ix_directory_draft_messages_draft_id", table_name="directory_draft_messages")
    op.drop_table("directory_draft_messages")
    with op.batch_alter_table("directory_drafts") as batch_op:
        batch_op.drop_column("conversation_rounds")
