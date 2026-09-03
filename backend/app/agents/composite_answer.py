"""知识 Agent quick 复合回答规划器的闭合候选协议。

本模块中的类型只描述模型可以提出的候选回答义务和只读输入请求，不包含
owner、Workspace、项目、目录或知识对象标识。服务端规范化结果才可执行。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.structured_query import EntrySetSpecDraft, StructuredQueryOutputDraft

COMPOSITE_ANSWER_PLAN_PROMPT_VERSION = "v1"

CompositeRequirementKind = Literal[
    "explain",
    "retrieve",
    "aggregate",
    "compare",
    "recommend",
    "other",
]
CompositeBasisPolicy = Literal[
    "grove_only",
    "grove_required",
    "model_allowed",
    "external_required",
]


class StrictCompositeDraft(BaseModel):
    """所有模型可控复合规划类型都拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class CompositeRequirementDraft(StrictCompositeDraft):
    """一个待回答义务，不直接等同于工具调用。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    order: int = Field(ge=0, le=99)
    summary: str = Field(min_length=1, max_length=300)
    kind: CompositeRequirementKind
    basis_policy: CompositeBasisPolicy


class CompositeRetrievalRequestDraft(StrictCompositeDraft):
    """有界 Grove 语义检索输入候选。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=500)
    requirement_ids: list[str] = Field(min_length=1, max_length=8)


class CompositeStructuredRequestDraft(StrictCompositeDraft):
    """复用 B1 EntrySetSpec 与输出的结构化输入候选。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    entry_set: EntrySetSpecDraft = Field(default_factory=EntrySetSpecDraft)
    outputs: list[StructuredQueryOutputDraft] = Field(min_length=1, max_length=3)
    requirement_ids: list[str] = Field(min_length=1, max_length=8)


class CompositeAnswerPlanDraft(StrictCompositeDraft):
    """CompositeAnswerPlan v1 模型候选；应用层会再次严格校验。"""

    schema_version: Literal["v1"] = "v1"
    requirements: list[CompositeRequirementDraft] = Field(min_length=1, max_length=8)
    statement_message_ids: list[int] = Field(default_factory=list, max_length=6)
    retrieval_requests: list[CompositeRetrievalRequestDraft] = Field(
        default_factory=list,
        max_length=3,
    )
    structured_requests: list[CompositeStructuredRequestDraft] = Field(
        default_factory=list,
        max_length=2,
    )
    reason: str = Field(default="", max_length=300)
