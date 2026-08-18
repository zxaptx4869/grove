"""Directory Draft 候选模型：确认前不触碰正式 Node。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.project import Project

DRAFT_DRAFTING = "drafting"
DRAFT_AWAITING_INPUT = "awaiting_input"
DRAFT_PENDING_CONFIRM = "pending_confirm"
DRAFT_CONFIRMED = "confirmed"
DRAFT_DISCARDED = "discarded"
DRAFT_FAILED = "failed"

DRAFT_ACTIVE = {
    DRAFT_DRAFTING,
    DRAFT_AWAITING_INPUT,
    DRAFT_FAILED,
    DRAFT_PENDING_CONFIRM,
}

DRAFT_CLARIFY = "clarify"
DRAFT_GENERATE = "generate"


class DirectoryDraft(Base):
    """每项目至多一份活跃目录草稿。"""

    __tablename__ = "directory_drafts"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), default=DRAFT_DRAFTING, nullable=False
    )
    next_action: Mapped[str] = mapped_column(
        String(16), default=DRAFT_CLARIFY, nullable=False
    )
    clarify_batches: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clarify_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarify_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_fallback: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversation_rounds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()
    nodes: Mapped[list["DirectoryDraftNode"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )
    messages: Mapped[list["DirectoryDraftMessage"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class DirectoryDraftNode(Base):
    """草稿内的候选目录节点。"""

    __tablename__ = "directory_draft_nodes"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("directory_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("directory_draft_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selected: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    draft: Mapped[DirectoryDraft] = relationship(back_populates="nodes")


class DirectoryDraftMessage(Base):
    """草稿会话消息。"""

    __tablename__ = "directory_draft_messages"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("directory_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    draft: Mapped[DirectoryDraft] = relationship(back_populates="messages")
