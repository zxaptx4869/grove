"""知识 Agent 一次结构化查询规划器的闭合候选协议。

这里的模型只描述 AI 可以提出的候选计划，不包含 owner、Workspace、项目、
目录、Entry id、数据库会话或任意表达式。服务端会在执行前再次严格校验、
规范化并注入 Run 固化范围；模型输出本身不具有授权或执行效力。
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MainType = Literal["knowledge", "method", "parameter", "reminder"]
InfoNature = Literal[
    "fact",
    "experience",
    "advice",
    "speculation",
    "other",
    "unspecified",
]
SortField = Literal["relevance", "updated_at", "created_at"]
SortDirection = Literal["asc", "desc"]
GroupField = Literal["main_type", "info_nature", "updated_month"]


class StrictQueryModel(BaseModel):
    """所有模型可控查询类型都拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class UpdatedAtRangeDraft(StrictQueryModel):
    """UTC 更新时间闭开区间候选；时区与先后关系由服务端硬校验。"""

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


class EntrySetSpecDraft(StrictQueryModel):
    """EntrySetSpec v1：仅表达允许的正式知识集合条件。"""

    schema_version: Literal["v1"] = "v1"
    semantic_query: str | None = Field(default=None, min_length=1, max_length=500)
    main_types: list[MainType] = Field(default_factory=list, max_length=4)
    info_natures: list[InfoNature] = Field(default_factory=list, max_length=6)
    updated_at: UpdatedAtRangeDraft | None = None


class EntrySortDraft(StrictQueryModel):
    """白名单排序；稳定 id tie-breaker 由服务端追加。"""

    field: SortField = "updated_at"
    direction: SortDirection = "desc"


class EntriesOutputDraft(StrictQueryModel):
    """有界 Entry 快照输出候选。"""

    kind: Literal["entries"] = "entries"
    limit: int = Field(default=6, ge=1, le=100)
    sort: EntrySortDraft = Field(default_factory=EntrySortDraft)


class CountOutputDraft(StrictQueryModel):
    """共享集合计数输出候选。"""

    kind: Literal["count"] = "count"


class GroupCountOutputDraft(StrictQueryModel):
    """共享集合受限分组计数输出候选。"""

    kind: Literal["group_count"] = "group_count"
    group_by: GroupField


StructuredQueryOutputDraft = Annotated[
    EntriesOutputDraft | CountOutputDraft | GroupCountOutputDraft,
    Field(discriminator="kind"),
]


class StructuredQueryPlanDraft(StrictQueryModel):
    """StructuredQueryPlan v1：一次生成、固定集合、固定输出。"""

    schema_version: Literal["v1"] = "v1"
    entry_set: EntrySetSpecDraft = Field(default_factory=EntrySetSpecDraft)
    outputs: list[StructuredQueryOutputDraft] = Field(min_length=1, max_length=3)
    reason: str = Field(default="", max_length=300)
