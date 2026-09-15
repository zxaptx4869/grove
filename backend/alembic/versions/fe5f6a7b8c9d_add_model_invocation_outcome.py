"""add model invocation outcome classification

Revision ID: fe5f6a7b8c9d
Revises: fd4e5f6a7b8c
Create Date: 2026-09-15 13:30:00.000000

为模型调用审计增加结果分类，区分真实成功、未派发、确定性降级、离线模型和调用失败。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fe5f6a7b8c9d"
down_revision: str | None = "fd4e5f6a7b8c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加结果分类，并为历史记录提供兼容分类。"""
    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "outcome",
                sa.String(length=32),
                nullable=False,
                server_default="model_success",
            )
        )
    op.execute(
        """
        UPDATE knowledge_agent_model_invocations
        SET outcome = 'offline_test_model'
        WHERE provider = 'offline' OR model = 'offline'
        """
    )
    op.execute(
        """
        UPDATE knowledge_agent_model_invocations
        SET outcome = 'model_call_failed'
        WHERE is_fallback = 1
          AND error IS NOT NULL
          AND outcome = 'model_success'
        """
    )
    op.execute(
        """
        UPDATE knowledge_agent_model_invocations
        SET outcome = 'deterministic_fallback'
        WHERE is_fallback = 1
          AND outcome = 'model_success'
        """
    )


def downgrade() -> None:
    """删除结果分类字段。"""
    with op.batch_alter_table("knowledge_agent_model_invocations") as batch_op:
        batch_op.drop_column("outcome")
