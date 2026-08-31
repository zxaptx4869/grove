"""extend entry_versions.change_type length

Revision ID: e7f8a9b0c1d2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-31 21:30:00.000000

知识 Agent 单 Entry 修订追加的版本类型 knowledge_agent_revision（24 字符）
超出 entry_versions.change_type 原有的 String(16)：MySQL 8 严格模式会拒绝
写入，非严格模式会截断。把该列扩到 String(32)，兼容既有值与新值。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """把 change_type 扩到 32 字符，容纳 knowledge_agent_revision。"""
    with op.batch_alter_table("entry_versions") as batch_op:
        batch_op.alter_column(
            "change_type",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    """回缩到 16 字符；存在超长值时由数据库按严格模式拒绝或提示。"""
    with op.batch_alter_table("entry_versions") as batch_op:
        batch_op.alter_column(
            "change_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
