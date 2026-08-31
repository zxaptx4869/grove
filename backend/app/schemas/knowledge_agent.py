"""知识 Agent 对话、Run、可观测记录与回答响应模型。

契约约束：API 不返回原始 prompt、模型敏感输入或整份 Attachment；
工具参数与结果只暴露脱敏摘要；引用只暴露服务端核验过的 Evidence 原文片段。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeScopeType = Literal["workspace", "project"]

RunStatus = Literal[
    "waiting",
    "processing",
    "completed",
    "partial",
    "failed",
    "cancelled",
]

RunKind = Literal["answer", "draft_candidate", "entry_revision"]

AnswerStatus = Literal[
    "completed",
    "partial",
    "insufficient",
    "failed",
    "clarification",
]

DraftStatus = Literal[
    "generating",
    "draft",
    "confirming",
    "confirmed",
    "cancelled",
    "failed",
]
RevisionDraftStatus = Literal[
    "generating",
    "draft",
    "confirming",
    "applied",
    "cancelled",
    "failed",
    "undone",
]
RevisionExecutionStatus = Literal["applied", "undoing", "undone"]
ContextMode = Literal["auto", "continue", "new_topic"]
ContextDecision = Literal["continue", "new_topic", "clarify"]
AnswerMode = Literal["auto", "quick", "investigate"]
ResultMode = Literal["auto", "answer", "entries"]
ActualResultMode = Literal["answer", "entries"]
ResultCompleteness = Literal["complete", "limited", "unknown"]
InvestigationStopReason = Literal[
    "controller_complete",
    "insufficient",
    "no_progress",
    "max_rounds",
    "query_budget",
    "entry_budget",
    "evidence_budget",
    "cancelled",
    "failed",
]


class KnowledgeConversationCreate(BaseModel):
    """创建知识对话：范围只能是 Workspace「全部知识」或具体项目。"""

    scope_type: KnowledgeScopeType = "workspace"
    project_id: int | None = None


class KnowledgeConversationOut(BaseModel):
    """知识对话摘要：含活动主题与活动工作集版本摘要。"""

    id: int
    title: str
    scope_type: KnowledgeScopeType
    project_id: int | None
    project_name: str | None = None
    active_topic_label: str | None = None
    active_context_version_id: int | None = None
    active_entry_count: int = 0
    # 最近 Run 摘要：用于客户端恢复活动/最近执行状态，不复制完整 Run
    recent_run_id: int | None = None
    recent_run_status: RunStatus | None = None
    recent_run_current_step: str | None = None
    recent_run_updated_at: datetime | None = None
    last_activity_at: datetime
    created_at: datetime


class KnowledgeScopeChangeRequest(BaseModel):
    """切换对话当前范围；活动 Run 期间切换返回 409。"""

    scope_type: KnowledgeScopeType
    project_id: int | None = None


class KnowledgeMessageOut(BaseModel):
    """单条对话消息：保留生成时的范围快照。"""

    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system"]
    message_type: Literal["user", "assistant", "scope_change"]
    content: str
    client_message_id: str | None = None
    run_id: int | None = None
    scope_type: KnowledgeScopeType
    project_id: int | None = None
    project_name: str | None = None
    # 关联 Run 的上下文契约（消息没有 Run 时为空）
    request_context_mode: ContextMode | None = None
    context_decision: ContextDecision | None = None
    standalone_query: str | None = None
    topic_label: str | None = None
    request_answer_mode: AnswerMode | None = None
    actual_answer_mode: AnswerMode | None = None
    request_result_mode: ResultMode | None = None
    actual_result_mode: ActualResultMode | None = None
    current_round: int = 0
    input_context_version_id: int | None = None
    output_context_version_id: int | None = None
    created_at: datetime


class KnowledgeMessagePageOut(BaseModel):
    """游标分页的消息页：无 cursor 时返回最近一页且页内按时间正序；
    `next_cursor` 指向更早消息；`runs` 是本页关联且去重的 Run 集合；
    `candidate_drafts` 是本页 operation Run 关联且去重的草稿集合。"""

    items: list[KnowledgeMessageOut]
    next_cursor: str | None = None
    runs: list["KnowledgeRunOut"] = []
    candidate_drafts: list["KnowledgeCandidateDraftOut"] = []
    entry_revision_drafts: list["KnowledgeEntryRevisionDraftOut"] = []


class KnowledgeRunCitationOut(BaseModel):
    """最终回答引用：来自本 Run 服务端核验的 Evidence。"""

    evidence_id: int
    evidence_handle: str
    entry_id: int
    entry_title: str
    source_id: int
    source_title: str
    attachment_id: int | None = None
    quote: str
    # Evidence 创建时保存的归属与目录快照：对象后来变化/删除不影响历史回答
    project_id: int | None = None
    project_name: str | None = None
    node_path: str | None = None


class KnowledgeConflictOut(BaseModel):
    """由不同有效 Evidence 支持的冲突展示。

    `citation_a` / `citation_b` 携带双方完整可展示 Evidence；旧响应可能只有
    兼容的扁平字段，客户端按缺失兜底展示。
    """

    summary: str
    evidence_id_a: int
    entry_id_a: int
    entry_title_a: str
    evidence_id_b: int
    entry_id_b: int
    entry_title_b: str
    citation_a: "KnowledgeRunCitationOut | None" = None
    citation_b: "KnowledgeRunCitationOut | None" = None


class KnowledgeAnswerPointOut(BaseModel):
    """回答结构化要点：每条携带服务端重验后的逐条引用。"""

    section: str | None = None
    text: str
    citations: list[KnowledgeRunCitationOut] = []


class KnowledgeAnswerOut(BaseModel):
    """结构化回答：引用只能来自本 Run 的 Evidence 句柄。"""

    answer: str
    status: AnswerStatus
    insufficient_note: str | None = None
    # v3：可选结构化要点；旧回答/旧模型输出为空列表
    points: list[KnowledgeAnswerPointOut] = []
    citations: list[KnowledgeRunCitationOut] = []
    conflicts: list[KnowledgeConflictOut] = []
    # 只由本 Run 最终有效引用支撑的终态覆盖/缺口，不复用控制器搜索前计划。
    coverage: list[str] = []
    gaps: list[str] = []


class KnowledgeEntryResultItemOut(BaseModel):
    """结构化 Entry 结果项：正式知识对象快照，不是 Citation。

    只保存服务端从正式 Entry / Project / Node / Evidence 关系装配的有界字段；
    不保存完整正文、Source 原文、prompt、伪相关度或模型编造理由。
    """

    entry_id: int
    title: str
    excerpt: str
    project_id: int | None = None
    project_name: str | None = None
    node_id: int | None = None
    node_path: str | None = None
    main_type: str | None = None
    info_nature: str | None = None
    updated_at: datetime
    source_count: int = 0
    # 生成时 Entry 内容/归属指纹：详情对比「已更新/当前」使用
    fingerprint: str | None = None
    # 服务端可验证的匹配线索；纯语义召回无法证明时省略
    match_hint: str | None = None
    matched_fields: list[str] = []


class KnowledgeEntryResultSnapshotOut(BaseModel):
    """Run 上持久化的有界 Entry 结果快照（首屏随 Run/消息页返回）。"""

    schema_version: str = "v1"
    query: str
    status: Literal["completed", "partial"]
    completeness: ResultCompleteness
    items: list[KnowledgeEntryResultItemOut] = []
    returned_count: int
    candidate_limit: int
    warning: str | None = None
    snapshot_updated_at: datetime


class KnowledgeEntryResultsPageOut(BaseModel):
    """结果分页响应：只读取同一持久化快照，不重新搜索。"""

    schema_version: str = "v1"
    status: Literal["completed", "partial"]
    completeness: ResultCompleteness
    items: list[KnowledgeEntryResultItemOut]
    returned_count: int
    total_in_snapshot: int
    candidate_limit: int
    has_more: bool
    next_cursor: str | None = None
    warning: str | None = None
    snapshot_updated_at: datetime


class FallbackStageOut(BaseModel):
    """单个 AI 阶段的降级状态。"""

    purpose: str
    is_fallback: bool
    provider: str | None = None
    model: str | None = None
    error: str | None = None


class FallbackSummaryOut(BaseModel):
    """Run 聚合降级摘要：可识别具体受影响阶段，不掩盖局部失败。"""

    has_fallback: bool = False
    stages: list[FallbackStageOut] = []


class InvestigationSummaryOut(BaseModel):
    """Run 上聚合的调查摘要：过程元数据，不是正式知识。"""

    requested_answer_mode: AnswerMode
    actual_answer_mode: AnswerMode | None = None
    rounds_completed: int = 0
    queries_executed: int = 0
    stop_reason: InvestigationStopReason | None = None
    coverage: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []


class KnowledgeRunOut(BaseModel):
    """一次持久化只读 Run 的查询结果。"""

    id: int
    conversation_id: int
    # 操作类型：普通问答（answer）或受控候选草稿（draft_candidate）
    run_kind: RunKind = "answer"
    # 操作 Run 锚定的来源回答 Run（仅 draft_candidate 使用）
    source_run_id: int | None = None
    # 操作 Run 锚定的目标正式 Entry（仅 entry_revision 使用）
    target_entry_id: int | None = None
    status: RunStatus
    current_step: str | None = None
    scope_type: KnowledgeScopeType
    project_id: int | None = None
    project_name: str | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    cancel_requested: bool = False
    retry_count: int = 0
    max_retries: int = 1
    error: str | None = None
    # 上下文决策契约
    request_context_mode: ContextMode | None = None
    context_decision: ContextDecision | None = None
    standalone_query: str | None = None
    topic_label: str | None = None
    request_answer_mode: AnswerMode | None = None
    actual_answer_mode: AnswerMode | None = None
    request_result_mode: ResultMode | None = None
    actual_result_mode: ActualResultMode | None = None
    current_round: int = 0
    input_context_version_id: int | None = None
    output_context_version_id: int | None = None
    context_degraded: bool = False
    fallback_summary: FallbackSummaryOut | None = None
    investigation_summary: InvestigationSummaryOut | None = None
    answer: KnowledgeAnswerOut | None = None
    entry_result: KnowledgeEntryResultSnapshotOut | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeRunSubmitRequest(BaseModel):
    """提交新问题：client_message_id 用于网络重试幂等；模式默认 auto。"""

    client_message_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    context_mode: ContextMode = "auto"
    answer_mode: AnswerMode = "auto"
    result_mode: ResultMode = "auto"


class KnowledgeRunSubmitOut(BaseModel):
    """消息提交结果：立即返回等待中的 Run，客户端轮询恢复。"""

    user_message: KnowledgeMessageOut
    run: KnowledgeRunOut


class KnowledgeDraftActionRequest(BaseModel):
    """显式「整理成知识」动作：锚定本会话的来源回答 Run 与可选目标项目。"""

    client_message_id: str = Field(min_length=1, max_length=64)
    source_run_id: int
    # Workspace 多项目回答必须先由用户选择目标项目；项目范围回答可不传（服务端固化）
    target_project_id: int | None = None


class KnowledgeDraftEvidenceOut(BaseModel):
    """草稿采用的当前可核验 Evidence 摘要（服务端重验后输出）。"""

    handle: str
    entry_id: int
    entry_title: str
    source_id: int
    source_title: str
    quote: str


class KnowledgeCandidateDraftOut(BaseModel):
    """持久化候选草稿：AI 建议语义，客户端只读状态与可编辑字段。"""

    id: int
    conversation_id: int
    operation_run_id: int
    source_run_id: int | None = None
    target_project_id: int | None = None
    target_project_name: str | None = None
    status: DraftStatus
    title: str | None = None
    content: str | None = None
    main_type: str | None = None
    info_nature: str | None = None
    evidence_handles: list[str] = []
    evidence_summaries: list[KnowledgeDraftEvidenceOut] = []
    generation_degraded: bool = False
    generation_error: str | None = None
    confirmed_candidate_id: int | None = None
    # 确认后目录推荐/关系判断状态：pending 表示对应辅助步骤尚未完成
    routing_status: str | None = None
    relation_status: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDraftActionOut(BaseModel):
    """草稿动作提交结果：可见用户消息、operation Run 与 generating Draft。"""

    user_message: KnowledgeMessageOut
    run: KnowledgeRunOut
    draft: KnowledgeCandidateDraftOut


class KnowledgeDraftEditRequest(BaseModel):
    """编辑草稿允许字段；目标项目、source Run 与 Evidence 集合不可编辑。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None


class KnowledgeDraftConfirmRequest(BaseModel):
    """确认草稿：只接收稳定幂等键，不接受任何自由引用字段。"""

    client_operation_id: str = Field(min_length=1, max_length=64)


class CandidateReceiptOut(BaseModel):
    """确认后创建的待确认 Candidate 回执。"""

    id: int
    title: str
    status: str
    source_id: int
    routing_status: str
    recommended_node_id: int | None = None
    relation_status: str
    relation_target_entry_id: int | None = None
    created_at: datetime


class KnowledgeDraftConfirmOut(BaseModel):
    """确认回执：Draft 进入 confirmed，Candidate 仍待确认、尚未写入正式知识。"""

    draft: KnowledgeCandidateDraftOut
    candidate: CandidateReceiptOut


class KnowledgeRevisionActionRequest(BaseModel):
    """显式「修订这条知识」动作：锚定来源回答 Run、目标 Entry 与非空指令。"""

    client_message_id: str = Field(min_length=1, max_length=64)
    source_run_id: int
    target_entry_id: int
    instruction: str = Field(min_length=1, max_length=2000)


class KnowledgeRevisionFieldDiffOut(BaseModel):
    """单字段差异：服务端按 base snapshot 与当前草稿计算，客户端不提交 diff。"""

    field: str
    label: str
    before: str | None = None
    after: str | None = None


class KnowledgeRevisionExecutionOut(BaseModel):
    """一次确认/撤销执行的可展示摘要；不暴露内部快照与幂等键。"""

    id: int
    draft_id: int
    entry_id: int | None = None
    status: RevisionExecutionStatus
    before_version_number: int | None = None
    after_version_number: int | None = None
    added_evidence_count: int = 0
    error: str | None = None
    undone_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeEntryRevisionDraftOut(BaseModel):
    """持久化修订草稿：AI 建议语义，展示可编辑字段与服务端差异。"""

    id: int
    conversation_id: int
    operation_run_id: int
    source_run_id: int | None = None
    target_entry_id: int | None = None
    target_project_id: int | None = None
    target_project_name: str | None = None
    instruction: str
    status: RevisionDraftStatus
    title: str | None = None
    content: str | None = None
    main_type: str | None = None
    info_nature: str | None = None
    applicable_condition: str | None = None
    note: str | None = None
    change_summary: str | None = None
    reason: str | None = None
    selected_evidence_handles: list[str] = []
    evidence_summaries: list[KnowledgeDraftEvidenceOut] = []
    # 服务端按 base snapshot 计算的字段差异；未变字段不返回
    changed_fields: list[KnowledgeRevisionFieldDiffOut] = []
    generation_degraded: bool = False
    generation_error: str | None = None
    execution: KnowledgeRevisionExecutionOut | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeRevisionActionOut(BaseModel):
    """修订动作提交结果：可见用户消息、entry_revision Run 与 generating Draft。"""

    user_message: KnowledgeMessageOut
    run: KnowledgeRunOut
    draft: KnowledgeEntryRevisionDraftOut


class KnowledgeRevisionDraftEditRequest(BaseModel):
    """编辑候选字段；target Entry/项目/source Run/基线与 Evidence 集合不可编辑。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=8000)
    note: str | None = Field(default=None, max_length=8000)
    change_summary: str | None = Field(default=None, min_length=1, max_length=1000)


class KnowledgeRevisionConfirmRequest(BaseModel):
    """确认修订：只接收稳定幂等键，不接受任何自由引用字段。"""

    client_operation_id: str = Field(min_length=1, max_length=64)


class KnowledgeRevisionUndoRequest(BaseModel):
    """撤销修订：只接收稳定幂等键，不接受任何自由引用字段。"""

    client_operation_id: str = Field(min_length=1, max_length=64)


class KnowledgeRevisionEntryOut(BaseModel):
    """确认/撤销后的正式 Entry 摘要（移动端回执使用）。"""

    id: int
    title: str
    project_id: int
    project_name: str | None = None
    node_id: int
    node_name: str | None = None
    version_number: int | None = None
    updated_at: datetime


class KnowledgeRevisionConfirmOut(BaseModel):
    """确认回执：Entry 已更新、版本已追加、Execution 为 applied。"""

    draft: KnowledgeEntryRevisionDraftOut
    execution: KnowledgeRevisionExecutionOut
    entry: KnowledgeRevisionEntryOut


class KnowledgeRevisionUndoOut(BaseModel):
    """撤销回执：Entry 已恢复、Execution 为 undone，审计保留。"""

    draft: KnowledgeEntryRevisionDraftOut
    execution: KnowledgeRevisionExecutionOut
    entry: KnowledgeRevisionEntryOut


class KnowledgeToolCallOut(BaseModel):
    """工具调用可审计记录（脱敏摘要）。"""

    id: int
    sequence: int
    tool_name: str
    params_summary: str | None = None
    result_summary: str | None = None
    status: str
    error: str | None = None
    duration_ms: int
    investigation_id: int | None = None
    round_number: int | None = None
    query_sequence: int | None = None
    created_at: datetime


class KnowledgeModelInvocationOut(BaseModel):
    """单次模型调用可观测记录。"""

    id: int
    purpose: str
    prompt_version: str
    provider: str
    model: str | None = None
    is_fallback: bool = False
    error: str | None = None
    duration_ms: int
    usage: dict | None = None
    investigation_id: int | None = None
    round_number: int | None = None
    query_sequence: int | None = None
    created_at: datetime


class KnowledgeRunObservabilityOut(BaseModel):
    """Run 的分阶段可排障记录。"""

    run_id: int
    tool_calls: list[KnowledgeToolCallOut] = []
    model_invocations: list[KnowledgeModelInvocationOut] = []


class KnowledgeInvestigationRoundOut(BaseModel):
    """一轮调查的审计详情：观察摘要、增量计数与控制器调用归属。"""

    id: int
    round_number: int
    status: str
    controller_action: str | None = None
    coverage: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []
    reason: str | None = None
    queries_planned: int = 0
    queries_executed: int = 0
    entries_added: int = 0
    evidence_added: int = 0
    provider: str | None = None
    model: str | None = None
    is_fallback: bool = False
    error: str | None = None
    duration_ms: int = 0
    created_at: datetime


class KnowledgeInvestigationQueryOut(BaseModel):
    """轮次内一条查询的审计详情。"""

    id: int
    round_number: int
    sequence: int
    original_query: str
    normalized_query_hash: str
    status: str
    result_counts: dict | None = None
    created_at: datetime


class KnowledgeInvestigationDetailOut(BaseModel):
    """按 Run 读取的逐轮调查详情（只读、分页/长度受限）。"""

    investigation_id: int
    run_id: int
    status: str
    objective: str
    requested_answer_mode: AnswerMode
    actual_answer_mode: AnswerMode | None = None
    max_rounds: int
    max_queries_per_round: int
    max_total_queries: int
    max_entries: int
    max_evidence: int
    current_round: int = 0
    total_queries_executed: int = 0
    distinct_entries_found: int = 0
    citable_evidence_count: int = 0
    stop_reason: InvestigationStopReason | None = None
    coverage: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []
    rounds: list[KnowledgeInvestigationRoundOut] = []
    queries: list[KnowledgeInvestigationQueryOut] = []
