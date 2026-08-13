"""补充项目说明与生命周期字段。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b7c4d1e9f20"
down_revision: str | None = "f3d3ba1ec30a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为既有项目填充产品基础字段。"""
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("projects")}
    if "description" not in columns:
        op.add_column("projects", sa.Column("description", sa.Text(), nullable=True))
    if "status" not in columns:
        op.add_column(
            "projects",
            sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        )


def downgrade() -> None:
    """回滚新增字段。"""
    op.drop_column("projects", "status")
    op.drop_column("projects", "description")
