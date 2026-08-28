"""add behavior signals

Revision ID: 7c7cf705d962
Revises: f2a3b4c5
Create Date: 2026-08-24 19:28:50.504539
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c7cf705d962'
down_revision: Union[str, None] = 'f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建行为信号表（记录用户对 AI 推荐的决定）。"""
    op.create_table(
        "behavior_signals",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("candidate_id", sa.BigInteger(), sa.ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("recommended", sa.Text(), nullable=True),
        sa.Column("final", sa.Text(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_behavior_signals_workspace_id", "behavior_signals", ["workspace_id"])
    op.create_index("ix_behavior_signals_project_id", "behavior_signals", ["project_id"])
    op.create_index("ix_behavior_signals_source_id", "behavior_signals", ["source_id"])
    op.create_index("ix_behavior_signals_candidate_id", "behavior_signals", ["candidate_id"])
    op.create_index("ix_behavior_signals_signal_type", "behavior_signals", ["signal_type"])


def downgrade() -> None:
    """回滚：删除行为信号表。"""
    op.drop_table("behavior_signals")
