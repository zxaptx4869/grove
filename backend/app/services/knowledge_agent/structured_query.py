"""一次结构化查询计划的服务端规范化、硬校验与可恢复固化。

模型输出始终只是候选。本模块不接受任何 Workspace、项目、目录或对象标识，
也不执行查询；可信范围只在后续 dispatcher 中从 RunToolContext 注入。
"""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.structured_query import (
    STRUCTURED_QUERY_PLAN_PROMPT_VERSION,
    StructuredQueryPlanDraft,
    run_structured_query_planner,
)
from app.core.config import Settings, get_settings
from app.models.knowledge_agent import PURPOSE_STRUCTURED_QUERY_PLAN
from app.services.knowledge_agent.observability import record_model_invocation

_MAIN_TYPE_ORDER = ("knowledge", "method", "parameter", "reminder")
_INFO_NATURE_ORDER = (
    "fact",
    "experience",
    "advice",
    "speculation",
    "other",
    "unspecified",
)
_OUTPUT_ORDER = {"count": 0, "group_count": 1, "entries": 2}


class StructuredQueryPlanError(ValueError):
    """候选计划无法在不改变语义的前提下安全执行。"""


class StrictNormalizedModel(BaseModel):
    """规范化快照同样拒绝未知字段，防止历史 JSON 被扩大解释。"""

    model_config = ConfigDict(extra="forbid")


class NormalizedUpdatedAtRange(StrictNormalizedModel):
    """统一转换为 UTC 的闭开时间区间。"""

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


class NormalizedEntrySetSpec(StrictNormalizedModel):
    """不含授权范围的 EntrySetSpec v1 可执行参数。"""

    schema_version: Literal["v1"] = "v1"
    semantic_query: str | None = None
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] = []
    info_natures: list[
        Literal[
            "fact",
            "experience",
            "advice",
            "speculation",
            "other",
            "unspecified",
        ]
    ] = []
    updated_at: NormalizedUpdatedAtRange | None = None


class NormalizedEntrySort(StrictNormalizedModel):
    """服务端允许的排序；执行器始终追加 Entry id tie-breaker。"""

    field: Literal["relevance", "updated_at", "created_at"]
    direction: Literal["asc", "desc"]


class NormalizedEntriesOutput(StrictNormalizedModel):
    kind: Literal["entries"] = "entries"
    limit: int
    sort: NormalizedEntrySort


class NormalizedCountOutput(StrictNormalizedModel):
    kind: Literal["count"] = "count"


class NormalizedGroupCountOutput(StrictNormalizedModel):
    kind: Literal["group_count"] = "group_count"
    group_by: Literal["main_type", "info_nature", "updated_month"]


NormalizedStructuredQueryOutput = Annotated[
    NormalizedEntriesOutput | NormalizedCountOutput | NormalizedGroupCountOutput,
    Field(discriminator="kind"),
]


class NormalizedStructuredQueryPlan(StrictNormalizedModel):
    """持久化并执行的 StructuredQueryPlan v1；不保存原始模型输出。"""

    schema_version: Literal["v1"] = "v1"
    prompt_version: Literal["v1"] = STRUCTURED_QUERY_PLAN_PROMPT_VERSION
    entry_set: NormalizedEntrySetSpec
    outputs: list[NormalizedStructuredQueryOutput]


def _utc_bound(value: datetime | None, field_name: str) -> datetime | None:
    """拒绝无时区时间，并统一转为 UTC。"""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise StructuredQueryPlanError(f"{field_name} 必须包含时区")
    return value.astimezone(UTC)


def _normalize_enum_list(values: list[str], order: tuple[str, ...]) -> list[str]:
    """去重并按服务端稳定枚举顺序规范化。"""
    selected = set(values)
    return [value for value in order if value in selected]


def normalize_structured_query_plan(
    candidate: StructuredQueryPlanDraft | dict,
    *,
    settings: Settings | None = None,
) -> NormalizedStructuredQueryPlan:
    """严格校验并规范化模型候选；任何未知/越权/矛盾语义整体拒绝。"""
    active_settings = settings or get_settings()
    try:
        draft = (
            candidate
            if isinstance(candidate, StructuredQueryPlanDraft)
            else StructuredQueryPlanDraft.model_validate(candidate)
        )
    except ValidationError as exc:
        raise StructuredQueryPlanError(f"计划 schema 非法：{exc}") from exc

    semantic_query = (
        " ".join(draft.entry_set.semantic_query.split())
        if draft.entry_set.semantic_query
        else None
    )
    if semantic_query == "":
        semantic_query = None
    start = _utc_bound(
        draft.entry_set.updated_at.from_ if draft.entry_set.updated_at else None,
        "updated_at.from",
    )
    end = _utc_bound(
        draft.entry_set.updated_at.to if draft.entry_set.updated_at else None,
        "updated_at.to",
    )
    if start is not None and end is not None and start >= end:
        raise StructuredQueryPlanError("updated_at 必须满足 from < to 的闭开区间")
    updated_at = None
    if start is not None or end is not None:
        updated_at = NormalizedUpdatedAtRange.model_validate(
            {"from": start, "to": end}
        )

    if len(draft.outputs) > active_settings.knowledge_agent_structured_query_max_outputs:
        raise StructuredQueryPlanError("计划输出数超过服务端预算")
    seen_kinds: set[str] = set()
    normalized_outputs: list[NormalizedStructuredQueryOutput] = []
    for output in draft.outputs:
        if output.kind in seen_kinds:
            raise StructuredQueryPlanError(f"输出 {output.kind} 不得重复")
        seen_kinds.add(output.kind)
        if output.kind == "entries":
            if output.limit > active_settings.knowledge_agent_structured_query_entry_limit:
                raise StructuredQueryPlanError("entries.limit 超过服务端预算")
            if output.sort.field == "relevance" and semantic_query is None:
                raise StructuredQueryPlanError("无 semantic_query 时不得按 relevance 排序")
            normalized_outputs.append(
                NormalizedEntriesOutput(
                    limit=output.limit,
                    sort=NormalizedEntrySort(
                        field=output.sort.field,
                        direction=output.sort.direction,
                    ),
                )
            )
        elif output.kind == "group_count":
            normalized_outputs.append(
                NormalizedGroupCountOutput(group_by=output.group_by)
            )
        else:
            normalized_outputs.append(NormalizedCountOutput())
    normalized_outputs.sort(key=lambda item: _OUTPUT_ORDER[item.kind])
    if len(normalized_outputs) > active_settings.knowledge_agent_structured_query_max_tool_calls:
        raise StructuredQueryPlanError("计划工具调用数超过服务端预算")

    plan = NormalizedStructuredQueryPlan(
        entry_set=NormalizedEntrySetSpec(
            semantic_query=semantic_query,
            main_types=_normalize_enum_list(
                list(draft.entry_set.main_types), _MAIN_TYPE_ORDER
            ),
            info_natures=_normalize_enum_list(
                list(draft.entry_set.info_natures), _INFO_NATURE_ORDER
            ),
            updated_at=updated_at,
        ),
        outputs=normalized_outputs,
    )
    raw = plan.model_dump_json(by_alias=True)
    if (
        len(raw.encode("utf-8"))
        > active_settings.knowledge_agent_structured_query_plan_bytes_limit
    ):
        raise StructuredQueryPlanError("规范化计划超过 JSON 字节预算")
    return plan


def restore_structured_query_plan(
    raw: str | None,
    *,
    settings: Settings | None = None,
) -> NormalizedStructuredQueryPlan | None:
    """恢复已固化计划；旧 Run 为空，非法历史快照不猜测也不执行。"""
    if raw is None:
        return None
    active_settings = settings or get_settings()
    if (
        len(raw.encode("utf-8"))
        > active_settings.knowledge_agent_structured_query_plan_bytes_limit
    ):
        raise StructuredQueryPlanError("已固化计划超过 JSON 字节预算")
    try:
        return NormalizedStructuredQueryPlan.model_validate_json(raw)
    except ValidationError as exc:
        raise StructuredQueryPlanError(f"已固化计划非法：{exc}") from exc


def persist_structured_query_plan(
    run,
    plan: NormalizedStructuredQueryPlan,
    *,
    settings: Settings | None = None,
) -> NormalizedStructuredQueryPlan:
    """首次写入规范化计划；已有计划只允许原样复用，禁止覆盖。"""
    existing = restore_structured_query_plan(
        run.structured_query_plan_json,
        settings=settings,
    )
    if existing is not None:
        return existing
    run.structured_query_plan_json = plan.model_dump_json(by_alias=True)
    return plan


async def plan_and_persist_structured_query(
    db,
    run,
    *,
    objective: str,
    scope_label: str,
    cancel_check=None,
) -> NormalizedStructuredQueryPlan | None:
    """复用已有计划或调用一次规划器，并在任何工具执行前提交合法快照。"""
    existing = restore_structured_query_plan(run.structured_query_plan_json)
    if existing is not None:
        return existing

    candidate, meta = await run_structured_query_planner(
        db,
        run.workspace_id,
        objective=objective,
        scope_label=scope_label,
    )
    plan = None
    if candidate is not None:
        try:
            plan = normalize_structured_query_plan(candidate)
        except StructuredQueryPlanError as exc:
            meta = replace(
                meta,
                is_fallback=True,
                error=f"结构化查询计划校验失败：{exc}",
            )
    # 规划期间若已取消，迟到计划与调用结果都不得提交
    if cancel_check is not None:
        await cancel_check()
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=meta,
        prompt_version=STRUCTURED_QUERY_PLAN_PROMPT_VERSION,
    )
    if plan is not None:
        persist_structured_query_plan(run, plan)
    await db.commit()
    return plan


def normalized_plan_summary(plan: NormalizedStructuredQueryPlan) -> dict:
    """返回有界、无范围 ID 的计划摘要，供 API/审计复用。"""
    return json.loads(plan.model_dump_json(by_alias=True))


assert PURPOSE_STRUCTURED_QUERY_PLAN == "structured_query_plan"
