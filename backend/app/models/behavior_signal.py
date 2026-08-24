"""行为信号模型：记录用户对 AI 推荐的决定，供后续个性化与真实数据验证。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.source import Source
    from app.models.user import User
    from app.models.workspace import Workspace

# 信号类型：用户对 AI 推荐的决定
SIGNAL_PROJECT_DECISION = "project_decision"
SIGNAL_NODE_DECISION = "node_decision"
SIGNAL_CONTENT_EDIT = "content_edit"
SIGNAL_RELATION_DECISION = "relation_decision"


class BehaviorSignal(Base):
    """用户对 AI 推荐决定的一次记录（长期遥测，业务对象删除后保留）。"""

    __tablename__ = "behavior_signals"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="SET NULL"), index=True, nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("candidates.id", ondelete="SET NULL"), index=True, nullable=True
    )
    signal_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    recommended: Mapped[str | None] = mapped_column(Text, nullable=True)
    final: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User | None"] = relationship()
    project: Mapped["Project | None"] = relationship()
    source: Mapped["Source | None"] = relationship()
