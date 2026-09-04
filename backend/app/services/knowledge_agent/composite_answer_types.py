"""quick 复合回答的有界执行检查点、工具事实与逐项覆盖类型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictCompositeSnapshot(BaseModel):
    """持久化快照拒绝未知字段，避免恢复时扩大历史语义。"""

    model_config = ConfigDict(extra="forbid")


class CompositeExecutionInputSnapshot(StrictCompositeSnapshot):
    """一个计划内只读输入请求的可恢复检查点。"""

    request_id: str = Field(min_length=1, max_length=32)
    kind: Literal["retrieval", "structured"]
    requirement_ids: list[str] = Field(min_length=1, max_length=8)
    fingerprint: str = Field(min_length=1, max_length=64)
    status: Literal[
        "completed",
        "empty",
        "limited",
        "partial",
        "denied",
        "error",
        "cancelled",
    ]
    completeness: Literal["complete", "limited", "unknown"] = "unknown"
    entry_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence_handles: list[str] = Field(default_factory=list, max_length=100)
    result_handles: list[str] = Field(default_factory=list, max_length=16)
    error: str | None = Field(default=None, max_length=500)


class CompositeToolFact(StrictCompositeSnapshot):
    """由服务端结构化结果派生、不可交给模型改写的事实。"""

    handle: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=32)
    requirement_ids: list[str] = Field(min_length=1, max_length=8)
    kind: Literal["count", "group_count", "entries"]
    text: str = Field(min_length=1, max_length=2000)
    completeness: Literal["complete", "limited", "unknown"]
    summary: dict[str, object] = Field(default_factory=dict)


class CompositeAnswerExecutionSnapshot(StrictCompositeSnapshot):
    """CompositeAnswerExecution v1：只保存有界输入结果和工具事实。"""

    schema_version: Literal["v1"] = "v1"
    elapsed_ms: int = Field(default=0, ge=0, le=600_000)
    # 首次最多 5 份请求，一次补查最多追加 2 份。
    inputs: list[CompositeExecutionInputSnapshot] = Field(default_factory=list, max_length=7)
    tool_facts: list[CompositeToolFact] = Field(default_factory=list, max_length=16)


class CompositeRequirementCoverageSnapshot(StrictCompositeSnapshot):
    """一个回答义务的服务端终态覆盖。"""

    requirement_id: str = Field(min_length=1, max_length=32)
    status: Literal["answered", "partial", "insufficient", "failed"]
    evidence_handles: list[str] = Field(default_factory=list, max_length=100)
    result_handles: list[str] = Field(default_factory=list, max_length=16)
    user_message_ids: list[int] = Field(default_factory=list, max_length=8)
    model_knowledge_used: bool = False
    note: str | None = Field(default=None, max_length=500)


class CompositeAnswerCoverageSnapshot(StrictCompositeSnapshot):
    """CompositeAnswerCoverage v1：覆盖状态只由服务端合法结果派生。"""

    schema_version: Literal["v1"] = "v1"
    requirements: list[CompositeRequirementCoverageSnapshot] = Field(
        min_length=1,
        max_length=20,
    )
