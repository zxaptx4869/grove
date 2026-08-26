"""模型 BYOK 配置模型：只保存脱敏信息，密钥在安全存储中。"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class AIProviderSettings(Base):
    """当前 Workspace 的文本、视觉与 embedding 模型配置。"""

    __tablename__ = "ai_provider_settings"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    text_provider: Mapped[str] = mapped_column(String(32), default="deepseek", nullable=False)
    text_model: Mapped[str] = mapped_column(String(128), default="deepseek-chat", nullable=False)
    text_key_tail: Mapped[str | None] = mapped_column(String(8), nullable=True)
    text_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vision_provider: Mapped[str] = mapped_column(String(32), default="doubao", nullable=False)
    vision_model: Mapped[str] = mapped_column(
        String(128), default="doubao-seed-2-0-lite-260428", nullable=False
    )
    vision_key_tail: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vision_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), default="doubao", nullable=False)
    embedding_model: Mapped[str] = mapped_column(
        String(128), default="doubao-embedding-vision-251215", nullable=False
    )
    embedding_key_tail: Mapped[str | None] = mapped_column(String(8), nullable=True)
    embedding_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship()
