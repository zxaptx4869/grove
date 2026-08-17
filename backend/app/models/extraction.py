"""Extraction 与 Candidate 模型。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.source import Source

EXTRACTION_ACTIVE = "active"
EXTRACTION_SUPERSEDED = "superseded"
EXTRACTION_FAILED = "failed"

CANDIDATE_KIND_RECOMMENDED = "recommended"
CANDIDATE_KIND_OTHER = "other"
CANDIDATE_PENDING = "pending"
CANDIDATE_CONFIRMED = "confirmed"
CANDIDATE_REJECTED = "rejected"

ROUTING_PENDING = "pending"
ROUTING_RECOMMENDED = "recommended"
ROUTING_NEEDS_REVIEW = "needs_review"
ROUTING_NO_SUITABLE = "no_suitable"


class Extraction(Base):
    """一次版本化处理运行记录。"""

    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=EXTRACTION_ACTIVE, nullable=False)
    discarded_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discarded_reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source: Mapped["Source"] = relationship(back_populates="extractions")
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )


class Candidate(Base):
    """等待用户确认的候选知识单元。"""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    extraction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("extractions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    candidate_kind: Mapped[str] = mapped_column(
        String(16), default=CANDIDATE_KIND_RECOMMENDED, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    main_type: Mapped[str] = mapped_column(String(16), nullable=False)
    info_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applicable_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=CANDIDATE_PENDING, nullable=False)
    entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="SET NULL"), index=True, nullable=True
    )
    recommended_node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    node_alternatives: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_status: Mapped[str] = mapped_column(
        String(16), default=ROUTING_PENDING, nullable=False
    )
    new_node_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    new_node_parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    new_node_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    extraction: Mapped[Extraction] = relationship(back_populates="candidates")
    source: Mapped["Source"] = relationship()
