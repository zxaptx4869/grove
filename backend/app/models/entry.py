"""Entry 与来源证据模型。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.project import Node, Project
    from app.models.source import Source

VERSION_CREATED = "created"
VERSION_EDITED = "edited"
VERSION_AI_REVISION = "ai_revision"
VERSION_RESTORED = "restored"


class Entry(Base):
    """用户确认后的正式知识。"""

    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("nodes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    main_type: Mapped[str] = mapped_column(String(16), nullable=False)
    info_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applicable_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()
    node: Mapped["Node"] = relationship()
    evidences: Mapped[list["EntrySourceEvidence"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )
    versions: Mapped[list["EntryVersion"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class EntryVersion(Base):
    """Entry 的基础版本快照，只保留最近 N 条。"""

    __tablename__ = "entry_versions"
    __table_args__ = (UniqueConstraint("entry_id", "version_number"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    main_type: Mapped[str] = mapped_column(String(16), nullable=False)
    info_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applicable_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    entry: Mapped[Entry] = relationship(back_populates="versions")


class EntrySourceEvidence(Base):
    """Entry 到 Source/Attachment 的证据关系。"""

    __tablename__ = "entry_source_evidences"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    entry_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attachment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="SET NULL"), nullable=True
    )
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    entry: Mapped[Entry] = relationship(back_populates="evidences")
    source: Mapped["Source"] = relationship()
