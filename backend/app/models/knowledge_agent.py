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
    from app.models.extraction import Candidate
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

# ---- Run 类型：普通问答、受控候选草稿与单 Entry 修订操作 ----
RUN_KIND_ANSWER = "answer"
RUN_KIND_DRAFT_CANDIDATE = "draft_candidate"
RUN_KIND_ENTRY_REVISION = "entry_revision"
RUN_KINDS = (
    RUN_KIND_ANSWER,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_KIND_ENTRY_REVISION,
)

# ---- Candidate Draft 状态 ----
DRAFT_GENERATING = "generating"
DRAFT_DRAFT = "draft"
DRAFT_CONFIRMING = "confirming"
DRAFT_CONFIRMED = "confirmed"
DRAFT_CANCELLED = "cancelled"
DRAFT_FAILED = "failed"
DRAFT_STATUSES = (
    DRAFT_GENERATING,
    DRAFT_DRAFT,
    DRAFT_CONFIRMING,
    DRAFT_CONFIRMED,
    DRAFT_CANCELLED,
    DRAFT_FAILED,
)
DRAFT_TERMINAL_STATUSES = {
    DRAFT_CONFIRMED,
    DRAFT_CANCELLED,
    DRAFT_FAILED,
}

# ---- Entry Revision Draft 状态 ----
REVISION_DRAFT_GENERATING = "generating"
REVISION_DRAFT_DRAFT = "draft"
REVISION_DRAFT_CONFIRMING = "confirming"
REVISION_DRAFT_APPLIED = "applied"
REVISION_DRAFT_CANCELLED = "cancelled"
REVISION_DRAFT_FAILED = "failed"
REVISION_DRAFT_UNDONE = "undone"
REVISION_DRAFT_STATUSES = (
    REVISION_DRAFT_GENERATING,
    REVISION_DRAFT_DRAFT,
    REVISION_DRAFT_CONFIRMING,
    REVISION_DRAFT_APPLIED,
    REVISION_DRAFT_CANCELLED,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_UNDONE,
)
REVISION_DRAFT_TERMINAL_STATUSES = {
    REVISION_DRAFT_APPLIED,
    REVISION_DRAFT_CANCELLED,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_UNDONE,
}

# ---- Entry Revision Execution 状态 ----
REVISION_EXECUTION_APPLIED = "applied"
REVISION_EXECUTION_UNDOING = "undoing"
REVISION_EXECUTION_UNDONE = "undone"
REVISION_EXECUTION_STATUSES = (
    REVISION_EXECUTION_APPLIED,
    REVISION_EXECUTION_UNDOING,
    REVISION_EXECUTION_UNDONE,
)

# ---- 上下文模式与决策 ----
CONTEXT_MODE_AUTO = "auto"
CONTEXT_MODE_CONTINUE = "continue"
CONTEXT_MODE_NEW_TOPIC = "new_topic"
CONTEXT_MODES = (CONTEXT_MODE_AUTO, CONTEXT_MODE_CONTINUE, CONTEXT_MODE_NEW_TOPIC)

# ---- 回答模式 ----
ANSWER_MODE_AUTO = "auto"
ANSWER_MODE_QUICK = "quick"
ANSWER_MODE_INVESTIGATE = "investigate"
ANSWER_MODES = (ANSWER_MODE_AUTO, ANSWER_MODE_QUICK, ANSWER_MODE_INVESTIGATE)

# ---- 结果形态（请求与实际分开持久化） ----
RESULT_MODE_AUTO = "auto"
RESULT_MODE_ANSWER = "answer"
RESULT_MODE_ENTRIES = "entries"
RESULT_MODES = (RESULT_MODE_AUTO, RESULT_MODE_ANSWER, RESULT_MODE_ENTRIES)

# ---- 请求依据模式（公开契约：仅 auto / knowledge_only） ----
BASIS_MODE_AUTO = "auto"
BASIS_MODE_KNOWLEDGE_ONLY = "knowledge_only"
BASIS_MODES = (BASIS_MODE_AUTO, BASIS_MODE_KNOWLEDGE_ONLY)

# ---- 内部规划策略（服务端保存，不向普通用户界面暴露） ----
BASIS_STRATEGY_KNOWLEDGE_ONLY = "knowledge_only"
BASIS_STRATEGY_KNOWLEDGE_FIRST = "knowledge_first"
BASIS_STRATEGY_MODEL_FIRST = "model_first"
BASIS_STRATEGY_HYBRID = "hybrid"
BASIS_STRATEGY_EXTERNAL_NEEDED = "external_needed"
BASIS_STRATEGIES = (
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_KNOWLEDGE_FIRST,
    BASIS_STRATEGY_MODEL_FIRST,
    BASIS_STRATEGY_HYBRID,
    BASIS_STRATEGY_EXTERNAL_NEEDED,
)

# ---- 外部材料状态（AnswerBasis v1） ----
EXTERNAL_MATERIAL_NOT_USED = "not_used"
EXTERNAL_MATERIAL_REQUIRED_UNAVAILABLE = "required_unavailable"
EXTERNAL_MATERIAL_STATUSES = (
    EXTERNAL_MATERIAL_NOT_USED,
    EXTERNAL_MATERIAL_REQUIRED_UNAVAILABLE,
)

# ---- 结构化 Entry 结果完整性 ----
RESULT_COMPLETENESS_COMPLETE = "complete"
RESULT_COMPLETENESS_LIMITED = "limited"
RESULT_COMPLETENESS_UNKNOWN = "unknown"
RESULT_COMPLETENESSES = (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
)

# ---- 一次结构化查询计划与确定性工具 ----
STRUCTURED_QUERY_PLAN_VERSION = "v1"
STRUCTURED_QUERY_RESULT_VERSION = "v2"

STRUCTURED_QUERY_OUTPUT_ENTRIES = "entries"
STRUCTURED_QUERY_OUTPUT_COUNT = "count"
STRUCTURED_QUERY_OUTPUT_GROUP_COUNT = "group_count"
STRUCTURED_QUERY_OUTPUT_TYPES = (
    STRUCTURED_QUERY_OUTPUT_ENTRIES,
    STRUCTURED_QUERY_OUTPUT_COUNT,
    STRUCTURED_QUERY_OUTPUT_GROUP_COUNT,
)

STRUCTURED_QUERY_GROUP_MAIN_TYPE = "main_type"
STRUCTURED_QUERY_GROUP_INFO_NATURE = "info_nature"
STRUCTURED_QUERY_GROUP_UPDATED_MONTH = "updated_month"
STRUCTURED_QUERY_GROUP_FIELDS = (
    STRUCTURED_QUERY_GROUP_MAIN_TYPE,
    STRUCTURED_QUERY_GROUP_INFO_NATURE,
    STRUCTURED_QUERY_GROUP_UPDATED_MONTH,
)

STRUCTURED_QUERY_SORT_RELEVANCE = "relevance"
STRUCTURED_QUERY_SORT_UPDATED_AT = "updated_at"
STRUCTURED_QUERY_SORT_CREATED_AT = "created_at"
STRUCTURED_QUERY_SORT_FIELDS = (
    STRUCTURED_QUERY_SORT_RELEVANCE,
    STRUCTURED_QUERY_SORT_UPDATED_AT,
    STRUCTURED_QUERY_SORT_CREATED_AT,
)

STRUCTURED_QUERY_SORT_ASC = "asc"
STRUCTURED_QUERY_SORT_DESC = "desc"
STRUCTURED_QUERY_SORT_DIRECTIONS = (
    STRUCTURED_QUERY_SORT_ASC,
    STRUCTURED_QUERY_SORT_DESC,
)

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

# ---- Run 步骤（调查分支扩展） ----
STEP_INVESTIGATION_ROUTE = "investigation_route"
STEP_ROUND_PLAN = "round_plan"
STEP_ROUND_SEARCH = "round_search"
STEP_ROUND_EVIDENCE = "round_evidence"
STEP_SYNTHESIZE = "synthesize"

# ---- Run 步骤（结构化 Entry 查找分支） ----
STEP_RESULT_MODE_ROUTE = "result_mode_route"
STEP_ENTRY_SEARCH = "entry_search"
STEP_ENTRY_ASSEMBLE = "entry_assemble"
STEP_STRUCTURED_QUERY_PLAN = "structured_query_plan"
STEP_STRUCTURED_QUERY_EXECUTE = "structured_query_execute"

# ---- Run 步骤（开放讨论依据规划分支） ----
STEP_BASIS_ROUTE = "basis_route"

# ---- Run 步骤（候选草稿操作分支） ----
STEP_DRAFT_VERIFY_EVIDENCE = "draft_verify_evidence"
STEP_DRAFT_GENERATE = "draft_generate"
STEP_DRAFT_VALIDATE = "draft_validate"

# ---- Run 步骤（单 Entry 修订操作分支） ----
STEP_REVISION_VERIFY_EVIDENCE = "revision_verify_evidence"
STEP_REVISION_GENERATE = "revision_generate"
STEP_REVISION_VALIDATE = "revision_validate"

# ---- 模型调用用途 ----
PURPOSE_CONTEXT_DECISION = "context_decision"
PURPOSE_EMBEDDING = "embedding"
PURPOSE_RERANK = "rerank"
PURPOSE_ANSWER = "answer"
PURPOSE_ANSWER_MODE_ROUTE = "answer_mode_route"
PURPOSE_RESULT_MODE_ROUTE = "result_mode_route"
PURPOSE_INVESTIGATION_CONTROLLER = "investigation_controller"
PURPOSE_SYNTHESIS = "synthesis"
PURPOSE_DRAFT_CANDIDATE = "draft_candidate"
PURPOSE_ENTRY_REVISION = "entry_revision"
PURPOSE_STRUCTURED_QUERY_PLAN = "structured_query_plan"

# ---- 模型调用用途（开放讨论依据规划） ----
PURPOSE_BASIS_ROUTE = "basis_route"

# ---- 调查状态 ----
INVESTIGATION_STATUS_ACTIVE = "active"
INVESTIGATION_STATUS_COMPLETED = "completed"
INVESTIGATION_STATUS_INSUFFICIENT = "insufficient"
INVESTIGATION_STATUS_CANCELLED = "cancelled"
INVESTIGATION_STATUS_FAILED = "failed"
INVESTIGATION_TERMINAL_STATUSES = {
    INVESTIGATION_STATUS_COMPLETED,
    INVESTIGATION_STATUS_INSUFFICIENT,
    INVESTIGATION_STATUS_CANCELLED,
    INVESTIGATION_STATUS_FAILED,
}

# ---- 调查轮次状态 ----
INVESTIGATION_ROUND_RUNNING = "running"
INVESTIGATION_ROUND_COMPLETED = "completed"
INVESTIGATION_ROUND_CANCELLED = "cancelled"
INVESTIGATION_ROUND_FAILED = "failed"

# ---- 调查查询状态 ----
INVESTIGATION_QUERY_PLANNED = "planned"
INVESTIGATION_QUERY_RUNNING = "running"
INVESTIGATION_QUERY_EXECUTED = "executed"
INVESTIGATION_QUERY_EMPTY = "empty"
INVESTIGATION_QUERY_PARTIAL = "partial"
INVESTIGATION_QUERY_ERROR = "error"

# ---- 调查停止原因（稳定枚举） ----
STOP_REASON_CONTROLLER_COMPLETE = "controller_complete"
STOP_REASON_INSUFFICIENT = "insufficient"
STOP_REASON_NO_PROGRESS = "no_progress"
STOP_REASON_MAX_ROUNDS = "max_rounds"
STOP_REASON_QUERY_BUDGET = "query_budget"
STOP_REASON_ENTRY_BUDGET = "entry_budget"
STOP_REASON_EVIDENCE_BUDGET = "evidence_budget"
STOP_REASON_CANCELLED = "cancelled"
STOP_REASON_FAILED = "failed"
STOP_REASONS = (
    STOP_REASON_CONTROLLER_COMPLETE,
    STOP_REASON_INSUFFICIENT,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_MAX_ROUNDS,
    STOP_REASON_QUERY_BUDGET,
    STOP_REASON_ENTRY_BUDGET,
    STOP_REASON_EVIDENCE_BUDGET,
    STOP_REASON_CANCELLED,
    STOP_REASON_FAILED,
)

# ---- 调查控制器动作 ----
INVESTIGATION_ACTION_SEARCH = "search"
INVESTIGATION_ACTION_ANSWER = "answer"
INVESTIGATION_ACTION_INSUFFICIENT = "insufficient"
INVESTIGATION_ACTIONS = (
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
)

# ---- 工具调用状态 ----
TOOL_OK = "ok"
TOOL_EMPTY = "empty"
TOOL_PARTIAL = "partial"
TOOL_DENIED = "denied"
TOOL_UNAVAILABLE = "unavailable"
TOOL_ERROR = "error"

# 新只读 dispatcher 使用的稳定状态；旧工具状态继续兼容保留
TOOL_COMPLETED = "completed"
TOOL_LIMITED = "limited"
TOOL_CANCELLED = "cancelled"
TOOL_STATUSES = (
    TOOL_COMPLETED,
    TOOL_EMPTY,
    TOOL_LIMITED,
    TOOL_PARTIAL,
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_CANCELLED,
    TOOL_OK,
    TOOL_UNAVAILABLE,
)

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
    # Run 类型：answer（默认，普通只读问答）、draft_candidate（受控候选草稿操作）
    # 或 entry_revision（受控单 Entry 修订操作）
    run_kind: Mapped[str] = mapped_column(
        String(16), default=RUN_KIND_ANSWER, server_default=RUN_KIND_ANSWER, nullable=False
    )
    # 操作 Run 锚定的来源回答 Run（仅 draft_candidate / entry_revision 使用；自引用外键）
    source_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # 操作 Run 锚定的目标正式 Entry（仅 entry_revision 使用）
    target_entry_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("entries.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
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
    # ---- 回答模式契约：请求模式与路由后的实际模式分开保存 ----
    request_answer_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actual_answer_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # ---- 结果形态契约：请求形态与路由后的实际形态分开保存 ----
    request_result_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    actual_result_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # ---- 依据契约：请求模式、可恢复规划与实际形成依据（AnswerBasis v1 JSON） ----
    request_basis_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    planned_basis_strategy: Mapped[str | None] = mapped_column(String(16), nullable=True)
    planned_basis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_basis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # 当前调查轮次（轮询进度；非调查 Run 保持 None/0）
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSON：调查摘要（实际模式、轮数、查询数、停止原因、覆盖/缺口/冲突、降级）
    investigation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 结构化回答 JSON（终态一次性写入）
    answer_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 结构化 Entry 结果 JSON（终态一次性写入；有界快照，不保存完整正文）
    entry_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # StructuredQueryPlan v1：只保存服务端校验、规范化后的计划；旧 Run 保持为空
    structured_query_plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    investigation: Mapped["KnowledgeInvestigation | None"] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class KnowledgeCandidateDraft(Base):
    """锚定回答 Run 的候选草稿：Agent 只生成草稿，用户确认后才创建 Candidate。

    约束与语义：
    - operation_run_id 唯一：一个操作 Run 至多一个 Draft，崩溃恢复复用同一 Draft；
    - confirmed_candidate_id 唯一：确认结果只能写一次，重复确认返回同一 Candidate；
    - (conversation_id, client_operation_id) 唯一：稳定幂等键只在一个对话内生效；
    - target_project_id/name 为生成时快照，历史恢复不随对话当前范围漂移；
    - evidence_handles_json 只保存服务端允许集合内的句柄，客户端不可编辑。
    """

    __tablename__ = "knowledge_candidate_drafts"
    __table_args__ = (
        UniqueConstraint(
            "operation_run_id",
            name="uq_knowledge_candidate_draft_operation_run",
        ),
        UniqueConstraint(
            "confirmed_candidate_id",
            name="uq_knowledge_candidate_draft_candidate",
        ),
        UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_candidate_draft_operation_key",
        ),
        Index(
            "ix_knowledge_candidate_draft_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    operation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # 目标项目快照：草稿生成后不随对话范围切换变化
    target_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    target_project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=DRAFT_GENERATING, nullable=False
    )
    # 草稿字段：generating 期间为空，生成成功进入 draft 后填充
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    info_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # JSON：采用的服务端 Evidence 句柄（白名单校验后保存）
    evidence_handles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON：生成可观测信息（provider/model/fallback/error/duration/prompt_version/usage）
    generation_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 确认幂等键：首次确认事务内写入；重复确认按 confirmed_candidate_id 重放
    client_operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_candidate_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("candidates.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship()
    operation_run: Mapped["KnowledgeAgentRun"] = relationship(
        foreign_keys=[operation_run_id]
    )
    source_run: Mapped["KnowledgeAgentRun | None"] = relationship(
        foreign_keys=[source_run_id]
    )
    confirmed_candidate: Mapped["Candidate | None"] = relationship(
        foreign_keys=[confirmed_candidate_id]
    )


class KnowledgeEntryRevisionDraft(Base):
    """锚定回答与单条正式 Entry 的修订草稿：候选内容、基线快照与执行关联。

    约束与语义：
    - operation_run_id 唯一：一个操作 Run 至多一个草稿，崩溃恢复复用同一草稿；
    - (conversation_id, client_operation_id) 唯一：确认幂等键只在一个对话内生效；
    - target_entry_id/target_project_id 为生成时快照，历史恢复不随对话范围漂移；
    - base_entry_json 与 base_entry_fingerprint 固化操作前 Entry 状态，服务端
      用它计算差异与乐观并发校验，客户端不得编辑；
    - allowed/selected Evidence 句柄只保存服务端允许集合内的值，客户端不可编辑。
    """

    __tablename__ = "knowledge_entry_revision_drafts"
    __table_args__ = (
        UniqueConstraint(
            "operation_run_id",
            name="uq_knowledge_entry_revision_draft_operation_run",
        ),
        UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_entry_revision_draft_operation_key",
        ),
        Index(
            "ix_knowledge_entry_revision_draft_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    operation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_run_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # 目标 Entry 与项目快照：由来源回答最终 citations 服务端解析，客户端不可指定
    target_entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="SET NULL"), index=True, nullable=True
    )
    target_project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    target_project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 用户显式修订指令（非空；普通 Composer 不进入本流程）
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # 不可变基线：操作前 Entry 字段 JSON 与规范化指纹、基线版本
    base_entry_json: Mapped[str] = mapped_column(Text, nullable=False)
    base_entry_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    base_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 服务端允许集合与采用集合（JSON 句柄列表）
    allowed_evidence_handles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_evidence_handles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 候选字段：generating 期间为空，生成成功进入 draft 后填充；用户可编辑
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    info_nature: Mapped[str | None] = mapped_column(String(16), nullable=True)
    applicable_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON：生成可观测信息（provider/model/fallback/error/duration/prompt_version）
    generation_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=REVISION_DRAFT_GENERATING, nullable=False
    )
    # 确认幂等键：首次确认事务内写入；重复确认按 Execution 重放
    client_operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_entry_revision_executions.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship()
    operation_run: Mapped["KnowledgeAgentRun"] = relationship(
        foreign_keys=[operation_run_id]
    )
    source_run: Mapped["KnowledgeAgentRun | None"] = relationship(
        foreign_keys=[source_run_id]
    )
    target_entry: Mapped["Entry | None"] = relationship(
        foreign_keys=[target_entry_id]
    )
    execution: Mapped["KnowledgeEntryRevisionExecution | None"] = relationship(
        foreign_keys=[execution_id]
    )


class KnowledgeEntryRevisionExecution(Base):
    """Knowledge Agent 修订确认/撤销的执行审计与条件恢复依据。

    语义：
    - draft_id 唯一：一次确认至多创建一条 Execution，重复确认按幂等键重放；
    - (conversation_id, client_operation_id) 唯一：确认幂等键；
    - (conversation_id, undo_client_operation_id) 唯一：撤销幂等键；
    - before/after 快照与指纹由应用服务在事务内写入，撤销不依赖可能被滚动
      清理的旧 EntryVersion；
    - added_evidence_ids_json 只记录本次事务真实新增的 EntrySourceEvidence id，
      撤销只删除这些仍属于目标 Entry 的关系。
    """

    __tablename__ = "knowledge_entry_revision_executions"
    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            name="uq_knowledge_entry_revision_execution_draft",
        ),
        UniqueConstraint(
            "conversation_id",
            "client_operation_id",
            name="uq_knowledge_entry_revision_execution_operation_key",
        ),
        UniqueConstraint(
            "conversation_id",
            "undo_client_operation_id",
            name="uq_knowledge_entry_revision_execution_undo_key",
        ),
        Index(
            "ix_knowledge_entry_revision_execution_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    draft_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_entry_revision_drafts.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    entry_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("entries.id", ondelete="SET NULL"), index=True, nullable=True
    )
    client_operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # 操作前/后字段快照与规范化指纹
    before_entry_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_entry_json: Mapped[str] = mapped_column(Text, nullable=False)
    before_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    after_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # 操作前/后 Entry 版本（版本号与版本记录 id）
    before_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    before_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    after_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON：本操作真实新增的 EntrySourceEvidence id 列表
    added_evidence_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=REVISION_EXECUTION_APPLIED, nullable=False
    )
    # 撤销幂等键：首次撤销事务内写入；已 undone 重试返回同一结果
    undo_client_operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    conversation: Mapped["KnowledgeConversation"] = relationship()
    draft: Mapped["KnowledgeEntryRevisionDraft"] = relationship(
        foreign_keys=[draft_id]
    )
    entry: Mapped["Entry | None"] = relationship(foreign_keys=[entry_id])


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
    # 可选调查归属：用于逐轮审计
    investigation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_investigations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # 可选调查归属：路由/控制器/综合阶段的轮次与查询归属
    investigation_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_investigations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # 证据轮次归属：多轮命中同一 Evidence 时保留首轮归属并幂等复用
    round_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    query_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
        UniqueConstraint(
            "conversation_id",
            "version_number",
            name="uq_knowledge_context_version_number",
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


class KnowledgeInvestigation(Base):
    """Run 一对一的有界自主调查：固化范围、预算、进度、停止原因与恢复时间。

    调查账本只属于当前 Run，不是跨对话记忆；覆盖/缺口/冲突只保存有长度上限
    的 JSON 摘要，不保存整份 Attachment 或无限 prompt。
    """

    __tablename__ = "knowledge_investigations"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_knowledge_investigation_run"),
        Index("ix_knowledge_investigation_status", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
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
    # 调查固化范围：创建后不随对话当前范围变化
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    project_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    requested_answer_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_answer_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=INVESTIGATION_STATUS_ACTIVE, nullable=False
    )
    # 预算快照：创建时固化，客户端/模型不能放大
    max_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_queries_per_round: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    max_total_queries: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    max_entries: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_evidence: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    # 进度与累计计数
    current_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_queries_executed: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    distinct_entries_found: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    citable_evidence_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # JSON 摘要：过程观察，不是正式知识
    coverage_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    gaps_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicts_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    run: Mapped["KnowledgeAgentRun"] = relationship(back_populates="investigation")
    conversation: Mapped["KnowledgeConversation"] = relationship()
    rounds: Mapped[list["KnowledgeInvestigationRound"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="KnowledgeInvestigationRound.round_number",
    )
    queries: Mapped[list["KnowledgeInvestigationQuery"]] = relationship(
        back_populates="investigation",
        cascade="all, delete-orphan",
        order_by="KnowledgeInvestigationQuery.round_number, KnowledgeInvestigationQuery.sequence",
    )


class KnowledgeInvestigationRound(Base):
    """一轮调查的持久化检查点：控制器动作、观察摘要、增量计数与调用归属。"""

    __tablename__ = "knowledge_investigation_rounds"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "round_number",
            name="uq_knowledge_investigation_round_number",
        ),
        Index(
            "ix_knowledge_investigation_round_claim",
            "investigation_id",
            "status",
            "round_number",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    investigation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_investigations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=INVESTIGATION_ROUND_RUNNING, nullable=False
    )
    controller_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 有长度上限的 JSON 观察摘要（应用层写入前截断）
    coverage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    gaps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON：本轮新发现 Entry 的短快照与不可用/越权对象（账本重建线索）
    entries_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unavailable_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    queries_planned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    queries_executed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entries_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # JSON：控制器模型调用归属（provider/model/fallback/error/duration_ms/prompt_version）
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    investigation: Mapped["KnowledgeInvestigation"] = relationship(
        back_populates="rounds"
    )
    queries: Mapped[list["KnowledgeInvestigationQuery"]] = relationship(
        back_populates="round",
        cascade="all, delete-orphan",
        order_by="KnowledgeInvestigationQuery.sequence",
    )


class KnowledgeInvestigationQuery(Base):
    """轮次内的一条计划/已执行查询：规范化指纹全局去重与执行状态留痕。"""

    __tablename__ = "knowledge_investigation_queries"
    __table_args__ = (
        UniqueConstraint(
            "investigation_id",
            "normalized_query_hash",
            name="uq_knowledge_investigation_query_hash",
        ),
        Index(
            "ix_knowledge_investigation_query_round",
            "investigation_id",
            "round_number",
            "sequence",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    investigation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_investigations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    round_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_investigation_rounds.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=INVESTIGATION_QUERY_PLANNED, nullable=False
    )
    # JSON：结果计数（命中/新增 Entry、Evidence、denied/unavailable）
    result_counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    investigation: Mapped["KnowledgeInvestigation"] = relationship(
        back_populates="queries"
    )
    round: Mapped["KnowledgeInvestigationRound | None"] = relationship(
        back_populates="queries"
    )
