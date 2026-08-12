"""初始空迁移：建立 Alembic 迁移管道。

Revision ID: 0001
Revises:
Create Date: 2026-08-12

本迁移不创建任何业务表，仅验证 Alembic 管道在 SQLite 与 MySQL 8 上均可执行。

方言差异说明（后续业务迁移必须遵守）：
- SQLite：主键自增用 INTEGER PRIMARY KEY AUTOINCREMENT；不支持修改列类型；
  外键约束默认不启用（需 PRAGMA foreign_keys=ON）。
- MySQL 8：主键自增用 BIGINT AUTO_INCREMENT；字符串需显式长度（VARCHAR）；
  默认 utf8mb4 字符集，连接串需带 charset=utf8mb4。
- 通用做法：优先使用 sa.BigInteger / sa.Text 等跨库类型，
  对需要长度的字段用 sa.String(length=N)（两库均支持）。
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空升级：仅确保迁移管道可用。"""
    pass


def downgrade() -> None:
    """空回滚。"""
    pass
