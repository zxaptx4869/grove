"""知识 Agent 底座模型：对话、消息、Run、工具调用、模型调用与 Run Evidence。

设计约束：
- 所有对象从第一行起归属 Workspace 与创建用户，任何读取都按当前用户 + Workspace 过滤；
- 用户消息与待执行 Run 在同一事务写入，`(conversation_id, client_message_id)` 幂等键
  保证网络重试不会重复执行；
- 同一对话最多一个活动 Run（`active_slot='active'`），终态置空以兼容
  SQLite/MySQL 的唯一约束语义；
- 可观测记录只保存脱敏摘要，不保存原始 prompt 或整份 Attachment。
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.entry import Entry
    from app.models.project import Project
    from app.models.source import Attachment, Source
    from app.models.user import User
    from app.models.workspace import Workspace

# ---- 范围类型 ----
SCOPE_WORKSPACE = "workspace"
SCOPE_PROJECT = "project"
KNOWLEDGE_SCOPE_TYPES = (SCOPE_WORKSPACE, SCOPE_PROJECT)

# ---- 消息 ----
MESSAGE_ROLE_USER = "user"
MESSAGE_ROLE_ASSISTANT = "assistant"
MESSAGE_ROLE_SYSTEM = "system"

MESSAGE_TYPE_USER = "user"
MESSAGE_TYPE_ASSISTANT = "assistant"
MESSAGE_TYPE_SCOPE_CHANGE = "scope_change"

# ---- Run 状态 ----
RUN_WAITING = "waiting"
RUN_PROCESSING = "processing"
RUN_COMPLETED = "completed"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

RUN_ACTIVE_STATUSES = {RUN_WAITING, RUN_PROCESSING}
RUN_TERMINAL_STATUSES = {RUN_COMPLETED, RUN_PARTIAL, RUN_FAILED, RUN_CANCELLED}

# 单活动 Run 的唯一槽位值；终态置空释放槽位
ACTIVE_SLOT = "active"

# ---- 上下文模式与决策 ----
CONTEXT_MODE_AUTO = "auto"
CONTEXT_MODE_CONTINUE = "continue"
CONTEXT_MODE_NEW_TOPIC = "new_topic"
CONTEXT_MODES = (CONTEXT_MODE_AUTO, CONTEXT_MODE_CONTINUE, CONTEXT_MODE_NEW_TOPIC)

CONTEXT_DECISION_CONTINUE = "continue"
CONTEXT_DECISION_NEW_TOPIC = "new_topic"
CONTEXT_DECISION_CLARIFY = "clarify"
CONTEXT_DECISIONS = (
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_DECISION_NEW_TOPIC,
    CONTEXT_DECISION_CLARIFY,
)

# ---- 上下文版本状态与关闭原因 ----
CONTEXT_STATUS_ACTIVE = "active"
CONTEXT_STATUS_SUPERSEDED = "superseded"
CONTEXT_STATUS_CLOSED = "closed"

CONTEXT_CLOSE_REASON_REPLACED = "replaced"
CONTEXT_CLOSE_REASON_NEW_TOPIC = "new_topic"
CONTEXT_CLOSE_REASON_SCOPE_CHANGE = "scope_change"

# ---- 工作集纳入原因 ----
WORKING_SET_REASON_CITED = "cited"
WORKING_SET_REASON_RECENT = "recent"

# ---- Run 步骤（固定执行图） ----
STEP_CLAIM = "claim"
STEP_CONTEXT_DECISION = "context_decision"
STEP_SEARCH = "search"
STEP_READ_ENTRIES = "read_entries"
STEP_READ_EVIDENCE = "read_evidence"
STEP_ORGANIZE_ANSWER = "organize_answer"
STEP_VALIDATE_REFERENCES = "validate_references"
STEP_FINALIZE = "finalize"

# ---- 模型调用用途 ----
PURPOSE_CONTEXT_DECISION = "context_decision"
PURPOSE_EMBEDDING = "embedding"
PURPOSE_RERANK = "rerank"
PURPOSE_ANSWER = "answer"

# ---- 工具调用状态 ----
TOOL_OK = "ok"
TOOL_EMPTY = "empty"
TOOL_PARTIAL = "partial"
TOOL_DENIED = "denied"
TOOL_UNAVAILABLE = "unavailable"
TOOL_ERROR = "error"

# ---- Evidence 用途 ----
EVIDENCE_PURPOSE_ANSWER = "answer"
EVIDENCE_PURPOSE_CONFLICT = "conflict"


class KnowledgeConversation(Base):
    """Workspace 内的知识对话，归属创建用户。"""

    __tablename__ = "knowledge_conversations"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scope_type: Mapped[str] = mapped_column(
        String(16), default=SCOPE_WORKSPACE, nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship()
    owner: Mapped["User"] = relationship()
    project: Mapped["Project"] = relationship()
    messages: Mapped[list["KnowledgeMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    runs: Mapped[list["KnowledgeAgentRun"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    context_versions: Mapped[list["KnowledgeContextVersion"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class KnowledgeAgentRun(Base):
    """一次持久化只读问答执行：固化范围快照、状态、取消与降级摘要。"""

    __tablename__ = "knowledge_agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "active_slot",
            name="uq_knowledge_run_active_slot",
        ),
        Index("ix_knowledge_run_claim", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # 范围快照：Run 生成后不随对话当前范围变化
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 消息关联：user_message_id/assistant_message_id 由应用层维护，
    # 避免 messages↔runs 循环外键在 SQLite/MySQL 上的建表兼容问题
    user_message_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(
        BigInteger, index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=RUN_WAITING, nullable=False, index=True
    )
    current_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active_slot: Mapped[str | None] = mapped_column(String(8), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # ---- 上下文决策契约 ----
    request_context_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    context_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    standalone_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # JSON：实际用于判断的历史消息 ID（不保存原始 prompt）
    history_message_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 输入工作集在领取时固化；恢复执行不漂移到后来状态
    input_context_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_context_versions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    output_context_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_context_versions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # JSON：上下文决策/改写阶段降级信息（provider/model/fallback/error/耗时）
    context_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON 汇总：各阶段降级摘要（不保存原始 prompt）
    fallback_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 结构化回答 JSON（终态一次性写入）
    answer_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship(back_populates="runs")
    workspace: Mapped["Workspace"] = relationship()
    tool_calls: Mapped[list["KnowledgeAgentToolCall"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    model_invocations: Mapped[list["KnowledgeAgentModelInvocation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    evidences: Mapped[list["KnowledgeAgentEvidence"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    input_context_version: Mapped["KnowledgeContextVersion | None"] = relationship(
        foreign_keys=[input_context_version_id],
        post_update=True,
    )
    output_context_version: Mapped["KnowledgeContextVersion | None"] = relationship(
        foreign_keys=[output_context_version_id],
        post_update=True,
    )


class KnowledgeMessage(Base):
    """对话消息：用户、助手与范围事件；保存生成时的范围快照。"""

    __tablename__ = "knowledge_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_knowledge_message_client_id",
        ),
        Index("ix_knowledge_message_cursor", "conversation_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"), index=True
    )
    # 消息范围快照：切换范围后历史消息仍保留生成时范围
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship(back_populates="messages")


class KnowledgeAgentToolCall(Base):
    """每次工具调用的可审计记录：脱敏参数摘要与结果摘要。"""

    __tablename__ = "knowledge_agent_tool_calls"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    params_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TOOL_OK, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["KnowledgeAgentRun"] = relationship(back_populates="tool_calls")


class KnowledgeAgentModelInvocation(Base):
    """embedding / 重排 / 回答阶段的逐次模型调用可观测记录。"""

    __tablename__ = "knowledge_agent_model_invocations"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_fallback: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSON：可获得的使用量信息；不保存请求内容
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["KnowledgeAgentRun"] = relationship(back_populates="model_invocations")


class KnowledgeAgentEvidence(Base):
    """本 Run 实际读取并核验的原文证据：最终引用只能指向这些句柄。"""

    __tablename__ = "knowledge_agent_evidences"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # 不透明句柄：服务端生成，模型无法猜测其他 Run 的句柄
    handle: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="SET NULL"), index=True, nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sources.id", ondelete="SET NULL"), index=True, nullable=True
    )
    attachment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # 生成时快照：来源后来变化/删除时历史回答不重写
    entry_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 核验后的真实原文子串（非模型改写文本）
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    quote_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 来源内容指纹：sha256，用于识别来源是否变化
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(16), default=EVIDENCE_PURPOSE_ANSWER, nullable=False
    )
    is_citable: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["KnowledgeAgentRun"] = relationship(back_populates="evidences")
    entry: Mapped["Entry"] = relationship()
    source: Mapped["Source"] = relationship()
    attachment: Mapped["Attachment"] = relationship()


class KnowledgeContextVersion(Base):
    """对话当前主题的不可变工作集版本。

    同一对话最多一个活动版本（`active_slot='active'`）；被替换、新话题或
    范围切换后版本进入终态并保留审计。只保存主题标签与 Entry 线索，
    不保存助手回答或模型摘要。
    """

    __tablename__ = "knowledge_context_versions"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "active_slot",
            name="uq_knowledge_context_active_slot",
        ),
        Index(
            "ix_knowledge_context_claim",
            "conversation_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_context_versions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    source_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # 范围快照：版本生成后不随对话范围变化
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic_label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=CONTEXT_STATUS_ACTIVE, nullable=False
    )
    close_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    active_slot: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship(
        back_populates="context_versions"
    )
    parent_version: Mapped["KnowledgeContextVersion | None"] = relationship(
        remote_side=[id],
        post_update=True,
    )
    items: Mapped[list["KnowledgeWorkingSetItem"]] = relationship(
        back_populates="context_version",
        cascade="all, delete-orphan",
        order_by="KnowledgeWorkingSetItem.sort_order",
    )


class KnowledgeWorkingSetItem(Base):
    """工作集项：只保存正式 Entry 线索与短快照，不保存正文或回答。"""

    __tablename__ = "knowledge_working_set_items"
    __table_args__ = (
        UniqueConstraint(
            "context_version_id",
            "entry_id",
            name="uq_knowledge_working_set_entry",
        ),
        Index("ix_knowledge_working_set_entry_id", "entry_id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    context_version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_context_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="CASCADE"), index=True, nullable=True
    )
    entry_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    include_reason: Mapped[str] = mapped_column(
        String(16), default=WORKING_SET_REASON_CITED, nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    context_version: Mapped["KnowledgeContextVersion"] = relationship(
        back_populates="items"
    )
    entry: Mapped["Entry"] = relationship()
