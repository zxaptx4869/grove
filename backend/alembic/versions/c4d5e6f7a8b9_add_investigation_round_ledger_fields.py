"""add investigation round ledger json fields

Revision ID: c4d5e6f7a8b9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-28 20:40:00.000000

为已完成轮次持久化账本对象线索：entries_json 保存本轮新发现 Entry 的
（id/标题/项目/目录）短快照，unavailable_json 保存本轮不可用/越权对象，
供崩溃恢复时确定性重建当前 Run 的已发现集合与预算，不复制整份原文。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为轮次表增加账本对象线索字段。"""
    with op.batch_alter_table("knowledge_investigation_rounds") as batch_op:
        batch_op.add_column(sa.Column("entries_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("unavailable_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """回滚：删除账本对象线索字段。"""
    with op.batch_alter_table("knowledge_investigation_rounds") as batch_op:
        batch_op.drop_column("unavailable_json")
        batch_op.drop_column("entries_json")
