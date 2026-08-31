"""add knowledge agent result mode and entry result fields

Revision ID: d0e1f2a3b4c5
Revises: e7f8a9b0c1d2
Create Date: 2026-08-31 22:30:00.000000

为普通 answer Run 增加请求/实际结果形态与有界结构化 Entry 结果 JSON：
- request_result_mode / actual_result_mode 使用 String(8)，容纳 auto/answer/entries；
- entry_result_json 使用 Text：30 条 × 240 字摘要的序列化结果可安全落在
  MySQL TEXT（65535 字节）与 SQLite Text 内，应用层在序列化前强制字节上限；
- 三个字段均可空：旧行保持兼容，客户端按 auto / answer / 无结构化结果读取；
- 不修改 answer_json，不回填历史数据。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 knowledge_agent_runs 增加结果形态与 Entry 结果字段。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("request_result_mode", sa.String(length=8), nullable=True)
        )
        batch_op.add_column(
            sa.Column("actual_result_mode", sa.String(length=8), nullable=True)
        )
        batch_op.add_column(sa.Column("entry_result_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """删除新增字段；历史 answer_json 与消息内容不受影响。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("entry_result_json")
        batch_op.drop_column("actual_result_mode")
        batch_op.drop_column("request_result_mode")
