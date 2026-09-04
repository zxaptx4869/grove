"""一次结构化查询计划的共享集合与固定顺序执行器。"""

import json
from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RUN_COMPLETED,
    RUN_PARTIAL,
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_PARTIAL,
)
from app.services.knowledge_agent.read_tools import (
    CancelCheck,
    ReadToolBudget,
    dispatch_read_tool,
)
from app.services.knowledge_agent.structured_query import NormalizedStructuredQueryPlan
from app.services.knowledge_agent.structured_query_tools import (
    STRUCTURED_QUERY_TOOL_REGISTRY,
    STRUCTURED_QUERY_TOOL_VERSION,
)
from app.services.knowledge_agent.tools import RunToolContext


@dataclass(frozen=True)
class StructuredQueryExecutionResult:
    """可直接映射到 v2 快照的确定性执行结果。"""

    status: str
    set_completeness: str
    entries: dict | None
    count: dict | None
    group_counts: list[dict]
    output_completeness: dict
    warnings: list[str]


def _payload_dict(result: StructuredQueryExecutionResult) -> dict:
    return {
        "status": result.status,
        "set_completeness": result.set_completeness,
        "entries": result.entries,
        "count": result.count,
        "group_counts": result.group_counts,
        "output_completeness": result.output_completeness,
        "warnings": result.warnings,
    }


def apply_execution_byte_budget(
    result: StructuredQueryExecutionResult,
    *,
    max_bytes: int,
) -> StructuredQueryExecutionResult:
    """总结果超限时先缩列表、再缩桶，并只降低受影响输出完整性。"""
    payload = deepcopy(_payload_dict(result))
    warnings = list(payload["warnings"])

    def size() -> int:
        return len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    entries = payload.get("entries")
    entry_items = entries.get("items", []) if isinstance(entries, dict) else []
    entry_truncated = False
    while entry_items and size() > max_bytes:
        entry_items.pop()
        entry_truncated = True
    if entry_truncated and isinstance(entries, dict):
        entries["returned_count"] = len(entry_items)
        entries["has_more"] = True
        entries["completeness"] = RESULT_COMPLETENESS_LIMITED
        payload["output_completeness"]["entries"] = RESULT_COMPLETENESS_LIMITED
        warnings.append("Entry 列表达到结果字节上限，已截断展示快照")

    group_truncated = False
    for group in reversed(payload["group_counts"]):
        buckets = group.get("buckets", [])
        while buckets and size() > max_bytes:
            buckets.pop()
            group_truncated = True
            group["truncated"] = True
            group["completeness"] = RESULT_COMPLETENESS_LIMITED
            payload["output_completeness"]["group_count"][
                group["group_by"]
            ] = RESULT_COMPLETENESS_LIMITED
    if group_truncated:
        warnings.append("分组桶达到结果字节上限，已截断")
    payload["warnings"] = list(dict.fromkeys(warnings))
    return StructuredQueryExecutionResult(
        status=payload["status"],
        set_completeness=payload["set_completeness"],
        entries=payload["entries"],
        count=payload["count"],
        group_counts=payload["group_counts"],
        output_completeness=payload["output_completeness"],
        warnings=payload["warnings"],
    )


async def execute_structured_query_plan(
    db: AsyncSession,
    ctx: RunToolContext,
    plan: NormalizedStructuredQueryPlan,
    *,
    cancel_check: CancelCheck,
    settings: Settings | None = None,
) -> StructuredQueryExecutionResult:
    """对同一集合按 count → group_count → entries 固定顺序确定性执行。"""
    settings = settings or get_settings()
    semantic = plan.entry_set.semantic_query is not None
    set_completeness = (
        RESULT_COMPLETENESS_LIMITED if semantic else RESULT_COMPLETENESS_COMPLETE
    )
    budget = ReadToolBudget(
        max_calls=settings.knowledge_agent_structured_query_max_tool_calls,
        timeout_seconds=settings.knowledge_agent_structured_query_execution_timeout_seconds,
        max_result_bytes=settings.knowledge_agent_structured_query_result_json_bytes_limit,
    )
    entries_result = None
    count_result = None
    group_results: list[dict] = []
    output_completeness: dict = {
        "entries": None,
        "count": None,
        "group_count": {},
    }
    warnings: list[str] = []
    affected = False
    for output in plan.outputs:
        await cancel_check()
        if output.kind == "entries":
            tool_name = "query_entries"
            params = {
                "entry_set": plan.entry_set.model_dump(mode="json", by_alias=True),
                "limit": output.limit,
                "sort": output.sort.model_dump(mode="json"),
            }
        else:
            tool_name = "aggregate_entries"
            params = {
                "entry_set": plan.entry_set.model_dump(mode="json", by_alias=True),
                "operation": output.kind,
            }
            if output.kind == "group_count":
                params["group_by"] = output.group_by
        dispatched = await dispatch_read_tool(
            db,
            ctx,
            tool_name=tool_name,
            tool_version=STRUCTURED_QUERY_TOOL_VERSION,
            params=params,
            budget=budget,
            cancel_check=cancel_check,
            registry=STRUCTURED_QUERY_TOOL_REGISTRY,
        )
        # 每个成功只读调用单独形成恢复检查点；最终 v2 快照仍在终态原子提交
        await db.commit()
        await cancel_check()
        if dispatched.status in {TOOL_PARTIAL, TOOL_DENIED, TOOL_ERROR}:
            affected = True
        if dispatched.error:
            warnings.append(dispatched.error)
        if output.kind == "entries":
            entries_result = {
                **dispatched.payload,
                "status": dispatched.status,
                "completeness": dispatched.completeness,
                "sort": output.sort.model_dump(mode="json"),
            }
            output_completeness["entries"] = dispatched.completeness
        elif output.kind == "count":
            count_result = {
                **dispatched.payload,
                "status": dispatched.status,
                "completeness": dispatched.completeness,
            }
            output_completeness["count"] = dispatched.completeness
        else:
            group_results.append(
                {
                    **dispatched.payload,
                    "status": dispatched.status,
                    "completeness": dispatched.completeness,
                }
            )
            output_completeness["group_count"][output.group_by] = (
                dispatched.completeness
            )

    result = StructuredQueryExecutionResult(
        status=RUN_PARTIAL if affected else RUN_COMPLETED,
        set_completeness=set_completeness,
        entries=entries_result,
        count=count_result,
        group_counts=group_results,
        output_completeness=output_completeness,
        warnings=list(dict.fromkeys(warnings)),
    )
    return apply_execution_byte_budget(
        result,
        max_bytes=settings.knowledge_agent_structured_query_result_json_bytes_limit,
    )
