"""add knowledge agent answer basis fields

Revision ID: c7d8e9f0a1b2
Revises: d0e1f2a3b4c5
Create Date: 2026-09-02 10:00:00.000000

为普通 answer Run 增加开放讨论的依据契约字段：
- request_basis_mode 使用 String(16)，容纳公开请求模式 auto/knowledge_only；
- planned_basis_strategy 使用 String(16)，保存服务端规划后的内部策略；
- answer_basis_json 使用 Text，保存服务端校验后的 AnswerBasis v1 JSON；
- 三个字段均可空：旧记录不回填猜测依据，历史回答按原语义继续可读；
- batch_alter_table 保证 SQLite（批量重建）与 MySQL 8 同时兼容。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为 knowledge_agent_runs 增加依据契约字段。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.add_column(
            sa.Column("request_basis_mode", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("planned_basis_strategy", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("answer_basis_json", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """删除新增字段；历史 answer_json/消息内容与 basis 数据不依赖列存在。"""
    with op.batch_alter_table("knowledge_agent_runs") as batch_op:
        batch_op.drop_column("answer_basis_json")
        batch_op.drop_column("planned_basis_strategy")
        batch_op.drop_column("request_basis_mode")
