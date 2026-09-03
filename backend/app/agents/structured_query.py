"""知识 Agent 一次结构化查询规划器的闭合候选协议。

这里的模型只描述 AI 可以提出的候选计划，不包含 owner、Workspace、项目、
目录、Entry id、数据库会话或任意表达式。服务端会在执行前再次严格校验、
规范化并注入 Run 固化范围；模型输出本身不具有授权或执行效力。
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.config import get_settings
from app.models.knowledge_agent import PURPOSE_STRUCTURED_QUERY_PLAN
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

STRUCTURED_QUERY_PLAN_PROMPT_VERSION = "v1"

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


STRUCTURED_QUERY_PLAN_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的一次结构化查询规划器。你只生成候选计划，不执行查询，"
    "也不回答问题。服务端会严格校验并注入真正的 owner、Workspace 与可选项目范围。"
    "\n"
    "允许的 EntrySetSpec v1 条件只有：可选 semantic_query、main_types、info_natures、"
    "UTC updated_at 闭开区间 [from,to)。不要输出 Workspace/项目/目录/Entry/Source id，"
    "不要输出 SQL、字段名表达式、正则、任意运算符或写操作。"
    "\n"
    "允许的输出只有：entries（有界列表）、count（集合计数）、group_count（按 main_type、"
    "info_nature 或 updated_month 分组）。每种输出最多一次，最多三个输出。"
    "entries 只允许 relevance、updated_at、created_at 排序；没有 semantic_query 时禁止"
    " relevance。"
    "\n"
    "需要主题相关性时使用 semantic_query；它只形成有界相关集合，后续统计不能视为"
    "授权范围内的精确全集。纯类型/性质/时间筛选可以不使用 semantic_query。"
    "\n"
    "自然语言日期必须根据输入给出的当前 UTC 时间换算成带时区的 ISO 8601 闭开区间。"
    "只读查询中夹带修改意图时仍只能生成允许的只读查询，不能生成修改工具或写入字段。"
)


def _model_name(text_model) -> str:
    """从 Provider 模型对象提取可观测模型名。"""
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


async def run_structured_query_planner(
    db,
    workspace_id: int,
    *,
    objective: str,
    scope_label: str,
    now: datetime | None = None,
) -> tuple[StructuredQueryPlanDraft | None, StageMeta]:
    """运行一次结构化查询规划，失败时返回显式 fallback，不伪造计划。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            None,
            StageMeta(
                purpose=PURPOSE_STRUCTURED_QUERY_PLAN,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    context = "\n".join(
        [
            f"独立问题：{objective}",
            f"可信范围：{scope_label}",
            f"当前 UTC 时间：{current.astimezone(UTC).isoformat()}",
            "请输出 StructuredQueryPlan v1。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=StructuredQueryPlanDraft,
        system_prompt=STRUCTURED_QUERY_PLAN_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_structured_query_planner_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("结构化查询规划模型调用失败：%s", exc)
        return (
            None,
            StageMeta(
                purpose=PURPOSE_STRUCTURED_QUERY_PLAN,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    usage = asdict(result.usage)
    if result.output is None:
        return (
            None,
            StageMeta(
                purpose=PURPOSE_STRUCTURED_QUERY_PLAN,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
                usage=usage,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_STRUCTURED_QUERY_PLAN,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
            usage=usage,
        ),
    )
