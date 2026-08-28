"""知识 Agent 对话、Run、可观测记录与回答响应模型。

契约约束：API 不返回原始 prompt、模型敏感输入或整份 Attachment；
工具参数与结果只暴露脱敏摘要；引用只暴露服务端核验过的 Evidence 原文片段。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

KnowledgeScopeType = Literal["workspace", "project"]

RunStatus = Literal[
    "waiting",
    "processing",
    "completed",
    "partial",
    "failed",
    "cancelled",
]

AnswerStatus = Literal[
    "completed",
    "partial",
    "insufficient",
    "failed",
    "clarification",
]
ContextMode = Literal["auto", "continue", "new_topic"]
ContextDecision = Literal["continue", "new_topic", "clarify"]


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
    input_context_version_id: int | None = None
    output_context_version_id: int | None = None
    created_at: datetime


class KnowledgeMessagePageOut(BaseModel):
    """游标分页的消息页。"""

    items: list[KnowledgeMessageOut]
    next_cursor: str | None = None


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


class KnowledgeConflictOut(BaseModel):
    """由不同有效 Evidence 支持的冲突展示。"""

    summary: str
    evidence_id_a: int
    entry_id_a: int
    entry_title_a: str
    evidence_id_b: int
    entry_id_b: int
    entry_title_b: str


class KnowledgeAnswerOut(BaseModel):
    """结构化回答：引用只能来自本 Run 的 Evidence 句柄。"""

    answer: str
    status: AnswerStatus
    insufficient_note: str | None = None
    citations: list[KnowledgeRunCitationOut] = []
    conflicts: list[KnowledgeConflictOut] = []


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


class KnowledgeRunOut(BaseModel):
    """一次持久化只读 Run 的查询结果。"""

    id: int
    conversation_id: int
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
    input_context_version_id: int | None = None
    output_context_version_id: int | None = None
    context_degraded: bool = False
    fallback_summary: FallbackSummaryOut | None = None
    answer: KnowledgeAnswerOut | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeRunSubmitRequest(BaseModel):
    """提交新问题：client_message_id 用于网络重试幂等；context_mode 默认 auto。"""

    client_message_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    context_mode: ContextMode = "auto"


class KnowledgeRunSubmitOut(BaseModel):
    """消息提交结果：立即返回等待中的 Run，客户端轮询恢复。"""

    user_message: KnowledgeMessageOut
    run: KnowledgeRunOut


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
    created_at: datetime


class KnowledgeRunObservabilityOut(BaseModel):
    """Run 的分阶段可排障记录。"""

    run_id: int
    tool_calls: list[KnowledgeToolCallOut] = []
    model_invocations: list[KnowledgeModelInvocationOut] = []
