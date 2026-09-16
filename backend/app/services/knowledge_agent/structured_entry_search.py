"""一次结构化计划接入 entries Run 的 v2 结果编排。"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    STEP_FINALIZE,
    STEP_STRUCTURED_QUERY_EXECUTE,
    STEP_STRUCTURED_QUERY_PLAN,
)
from app.schemas.knowledge_agent import (
    KnowledgeCountResultOut,
    KnowledgeEntryResultSnapshotOut,
    KnowledgeEntrySetSummaryOut,
    KnowledgeEntrySortOut,
    KnowledgeGroupCountResultOut,
    KnowledgeOutputCompletenessOut,
)
from app.services.knowledge_agent.conversations import scope_label
from app.services.knowledge_agent.observability import run_fallback_summary
from app.services.knowledge_agent.run_control import check_run_cancelled
from app.services.knowledge_agent.runs import finalize_entry_run, update_run_step
from app.services.knowledge_agent.structured_query import (
    plan_and_persist_structured_query,
)
from app.services.knowledge_agent.structured_query_execution import (
    execute_structured_query_plan,
)


def _assistant_compatibility_text(snapshot: KnowledgeEntryResultSnapshotOut) -> str:
    """为旧客户端保留有界摘要，不把有限统计包装成精确全集。"""
    if snapshot.status == "partial" and snapshot.warning:
        return snapshot.warning
    if snapshot.count is not None:
        if snapshot.count.completeness == RESULT_COMPLETENESS_COMPLETE:
            return f"结构化查询完成，共 {snapshot.count.value} 条正式知识。"
        return f"结构化查询完成，本次匹配到 {snapshot.count.value} 条正式知识。"
    if snapshot.group_counts:
        return "；".join(
            f"{group.group_by}："
            + "、".join(
                f"{bucket.label or bucket.key} {bucket.count} 条" for bucket in group.buckets
            )
            + ("（有限结果）" if group.completeness != RESULT_COMPLETENESS_COMPLETE else "")
            for group in snapshot.group_counts
        )
    if snapshot.items:
        return f"找到 {len(snapshot.items)} 条相关正式知识，请使用支持结构化结果的客户端查看。"
    return "结构化查询完成，当前集合没有可展示的正式知识。"


async def execute_structured_query_entry_search(
    db: AsyncSession,
    run,
    decision,
    ctx,
) -> bool:
    """执行 B1 结构化 entries 图；规划失败返回 False 让调用方走旧查找。"""
    settings = get_settings()
    objective = (decision.standalone_query or "").strip()
    trusted_scope_label = scope_label(run.scope_type, run.project_name)

    await check_run_cancelled(run.id)
    await update_run_step(run.id, STEP_STRUCTURED_QUERY_PLAN)
    plan = await plan_and_persist_structured_query(
        db,
        run,
        objective=objective,
        scope_label=trusted_scope_label,
        cancel_check=lambda: check_run_cancelled(run.id),
    )
    await check_run_cancelled(run.id)
    if plan is None:
        from app.services.knowledge_agent.task_state import read_state

        state = read_state(run)
        if state is not None:
            from app.schemas.knowledge_agent import KnowledgeAnswerOut
            from app.services.knowledge_agent.runs import finalize_run

            await finalize_run(
                db, run, answer=KnowledgeAnswerOut(
                    answer=state.pending_question or "无法确定本次查询条件，请补充需要的范围",
                    status="clarification",
                ), status="completed", fallback_summary=await run_fallback_summary(db, run.id),
            )
            return True
        return False

    await update_run_step(run.id, STEP_STRUCTURED_QUERY_EXECUTE)

    async def _cancel() -> None:
        await check_run_cancelled(run.id)

    execution = await execute_structured_query_plan(
        db,
        ctx,
        plan,
        cancel_check=_cancel,
    )
    entries_payload = execution.entries or {}
    items = entries_payload.get("items", [])
    entries_sort = entries_payload.get("sort")
    count = (
        KnowledgeCountResultOut.model_validate(execution.count)
        if execution.count is not None
        else None
    )
    groups = [
        KnowledgeGroupCountResultOut.model_validate(item)
        for item in execution.group_counts
    ]
    from app.services.knowledge_agent.structured_query_tools import resolve_project_filter

    try:
        result_scope = await resolve_project_filter(db, ctx, plan.entry_set)
    except ValueError:
        result_scope = {
            "scope_type": run.scope_type,
            "project_id": run.project_id,
            "project_name": plan.entry_set.project_name or run.project_name,
        }
    warnings = list(execution.warnings)
    snapshot = KnowledgeEntryResultSnapshotOut.model_validate(
        {
            "schema_version": "v2",
            "query": objective,
            "status": execution.status,
            "completeness": execution.set_completeness,
            "items": items,
            "returned_count": len(items),
            "candidate_limit": settings.knowledge_agent_structured_query_semantic_candidate_limit,
            "warning": warnings[0] if warnings else None,
            "snapshot_updated_at": datetime.now(UTC),
            "set_summary": KnowledgeEntrySetSummaryOut(
                **result_scope,
                semantic_query=plan.entry_set.semantic_query,
                main_types=list(plan.entry_set.main_types),
                info_natures=list(plan.entry_set.info_natures),
                updated_at_from=(
                    plan.entry_set.updated_at.from_
                    if plan.entry_set.updated_at is not None
                    else None
                ),
                updated_at_to=(
                    plan.entry_set.updated_at.to if plan.entry_set.updated_at is not None else None
                ),
                completeness=execution.set_completeness,
            ),
            "sort": (
                KnowledgeEntrySortOut.model_validate(entries_sort)
                if entries_sort is not None
                else None
            ),
            "count": count,
            "group_counts": groups,
            "output_completeness": KnowledgeOutputCompletenessOut.model_validate(
                execution.output_completeness
            ),
            "warnings": warnings,
        }
    )
    await db.commit()
    await check_run_cancelled(run.id)
    await update_run_step(run.id, STEP_FINALIZE)
    summary = await run_fallback_summary(db, run.id)
    assistant_text = _assistant_compatibility_text(snapshot)
    from app.services.knowledge_agent.task_state import read_state

    if read_state(run) is not None:
        filters = [snapshot.set_summary.project_name or "当前授权范围内全部项目"]
        if plan.entry_set.semantic_query:
            filters.append(f"主题匹配：{plan.entry_set.semantic_query}")
        if plan.entry_set.main_types:
            filters.append("类型：" + "、".join(plan.entry_set.main_types))
        assistant_text = "统计口径：" + "；".join(filters) + "。\n" + assistant_text
    await check_run_cancelled(run.id)
    await finalize_entry_run(
        db,
        run,
        status=execution.status,
        entry_snapshot=snapshot,
        fallback_summary=summary,
        assistant_text=assistant_text,
    )
    return True
