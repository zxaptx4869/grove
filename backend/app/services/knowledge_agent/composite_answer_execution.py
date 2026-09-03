"""quick 复合回答计划的固定顺序只读执行器。"""

import hashlib
import json
from dataclasses import dataclass
from time import monotonic, perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge_agent import ANSWER_PROMPT_VERSION
from app.core.config import Settings, get_settings
from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    RUN_COMPLETED,
)
from app.services.knowledge_agent.composite_answer import (
    NormalizedCompositeAnswerPlan,
    NormalizedCompositeRetrievalRequest,
    NormalizedCompositeStructuredRequest,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.observability import (
    StageMeta,
    record_model_invocation,
)
from app.services.knowledge_agent.structured_query_execution import (
    StructuredQueryExecutionResult,
    execute_structured_query_plan,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    record_tool_result,
    search_confirmed_knowledge,
)

COMPOSITE_EXECUTION_VERSION = "v1"


@dataclass(frozen=True)
class CompositeExecutionArtifacts:
    """固定执行结束后的有界快照；回答上下文从快照句柄重新装配。"""

    snapshot: CompositeAnswerExecutionSnapshot


def composite_request_fingerprint(
    run_id: int,
    plan: NormalizedCompositeAnswerPlan,
    *,
    request_id: str,
    kind: str,
    params: dict,
) -> str:
    """生成绑定 Run、计划版本、请求身份和规范化参数的稳定指纹。"""
    raw = json.dumps(
        {
            "run_id": run_id,
            "execution_version": COMPOSITE_EXECUTION_VERSION,
            "plan_schema_version": plan.schema_version,
            "plan_prompt_version": plan.prompt_version,
            "request_id": request_id,
            "kind": kind,
            "params": params,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def restore_composite_execution(
    raw: str | None,
    *,
    settings: Settings | None = None,
) -> CompositeAnswerExecutionSnapshot:
    """恢复已提交检查点；空快照使用 v1 初始值，非法快照直接失败。"""
    if raw is None:
        return CompositeAnswerExecutionSnapshot()
    active_settings = settings or get_settings()
    if (
        len(raw.encode("utf-8"))
        > active_settings.knowledge_agent_composite_answer_execution_bytes_limit
    ):
        raise ValueError("复合回答执行快照超过 JSON 字节预算")
    return CompositeAnswerExecutionSnapshot.model_validate_json(raw)


def _bounded_snapshot(
    snapshot: CompositeAnswerExecutionSnapshot,
    *,
    settings: Settings,
) -> CompositeAnswerExecutionSnapshot:
    """保证检查点可写入 TEXT；按尾部优先缩减展示性对象句柄。"""
    payload = snapshot.model_copy(deep=True)
    limit = settings.knowledge_agent_composite_answer_execution_bytes_limit
    while len(payload.model_dump_json().encode("utf-8")) > limit:
        changed = False
        for item in reversed(payload.inputs):
            if item.entry_ids:
                item.entry_ids.pop()
                item.status = "limited"
                item.completeness = RESULT_COMPLETENESS_LIMITED
                item.error = item.error or "执行快照达到 JSON 字节预算"
                changed = True
                break
            if item.evidence_handles:
                item.evidence_handles.pop()
                item.status = "limited"
                item.completeness = RESULT_COMPLETENESS_LIMITED
                item.error = item.error or "执行快照达到 JSON 字节预算"
                changed = True
                break
        if not changed:
            raise ValueError("复合回答执行快照无法压缩到 JSON 字节预算")
    return payload


async def _persist_checkpoint(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    snapshot: CompositeAnswerExecutionSnapshot,
    *,
    settings: Settings,
) -> CompositeAnswerExecutionSnapshot:
    bounded = _bounded_snapshot(snapshot, settings=settings)
    run.composite_answer_execution_json = bounded.model_dump_json()
    await db.commit()
    return bounded


def _result_handle(fingerprint: str, output_key: str) -> str:
    raw = hashlib.sha256(f"{fingerprint}:{output_key}".encode()).hexdigest()[:24]
    return f"res_{raw}"


def _group_label(value: str) -> str:
    return {
        "main_type": "知识类型",
        "info_nature": "信息性质",
        "updated_month": "更新月份",
    }.get(value, value)


def structured_result_tool_facts(
    request: NormalizedCompositeStructuredRequest,
    result: StructuredQueryExecutionResult,
    *,
    fingerprint: str,
) -> list[CompositeToolFact]:
    """把 B1 输出变成稳定服务端事实；完整性决定是否允许全集措辞。"""
    facts: list[CompositeToolFact] = []
    if result.count is not None:
        completeness = result.count.get("completeness", RESULT_COMPLETENESS_UNKNOWN)
        value = int(result.count.get("value", 0))
        text = (
            f"符合条件的知识条目共 {value} 条。"
            if completeness == RESULT_COMPLETENESS_COMPLETE
            else f"本次匹配中可确认 {value} 条；结果受语义检索或预算限制，不代表完整总数。"
        )
        facts.append(
            CompositeToolFact(
                handle=_result_handle(fingerprint, "count"),
                request_id=request.id,
                requirement_ids=request.requirement_ids,
                kind="count",
                text=text,
                completeness=completeness,
                summary={"value": value},
            )
        )
    for group in result.group_counts:
        group_by = str(group.get("group_by", ""))
        completeness = group.get("completeness", RESULT_COMPLETENESS_UNKNOWN)
        buckets = list(group.get("buckets", []))
        rendered = "、".join(
            f"{item.get('key')} {int(item.get('count', 0))} 条" for item in buckets
        ) or "没有可确认分组"
        suffix = "。" if completeness == RESULT_COMPLETENESS_COMPLETE else "；仅代表本次有限结果。"
        facts.append(
            CompositeToolFact(
                handle=_result_handle(fingerprint, f"group_count:{group_by}"),
                request_id=request.id,
                requirement_ids=request.requirement_ids,
                kind="group_count",
                text=f"按{_group_label(group_by)}统计：{rendered}{suffix}",
                completeness=completeness,
                summary={"group_by": group_by, "buckets": buckets},
            )
        )
    if result.entries is not None:
        completeness = result.entries.get("completeness", RESULT_COMPLETENESS_UNKNOWN)
        items = list(result.entries.get("items", []))
        count = len(items)
        suffix = (
            "。"
            if completeness == RESULT_COMPLETENESS_COMPLETE
            else "；列表受 top-k 或预算限制，不代表完整集合。"
        )
        facts.append(
            CompositeToolFact(
                handle=_result_handle(fingerprint, "entries"),
                request_id=request.id,
                requirement_ids=request.requirement_ids,
                kind="entries",
                text=f"本次返回 {count} 条匹配知识条目{suffix}",
                completeness=completeness,
                summary={
                    "returned_count": count,
                    "entry_ids": [item.get("entry_id") for item in items],
                    "has_more": bool(result.entries.get("has_more")),
                },
            )
        )
    return facts


async def _execute_retrieval(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    ctx: RunToolContext,
    plan: NormalizedCompositeAnswerPlan,
    request: NormalizedCompositeRetrievalRequest,
    *,
    remaining_entries: int,
    remaining_evidence: int,
    cancel_check,
    settings: Settings,
) -> CompositeExecutionInputSnapshot:
    fingerprint_params = {
        "query": request.query,
        "requirement_ids": request.requirement_ids,
        "max_entries": settings.knowledge_agent_composite_answer_max_entries,
        "max_evidence": settings.knowledge_agent_composite_answer_max_evidence,
    }
    fingerprint = composite_request_fingerprint(
        run.id,
        plan,
        request_id=request.id,
        kind="retrieval",
        params=fingerprint_params,
    )
    if remaining_entries <= 0 or remaining_evidence <= 0:
        return CompositeExecutionInputSnapshot(
            request_id=request.id,
            kind="retrieval",
            requirement_ids=request.requirement_ids,
            fingerprint=fingerprint,
            status="limited",
            completeness=RESULT_COMPLETENESS_LIMITED,
            error="复合回答对象或 Evidence 总预算已耗尽",
        )

    await cancel_check()
    started = perf_counter()
    search = await search_confirmed_knowledge(
        db,
        ctx,
        request.query,
        recall_limit=min(settings.knowledge_agent_recall_limit, remaining_entries),
        context_limit=min(settings.knowledge_agent_context_limit, remaining_entries),
    )
    if search.embedding_meta:
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=StageMeta(**search.embedding_meta),
            prompt_version=ANSWER_PROMPT_VERSION,
        )
    if search.rerank_meta:
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=StageMeta(**search.rerank_meta),
            prompt_version=ANSWER_PROMPT_VERSION,
        )
    entry_ids = [item.entry_id for item in search.items][:remaining_entries]
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="search_confirmed_knowledge",
        params={"request_id": request.id, "query": request.query[:200]},
        result={"total": len(entry_ids), "entry_ids": entry_ids},
        duration_ms=int((perf_counter() - started) * 1000),
    )
    if not entry_ids:
        return CompositeExecutionInputSnapshot(
            request_id=request.id,
            kind="retrieval",
            requirement_ids=request.requirement_ids,
            fingerprint=fingerprint,
            status="empty",
            completeness=RESULT_COMPLETENESS_LIMITED,
        )

    await cancel_check()
    started = perf_counter()
    entries = await read_entries(db, ctx, entry_ids)
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="read_entries",
        params={"request_id": request.id, "entry_ids": entry_ids},
        result={
            "total": len(entries.items),
            "denied": len(entries.denied_entry_ids),
            "unavailable": len(entries.unavailable_entry_ids),
        },
        duration_ms=int((perf_counter() - started) * 1000),
    )

    evidence_handles: list[str] = []
    unavailable = len(entries.denied_entry_ids) + len(entries.unavailable_entry_ids)
    for item in entries.items:
        await cancel_check()
        if len(evidence_handles) >= remaining_evidence:
            break
        source_ids = [source["source_id"] for source in item.sources]
        source_ids = source_ids[: remaining_evidence - len(evidence_handles)]
        if not source_ids:
            continue
        started = perf_counter()
        evidence = await read_source_evidence(db, ctx, item.entry_id, source_ids)
        citable = [row for row in evidence.items if row.citable and row.evidence_handle]
        unavailable += len(evidence.items) - len(citable)
        evidence_handles.extend(str(row.evidence_handle) for row in citable)
        await record_tool_result(
            db,
            run_id=run.id,
            tool_name="read_source_evidence",
            params={
                "request_id": request.id,
                "entry_id": item.entry_id,
                "source_ids": source_ids,
            },
            result={
                "total": len(evidence.items),
                "citable": len(citable),
                "denied": sum(row.status == "denied" for row in evidence.items),
                "unavailable": len(evidence.items) - len(citable),
            },
            duration_ms=int((perf_counter() - started) * 1000),
        )

    truncated = len(entries.items) < len(entry_ids) or len(evidence_handles) >= remaining_evidence
    status = "partial" if unavailable else ("limited" if truncated else "completed")
    completeness = RESULT_COMPLETENESS_UNKNOWN if unavailable else RESULT_COMPLETENESS_LIMITED
    return CompositeExecutionInputSnapshot(
        request_id=request.id,
        kind="retrieval",
        requirement_ids=request.requirement_ids,
        fingerprint=fingerprint,
        status=status,
        completeness=completeness,
        entry_ids=[item.entry_id for item in entries.items],
        evidence_handles=list(dict.fromkeys(evidence_handles)),
        error="部分对象或来源不可用" if unavailable else None,
    )


async def _execute_structured(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    ctx: RunToolContext,
    plan: NormalizedCompositeAnswerPlan,
    request: NormalizedCompositeStructuredRequest,
    *,
    cancel_check,
) -> tuple[CompositeExecutionInputSnapshot, list[CompositeToolFact]]:
    params = request.query_plan.model_dump(mode="json", by_alias=True)
    fingerprint = composite_request_fingerprint(
        run.id,
        plan,
        request_id=request.id,
        kind="structured",
        params=params,
    )
    # 每份结构化请求拥有自己的共享集合，不能沿用上一请求的 semantic 候选。
    ctx.structured_query_entry_ids = None
    ctx.structured_query_entry_order = None
    await cancel_check()
    result = await execute_structured_query_plan(
        db,
        ctx,
        request.query_plan,
        cancel_check=cancel_check,
    )
    facts = structured_result_tool_facts(request, result, fingerprint=fingerprint)
    completeness_values = [fact.completeness for fact in facts]
    if not facts:
        completeness = RESULT_COMPLETENESS_UNKNOWN
    elif RESULT_COMPLETENESS_UNKNOWN in completeness_values:
        completeness = RESULT_COMPLETENESS_UNKNOWN
    elif RESULT_COMPLETENESS_LIMITED in completeness_values:
        completeness = RESULT_COMPLETENESS_LIMITED
    else:
        completeness = RESULT_COMPLETENESS_COMPLETE
    status = "completed" if result.status == RUN_COMPLETED else "partial"
    if completeness == RESULT_COMPLETENESS_LIMITED and status == "completed":
        status = "limited"
    entry_ids: list[int] = []
    if result.entries is not None:
        entry_ids = [
            int(item["entry_id"])
            for item in result.entries.get("items", [])
            if item.get("entry_id") is not None
        ]
    return (
        CompositeExecutionInputSnapshot(
            request_id=request.id,
            kind="structured",
            requirement_ids=request.requirement_ids,
            fingerprint=fingerprint,
            status=status,
            completeness=completeness,
            entry_ids=entry_ids,
            result_handles=[fact.handle for fact in facts],
            error="；".join(result.warnings)[:500] or None,
        ),
        facts,
    )


async def execute_composite_answer_plan(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    ctx: RunToolContext,
    plan: NormalizedCompositeAnswerPlan,
    *,
    cancel_check,
    settings: Settings | None = None,
) -> CompositeExecutionArtifacts:
    """按 retrieval → structured 固定顺序执行；恢复只重放未完成请求。"""
    active_settings = settings or get_settings()
    snapshot = restore_composite_execution(
        run.composite_answer_execution_json,
        settings=active_settings,
    )
    planned_request_ids = {
        item.id for item in [*plan.retrieval_requests, *plan.structured_requests]
    }
    snapshot_request_ids = [item.request_id for item in snapshot.inputs]
    if (
        len(snapshot_request_ids) != len(set(snapshot_request_ids))
        or not set(snapshot_request_ids).issubset(planned_request_ids)
        or any(fact.request_id not in planned_request_ids for fact in snapshot.tool_facts)
    ):
        raise ValueError("复合回答执行快照与已固化计划不一致")
    started_at = monotonic()
    existing = {item.request_id: item for item in snapshot.inputs}

    async def _time_guard() -> None:
        await cancel_check()
        if (
            monotonic() - started_at
            >= active_settings.knowledge_agent_composite_answer_execution_timeout_seconds
        ):
            raise TimeoutError("复合回答执行总耗时预算已耗尽")

    for request in plan.retrieval_requests:
        other_inputs = [item for item in snapshot.inputs if item.request_id != request.id]
        remaining_entries = max(
            0,
            active_settings.knowledge_agent_composite_answer_max_entries
            - len({entry_id for item in other_inputs for entry_id in item.entry_ids}),
        )
        remaining_evidence = max(
            0,
            active_settings.knowledge_agent_composite_answer_max_evidence
            - len(
                {
                        handle
                        for item in other_inputs
                    for handle in item.evidence_handles
                }
            ),
        )
        fingerprint_params = {
            "query": request.query,
            "requirement_ids": request.requirement_ids,
            "max_entries": active_settings.knowledge_agent_composite_answer_max_entries,
            "max_evidence": active_settings.knowledge_agent_composite_answer_max_evidence,
        }
        fingerprint = composite_request_fingerprint(
            run.id,
            plan,
            request_id=request.id,
            kind="retrieval",
            params=fingerprint_params,
        )
        restored = existing.get(request.id)
        if (
            restored is not None
            and restored.fingerprint == fingerprint
            and restored.status in {"completed", "empty", "limited"}
        ):
            continue
        await _time_guard()
        try:
            item = await _execute_retrieval(
                db,
                run,
                ctx,
                plan,
                request,
                remaining_entries=remaining_entries,
                remaining_evidence=remaining_evidence,
                cancel_check=_time_guard,
                settings=active_settings,
            )
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "RunCancelled":
                raise
            item = CompositeExecutionInputSnapshot(
                request_id=request.id,
                kind="retrieval",
                requirement_ids=request.requirement_ids,
                fingerprint=fingerprint,
                status="partial",
                completeness=RESULT_COMPLETENESS_UNKNOWN,
                error=f"检索请求执行失败：{exc}"[:500],
            )
        snapshot.inputs = [old for old in snapshot.inputs if old.request_id != request.id]
        snapshot.inputs.append(item)
        snapshot = await _persist_checkpoint(db, run, snapshot, settings=active_settings)
        existing[item.request_id] = item

    for request in plan.structured_requests:
        params = request.query_plan.model_dump(mode="json", by_alias=True)
        fingerprint = composite_request_fingerprint(
            run.id,
            plan,
            request_id=request.id,
            kind="structured",
            params=params,
        )
        restored = existing.get(request.id)
        if (
            restored is not None
            and restored.fingerprint == fingerprint
            and restored.status in {"completed", "empty", "limited"}
        ):
            continue
        await _time_guard()
        try:
            item, facts = await _execute_structured(
                db,
                run,
                ctx,
                plan,
                request,
                cancel_check=_time_guard,
            )
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "RunCancelled":
                raise
            item = CompositeExecutionInputSnapshot(
                request_id=request.id,
                kind="structured",
                requirement_ids=request.requirement_ids,
                fingerprint=fingerprint,
                status="partial",
                completeness=RESULT_COMPLETENESS_UNKNOWN,
                error=f"结构化请求执行失败：{exc}"[:500],
            )
            facts = []
        snapshot.inputs = [old for old in snapshot.inputs if old.request_id != request.id]
        snapshot.inputs.append(item)
        snapshot.tool_facts = [
            fact for fact in snapshot.tool_facts if fact.request_id != request.id
        ] + facts
        snapshot = await _persist_checkpoint(db, run, snapshot, settings=active_settings)
        existing[item.request_id] = item

    await _time_guard()
    return CompositeExecutionArtifacts(snapshot=snapshot)
