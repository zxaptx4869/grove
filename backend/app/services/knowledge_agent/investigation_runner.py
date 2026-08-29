"""知识 Agent 有界调查执行器：应用层循环、硬预算、稳定停止与最终综合。

模型每轮只提出结构化下一步；查询去重、工具链、范围、预算与停止条件全部
由本层控制。每个完成轮次作为一个事务检查点提交，最终回答、Run/调查终态、
调查摘要与输出工作集在终态事务一次性写入。
"""

import json
import logging
from collections import defaultdict, deque
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.investigation import (
    INVESTIGATION_CONTROLLER_PROMPT_VERSION,
    run_investigation_controller,
)
from app.agents.knowledge_agent import ANSWER_PROMPT_VERSION, run_knowledge_answer_agent
from app.core.config import get_settings
from app.models import Entry, KnowledgeAgentEvidence
from app.models.knowledge_agent import (
    ANSWER_MODE_AUTO,
    ANSWER_MODE_INVESTIGATE,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
    INVESTIGATION_QUERY_EXECUTED,
    INVESTIGATION_QUERY_PLANNED,
    INVESTIGATION_QUERY_RUNNING,
    INVESTIGATION_ROUND_COMPLETED,
    INVESTIGATION_ROUND_RUNNING,
    INVESTIGATION_STATUS_ACTIVE,
    INVESTIGATION_STATUS_COMPLETED,
    INVESTIGATION_STATUS_INSUFFICIENT,
    PURPOSE_SYNTHESIS,
    RUN_COMPLETED,
    RUN_PARTIAL,
    STEP_ROUND_EVIDENCE,
    STEP_ROUND_PLAN,
    STEP_ROUND_SEARCH,
    STEP_SYNTHESIZE,
    STOP_REASON_CONTROLLER_COMPLETE,
    STOP_REASON_ENTRY_BUDGET,
    STOP_REASON_EVIDENCE_BUDGET,
    STOP_REASON_INSUFFICIENT,
    STOP_REASON_MAX_ROUNDS,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_QUERY_BUDGET,
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
)
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.conversations import scope_label
from app.services.knowledge_agent.evidence import build_validated_answer
from app.services.knowledge_agent.investigation import (
    ControllerPlan,
    controller_plan_defaults,
    validate_controller_output,
)
from app.services.knowledge_agent.ledger import (
    InvestigationLedger,
    LedgerEntryRef,
    LedgerEvidenceRef,
    dedupe_proposed_queries,
    evidence_quote_key,
    normalize_query_text,
    query_fingerprint,
    rebuild_ledger,
)
from app.services.knowledge_agent.observability import (
    StageMeta,
    record_model_invocation,
    record_reference_validation,
    run_fallback_summary,
)
from app.services.knowledge_agent.runner import (
    _build_output_version,
    _check_cancelled,
    _cited_items_from_answer,
    _insufficient_answer,
)
from app.services.knowledge_agent.runs import (
    finalize_run,
    update_run_step,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    record_tool_result,
    search_confirmed_knowledge,
)
from app.services.knowledge_agent.working_set import WorkingSetValidation

logger = logging.getLogger(__name__)


async def _get_or_create_investigation(
    db: AsyncSession,
    run,
    decision,
) -> KnowledgeInvestigation:
    """读取或创建 Run 一对一调查；预算在创建时从服务端配置固化。"""
    investigation = (
        await db.execute(
            select(KnowledgeInvestigation).where(KnowledgeInvestigation.run_id == run.id)
        )
    ).scalar_one_or_none()
    if investigation is not None:
        return investigation
    settings = get_settings()
    investigation = KnowledgeInvestigation(
        run_id=run.id,
        conversation_id=run.conversation_id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
        objective=decision.standalone_query or "",
        requested_answer_mode=run.request_answer_mode or ANSWER_MODE_AUTO,
        actual_answer_mode=run.actual_answer_mode or ANSWER_MODE_INVESTIGATE,
        status=INVESTIGATION_STATUS_ACTIVE,
        max_rounds=settings.knowledge_agent_investigation_max_rounds,
        max_queries_per_round=settings.knowledge_agent_investigation_max_queries_per_round,
        max_total_queries=settings.knowledge_agent_investigation_max_total_queries,
        max_entries=settings.knowledge_agent_investigation_max_entries,
        max_evidence=settings.knowledge_agent_investigation_max_evidence,
    )
    db.add(investigation)
    await db.flush()
    return investigation


async def _reset_incomplete_rounds(
    db: AsyncSession,
    investigation: KnowledgeInvestigation,
) -> None:
    """崩溃恢复：安全重置未完成轮次，从该轮重新开始。

    已完成轮次是事务检查点（status=completed）；崩溃留下的 running/failed
    轮次与其计划查询一并删除，避免唯一约束冲突和半成品观察。已提交的
    Evidence 保留并由 `create_answer_evidence` 幂等复用；轮次号、查询、
    助手回答与预算计数都不会重复。
    """
    rows = (
        (
            await db.execute(
                select(KnowledgeInvestigationRound).where(
                    KnowledgeInvestigationRound.investigation_id == investigation.id,
                    KnowledgeInvestigationRound.status != INVESTIGATION_ROUND_COMPLETED,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return
    round_ids = [row.id for row in rows]
    queries = (
        (
            await db.execute(
                select(KnowledgeInvestigationQuery).where(
                    KnowledgeInvestigationQuery.round_id.in_(round_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    for query in queries:
        await db.delete(query)
    for round_row in rows:
        await db.delete(round_row)
    await db.flush()


def _working_set_summary(working_set: WorkingSetValidation) -> str:
    """工作集短摘要：只含标题线索，不复制正文。"""
    return "；".join(item.entry_title for item in working_set.items[:10])


def _remaining_budget(
    investigation: KnowledgeInvestigation,
    ledger: InvestigationLedger,
) -> dict:
    """剩余预算：rounds/queries/entries/evidence，均不小于 0。"""
    return {
        "rounds": max(0, investigation.max_rounds - investigation.current_round),
        "queries": max(0, investigation.max_total_queries - len(ledger.executed_query_hashes)),
        "entries": max(0, investigation.max_entries - ledger.discovered_entry_count()),
        "evidence": max(0, investigation.max_evidence - ledger.distinct_evidence_count()),
    }


async def _commit_round_observation(
    db: AsyncSession,
    *,
    investigation: KnowledgeInvestigation,
    run,
    round_number: int,
    plan: ControllerPlan,
    controller_meta: StageMeta,
    query_rows: list,
    queries_executed: int,
    entries_added: int,
    evidence_added: int,
    ledger: InvestigationLedger,
    stop_reason: str | None,
) -> None:
    """把一轮观察与账本增量提交为完成检查点。"""
    round_row = (
        await db.execute(
            select(KnowledgeInvestigationRound).where(
                KnowledgeInvestigationRound.investigation_id == investigation.id,
                KnowledgeInvestigationRound.round_number == round_number,
            )
        )
    ).scalar_one_or_none()
    if round_row is None:
        round_row = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=investigation.workspace_id,
            owner_user_id=investigation.owner_user_id,
            round_number=round_number,
            status=INVESTIGATION_ROUND_COMPLETED,
        )
        db.add(round_row)
        await db.flush()
    round_row.status = INVESTIGATION_ROUND_COMPLETED
    round_row.controller_action = plan.action
    round_row.coverage_json = json.dumps(plan.coverage, ensure_ascii=False)
    round_row.gaps_json = json.dumps(plan.gaps, ensure_ascii=False)
    round_row.conflicts_json = json.dumps(plan.conflicts, ensure_ascii=False)
    round_row.reason = plan.reason or None
    round_row.queries_planned = len(query_rows)
    round_row.queries_executed = queries_executed
    round_row.entries_added = entries_added
    round_row.evidence_added = evidence_added
    round_row.meta_json = json.dumps(
        {
            "provider": controller_meta.provider,
            "model": controller_meta.model,
            "is_fallback": controller_meta.is_fallback,
            "error": controller_meta.error,
            "duration_ms": controller_meta.duration_ms,
            "prompt_version": INVESTIGATION_CONTROLLER_PROMPT_VERSION,
        },
        ensure_ascii=False,
    )
    round_row.entries_json = json.dumps(
        ledger.round_entries_payload(round_number),
        ensure_ascii=False,
    )
    round_row.unavailable_json = json.dumps(
        [item for item in ledger.unavailable if item["round_number"] == round_number],
        ensure_ascii=False,
    )
    investigation.current_round = round_number
    investigation.total_queries_executed += queries_executed
    investigation.distinct_entries_found = ledger.discovered_entry_count()
    investigation.citable_evidence_count = ledger.distinct_evidence_count()
    investigation.coverage_summary = json.dumps(ledger.coverage, ensure_ascii=False)
    investigation.gaps_summary = json.dumps(ledger.gaps, ensure_ascii=False)
    investigation.conflicts_summary = json.dumps(ledger.conflicts, ensure_ascii=False)
    if stop_reason is not None:
        investigation.stop_reason = stop_reason
    run.current_round = round_number
    await db.flush()


async def _persist_planned_queries(
    db: AsyncSession,
    *,
    investigation: KnowledgeInvestigation,
    round_row: KnowledgeInvestigationRound,
    round_number: int,
    queries: list[str],
) -> list[KnowledgeInvestigationQuery]:
    """持久化本轮计划查询（planned），供执行与恢复使用。"""
    rows: list[KnowledgeInvestigationQuery] = []
    for sequence, text in enumerate(queries, start=1):
        row = KnowledgeInvestigationQuery(
            investigation_id=investigation.id,
            round_id=round_row.id,
            workspace_id=investigation.workspace_id,
            owner_user_id=investigation.owner_user_id,
            round_number=round_number,
            sequence=sequence,
            original_query=text,
            normalized_query=normalize_query_text(text),
            normalized_query_hash=query_fingerprint(text),
            status=INVESTIGATION_QUERY_PLANNED,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


async def _execute_query_round(
    db: AsyncSession,
    *,
    run,
    ctx: RunToolContext,
    investigation: KnowledgeInvestigation,
    ledger: InvestigationLedger,
    query_rows: list[KnowledgeInvestigationQuery],
    round_number: int,
) -> tuple[int, int, int]:
    """执行“搜索候选池→全局选择→受限读取”，返回轮次增量。

    搜索结果不再按查询返回顺序立即读取 Evidence。先把所有合法查询的
    Entry 候选汇总，再轮转选择 Entry 与 Source 候选，避免首条查询耗尽
    全部预算。所有最终读取仍通过 RunToolContext 的 Workspace/项目范围校验。
    """
    settings = get_settings()
    searches: dict[int, object] = {}
    search_durations: dict[int, int] = {}
    candidates_by_query: dict[int, list[int]] = {}
    query_stats: dict[int, dict[str, int]] = {}

    # 第一阶段：所有搜索先完成，不能让返回较早的查询抢先读取 Evidence。
    for query_row in query_rows:
        await _check_cancelled(run.id)
        await update_run_step(run.id, STEP_ROUND_SEARCH)
        query_row.status = INVESTIGATION_QUERY_RUNNING
        # 提交状态变更，避免主会话写锁阻塞跨会话取消的短会话
        await db.commit()
        started = perf_counter()
        search = await search_confirmed_knowledge(
            db,
            ctx,
            # 检索使用清理后的原文（保留空格与大小写）；规范化文本只用于指纹去重
            query_row.original_query,
            recall_limit=settings.knowledge_agent_recall_limit,
            context_limit=settings.knowledge_agent_context_limit,
        )
        duration_ms = int((perf_counter() - started) * 1000)
        if search.embedding_meta:
            await record_model_invocation(
                db,
                run_id=run.id,
                meta=StageMeta(**search.embedding_meta),
                prompt_version=ANSWER_PROMPT_VERSION,
                investigation_id=investigation.id,
                round_number=round_number,
                query_sequence=query_row.sequence,
            )
        if search.rerank_meta:
            await record_model_invocation(
                db,
                run_id=run.id,
                meta=StageMeta(**search.rerank_meta),
                prompt_version=ANSWER_PROMPT_VERSION,
                investigation_id=investigation.id,
                round_number=round_number,
                query_sequence=query_row.sequence,
            )
        # search 及模型调用留痕可能写入主会话。下一条 Query 会通过独立短会话
        # 更新 Run 步骤；先释放当前写事务，避免 SQLite 的单写者锁互相阻塞。
        await db.commit()
        candidate_ids = list(
            dict.fromkeys(
                item.entry_id
                for item in search.items
                if item.entry_id not in ledger.discovered_entries
            )
        )
        searches[query_row.sequence] = search
        search_durations[query_row.sequence] = duration_ms
        candidates_by_query[query_row.sequence] = candidate_ids
        query_stats[query_row.sequence] = {
            "hits": len(search.items),
            "new_entries": len(candidate_ids),
            "entries_added": 0,
            "evidence_added": 0,
            "denied": 0,
            "unavailable": 0,
            "deduped": 0,
            "limited": 0,
        }
        # 每个查询工具批次后检查取消：搜索期间设置的取消在此边界命中
        await _check_cancelled(run.id)

    # 第二阶段：Entry 候选按查询轮转。每个查询最多消耗公平份额，除非它是
    # 唯一仍有候选的查询；同一 Entry 被多查询命中时只计第一个稳定归属。
    remaining_entries = max(0, investigation.max_entries - ledger.discovered_entry_count())
    entry_limit_per_query = max(
        1, (remaining_entries + max(1, len(query_rows)) - 1) // max(1, len(query_rows))
    )
    queues = {sequence: deque(entry_ids) for sequence, entry_ids in candidates_by_query.items()}
    selected_entries: list[tuple[int, int]] = []
    selected_entry_ids: set[int] = set()
    selected_per_query: defaultdict[int, int] = defaultdict(int)
    while len(selected_entries) < remaining_entries and any(queues.values()):
        progress = False
        for query_row in query_rows:
            queue = queues[query_row.sequence]
            while queue and queue[0] in selected_entry_ids:
                queue.popleft()
                query_stats[query_row.sequence]["deduped"] += 1
            if not queue or selected_per_query[query_row.sequence] >= entry_limit_per_query:
                continue
            entry_id = queue.popleft()
            selected_entries.append((query_row.sequence, entry_id))
            selected_entry_ids.add(entry_id)
            selected_per_query[query_row.sequence] += 1
            progress = True
            if len(selected_entries) >= remaining_entries:
                break
        if not progress:
            # 所有仍有候选的查询均已用完公平份额时，稳定放宽限额继续轮转。
            entry_limit_per_query += 1

    for query_row in query_rows:
        admitted_ids = [
            entry_id for sequence, entry_id in selected_entries if sequence == query_row.sequence
        ]
        query_stats[query_row.sequence]["limited"] = max(
            0,
            len(candidates_by_query[query_row.sequence])
            - len(admitted_ids)
            - query_stats[query_row.sequence]["deduped"],
        )
        await record_tool_result(
            db,
            run_id=run.id,
            tool_name="search_confirmed_knowledge",
            params={
                "query": query_row.normalized_query[:200],
                "round": round_number,
                "query_sequence": query_row.sequence,
            },
            result={
                "total": query_stats[query_row.sequence]["hits"],
                "entry_ids": admitted_ids,
                "new_entries": query_stats[query_row.sequence]["new_entries"],
                "admitted": len(admitted_ids),
                "deduped": query_stats[query_row.sequence]["deduped"],
                "limited": query_stats[query_row.sequence]["limited"],
                "remaining_entry_budget": remaining_entries,
            },
            duration_ms=search_durations[query_row.sequence],
            investigation_id=investigation.id,
            round_number=round_number,
            query_sequence=query_row.sequence,
        )
    await db.commit()

    entries_by_id: dict[int, object] = {}
    if selected_entries:
        await _check_cancelled(run.id)
        await update_run_step(run.id, STEP_ROUND_EVIDENCE)
        selected_ids = [entry_id for _, entry_id in selected_entries]
        started = perf_counter()
        entries = await read_entries(db, ctx, selected_ids)
        read_duration_ms = int((perf_counter() - started) * 1000)
        entries_by_id = {item.entry_id: item for item in entries.items}
        owner_by_entry = {entry_id: sequence for sequence, entry_id in selected_entries}
        for entry_id in entries.denied_entry_ids:
            sequence = owner_by_entry.get(entry_id)
            if sequence is not None:
                query_stats[sequence]["denied"] += 1
            ledger.add_unavailable(
                kind="entry",
                obj_id=entry_id,
                reason="Entry 越权或未发现",
                round_number=round_number,
            )
        for entry_id in entries.unavailable_entry_ids:
            sequence = owner_by_entry.get(entry_id)
            if sequence is not None:
                query_stats[sequence]["unavailable"] += 1
            ledger.add_unavailable(
                kind="entry",
                obj_id=entry_id,
                reason="Entry 已删除或移出范围",
                round_number=round_number,
            )
        await record_tool_result(
            db,
            run_id=run.id,
            tool_name="read_entries",
            params={"entry_ids": selected_ids, "round": round_number},
            result={
                "total": len(entries.items),
                "denied": len(entries.denied_entry_ids),
                "unavailable": len(entries.unavailable_entry_ids),
            },
            duration_ms=read_duration_ms,
            investigation_id=investigation.id,
            round_number=round_number,
        )
        for sequence, entry_id in selected_entries:
            item = entries_by_id.get(entry_id)
            if item is None:
                continue
            if ledger.add_entry(
                LedgerEntryRef(
                    entry_id=item.entry_id,
                    entry_title=item.title,
                    project_name=item.project_name,
                    node_path=item.node_path,
                    round_number=round_number,
                )
            ):
                query_stats[sequence]["entries_added"] += 1
        await db.commit()

    # 第三阶段：将已读取 Entry 的 Source 候选再次按查询轮转。单 Entry 与单
    # Query 都有上限，避免一个高来源数的 Entry 重新垄断 Evidence 预算。
    evidence_budget = max(0, investigation.max_evidence - ledger.distinct_evidence_count())
    evidence_limit_per_query = max(
        1, (evidence_budget + max(1, len(query_rows)) - 1) // max(1, len(query_rows))
    )
    evidence_limit_per_entry = max(
        1, (evidence_budget + max(1, len(selected_entries)) - 1) // max(1, len(selected_entries))
    )
    source_queues: dict[int, deque[tuple[int, int]]] = defaultdict(deque)
    for sequence, entry_id in selected_entries:
        item = entries_by_id.get(entry_id)
        if item is None:
            continue
        for source in item.sources:
            source_queues[sequence].append((entry_id, int(source["source_id"])))
    attempted_source_keys: set[tuple[int, int]] = set()
    accepted_evidence_per_query: defaultdict[int, int] = defaultdict(int)
    accepted_evidence_per_entry: defaultdict[int, int] = defaultdict(int)
    seen_quotes = {
        evidence_quote_key(ref.entry_id, ref.quote) for ref in ledger.evidences.values()
    }
    seen_sources = {(ref.entry_id, ref.source_id) for ref in ledger.evidences.values()}
    while (
        ledger.distinct_evidence_count() < investigation.max_evidence
        and any(source_queues.values())
    ):
        attempted = False
        for query_row in query_rows:
            queue = source_queues[query_row.sequence]
            while queue and queue[0] in attempted_source_keys:
                queue.popleft()
                query_stats[query_row.sequence]["deduped"] += 1
            if (
                not queue
                or accepted_evidence_per_query[query_row.sequence] >= evidence_limit_per_query
            ):
                continue
            entry_id, source_id = queue[0]
            if accepted_evidence_per_entry[entry_id] >= evidence_limit_per_entry:
                continue
            queue.popleft()
            attempted_source_keys.add((entry_id, source_id))
            attempted = True
            await _check_cancelled(run.id)
            started = perf_counter()
            evidence_result = await read_source_evidence(
                db,
                ctx,
                entry_id,
                [source_id],
                round_number=round_number,
                query_sequence=query_row.sequence,
            )
            duration_ms = int((perf_counter() - started) * 1000)
            citable = [
                row for row in evidence_result.items if row.citable and row.evidence_id is not None
            ]
            unavailable = [row for row in evidence_result.items if not row.citable]
            await record_tool_result(
                db,
                run_id=run.id,
                tool_name="read_source_evidence",
                params={
                    "entry_id": entry_id,
                    "source_ids": [source_id],
                    "round": round_number,
                    "query_sequence": query_row.sequence,
                },
                result={
                    "total": len(evidence_result.items),
                    "citable": len(citable),
                    "denied": 0,
                    "unavailable": len(unavailable),
                },
                duration_ms=duration_ms,
                investigation_id=investigation.id,
                round_number=round_number,
                query_sequence=query_row.sequence,
            )
            for row in unavailable:
                query_stats[query_row.sequence]["unavailable"] += 1
                ledger.add_unavailable(
                    kind="evidence",
                    obj_id=row.source_id,
                    reason=row.reason or row.status,
                    round_number=round_number,
                )
            accepted_from_candidate = 0
            for row in citable:
                if ledger.distinct_evidence_count() >= investigation.max_evidence:
                    break
                quote_key = evidence_quote_key(row.entry_id, row.quote or "")
                source_key = (row.entry_id, row.source_id)
                if source_key in seen_sources or quote_key in seen_quotes:
                    query_stats[query_row.sequence]["deduped"] += 1
                    if source_key not in seen_sources:
                        # read_source_evidence 为核验通过的候选创建了临时 Evidence；
                        # 等价 quote 未被账本接纳时必须在同一事务删除，不能让
                        # 它在崩溃恢复时作为可引用 Evidence 重新进入账本。
                        persisted = await db.get(KnowledgeAgentEvidence, row.evidence_id)
                        if persisted is not None:
                            await db.delete(persisted)
                    continue
                if ledger.add_evidence(
                    LedgerEvidenceRef(
                        evidence_id=row.evidence_id,
                        handle=row.evidence_handle or "",
                        entry_id=row.entry_id,
                        source_id=row.source_id,
                        source_title=row.source_title,
                        attachment_id=row.attachment_id,
                        quote=row.quote or "",
                        round_number=round_number,
                    )
                ):
                    query_stats[query_row.sequence]["evidence_added"] += 1
                    accepted_from_candidate += 1
                    seen_sources.add(source_key)
                    seen_quotes.add(quote_key)
            if accepted_from_candidate:
                accepted_evidence_per_query[query_row.sequence] += accepted_from_candidate
                accepted_evidence_per_entry[entry_id] += accepted_from_candidate
            await db.commit()
            if ledger.distinct_evidence_count() >= investigation.max_evidence:
                break
        if not attempted:
            evidence_limit_per_query += 1
            evidence_limit_per_entry += 1

    for query_row in query_rows:
        stats = query_stats[query_row.sequence]
        query_row.status = INVESTIGATION_QUERY_EXECUTED
        query_row.result_counts_json = json.dumps(stats, ensure_ascii=False)
        ledger.add_executed_query(
            fingerprint=query_row.normalized_query_hash,
            text=query_row.normalized_query,
            round_number=round_number,
        )
    await db.commit()
    return (
        len(query_rows),
        sum(item["entries_added"] for item in query_stats.values()),
        sum(item["evidence_added"] for item in query_stats.values()),
    )


async def _synthesize_investigation_answer(
    db: AsyncSession,
    *,
    run,
    ctx: RunToolContext,
    decision,
    investigation: KnowledgeInvestigation,
    ledger: InvestigationLedger,
    scope: str,
    working_set: WorkingSetValidation,
) -> tuple[KnowledgeAnswerOut, str, list[dict]]:
    """最终综合：只传当前 Run Evidence 与紧凑账本，返回 (回答, Run 状态, 引用线索)。"""
    await _check_cancelled(run.id)
    if ledger.distinct_evidence_count() == 0:
        answer = _insufficient_answer(
            "调查未获得可核验的当前 Run 证据，无法给出带引用的确定结论。",
            "没有当前 Run 可核验 Evidence",
        )
        return answer, RUN_PARTIAL, []

    entry_ids = [ref.entry_id for ref in ledger.discovered_entries.values() if ref.entry_id != 0]
    entries = await read_entries(db, ctx, entry_ids)
    entries_by_id = {item.entry_id: item for item in entries.items}
    evidence_by_entry: dict[int, list[LedgerEvidenceRef]] = {}
    for ref in ledger.evidences.values():
        evidence_by_entry.setdefault(ref.entry_id, []).append(ref)

    answer_entries: list[dict] = []
    for item in entries.items:
        refs = evidence_by_entry.get(item.entry_id, [])
        if not refs:
            continue
        answer_entries.append(
            {
                "entry_id": item.entry_id,
                "title": item.title,
                "content": item.content,
                "project_name": item.project_name,
                "node_path": item.node_path,
                "evidences": [
                    {
                        "handle": ref.handle,
                        "quote": ref.quote,
                        "source_title": ref.source_title,
                    }
                    for ref in refs
                ],
            }
        )

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_SYNTHESIZE)
    synthesis_context = (
        f"实际模式：investigate；完成轮次：{investigation.current_round}；"
        f"实际查询数：{investigation.total_queries_executed}；"
        f"停止原因：{investigation.stop_reason or 'unknown'}；"
        f"未解决缺口：{'；'.join(ledger.gaps) or '（无）'}"
    )
    draft, answer_meta = await run_knowledge_answer_agent(
        db,
        run.workspace_id,
        decision.standalone_query,
        scope,
        answer_entries,
        purpose=PURPOSE_SYNTHESIS,
        synthesis_context=synthesis_context,
    )
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=answer_meta,
        prompt_version=ANSWER_PROMPT_VERSION,
        investigation_id=investigation.id,
    )
    await db.commit()

    answer, ref_stats = await build_validated_answer(
        db,
        run.id,
        draft,
        verifiable_gaps=ledger.gaps,
    )
    factual_without_refs = not draft.insufficient and ref_stats.valid_count == 0
    if ref_stats.discarded_count > 0:
        await record_reference_validation(
            db,
            run.id,
            stats=ref_stats,
            note="调查综合部分引用被丢弃",
        )
    elif factual_without_refs:
        await record_reference_validation(
            db,
            run.id,
            stats=ref_stats,
            note="调查综合事实性回答没有有效引用",
        )
    if ref_stats.discarded_count > 0 or factual_without_refs:
        await db.commit()
    if answer_meta.is_fallback:
        answer = KnowledgeAnswerOut(
            answer=answer.answer,
            status="failed",
            insufficient_note=answer.insufficient_note or "回答模型不可用",
        )
    run_status = (
        RUN_PARTIAL
        if (answer_meta.is_fallback or factual_without_refs or ref_stats.discarded_count)
        else RUN_COMPLETED
    )
    cited_items = _cited_items_from_answer(answer, entries_by_id, run.id)
    # 控制器 coverage/gaps 是搜索前计划；终态只保留实际有效引用的结果。
    ledger.coverage = list(answer.coverage)
    ledger.gaps = list(answer.gaps)
    ledger.conflicts = [conflict.summary for conflict in answer.conflicts]
    return answer, run_status, cited_items


async def execute_investigation(
    db: AsyncSession,
    run,
    decision,
    *,
    input_version,
    working_set: WorkingSetValidation,
    ctx: RunToolContext,
    seed_entries: list[Entry],
) -> None:
    """执行有界调查：最多 max_rounds 轮，应用层控制查询/Entry/Evidence 预算。"""
    settings = get_settings()
    scope = scope_label(run.scope_type, run.project_name)
    investigation = await _get_or_create_investigation(db, run, decision)
    # 恢复：重置上次执行未完成轮次，再重建账本与剩余预算
    await _reset_incomplete_rounds(db, investigation)
    await db.commit()

    ledger = await rebuild_ledger(db, investigation, run.id)
    # rebuild_ledger 会清理旧版本可能提交的重复/超预算 Evidence；在后续
    # 独立进度会话写入前提交清理，保持 SQLite 事务边界明确。
    await db.commit()
    # 恢复：把重建出的已发现 Entry 回填到工具上下文，保证后续读取与综合授权
    for entry_id in ledger.discovered_entries:
        ctx.discovered_entry_ids.add(entry_id)
    # 复验有效的工作集种子进入已发现集合（round=0，不计入发现预算）
    for seed in seed_entries:
        ctx.discovered_entry_ids.add(seed.id)
        ledger.add_entry(
            LedgerEntryRef(
                entry_id=seed.id,
                entry_title=seed.title,
                project_name=seed.project.name if seed.project else None,
                round_number=0,
            )
        )

    # 恢复：若上次执行已在停止检查点提交停止原因，直接进入综合，不重复轮次
    stop_reason: str | None = investigation.stop_reason
    round_number = investigation.current_round + 1
    while stop_reason is None and round_number <= investigation.max_rounds:
        await _check_cancelled(run.id)
        await update_run_step(run.id, STEP_ROUND_PLAN)
        controller_draft, controller_meta = await run_investigation_controller(
            db,
            run.workspace_id,
            objective=investigation.objective,
            scope_label=scope,
            working_set_summary=_working_set_summary(working_set),
            executed_queries=[item["text"] for item in ledger.executed_queries],
            ledger_summary=ledger.controller_summary(max_chars=1500),
            remaining_budget=_remaining_budget(investigation, ledger),
        )
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=controller_meta,
            prompt_version=INVESTIGATION_CONTROLLER_PROMPT_VERSION,
            investigation_id=investigation.id,
            round_number=round_number,
        )
        plan = validate_controller_output(
            controller_draft,
            **controller_plan_defaults(),
        )
        if plan.invalid:
            # 非法输出：安全停止，不执行任何查询
            plan = ControllerPlan(
                action=INVESTIGATION_ACTION_INSUFFICIENT,
                reason=plan.rejection_note or "控制器输出非法",
                coverage=plan.coverage,
                gaps=plan.gaps,
                conflicts=plan.conflicts,
            )
            stop_reason = STOP_REASON_NO_PROGRESS
        elif controller_meta.is_fallback:
            stop_reason = STOP_REASON_INSUFFICIENT
        elif plan.action == INVESTIGATION_ACTION_ANSWER:
            stop_reason = STOP_REASON_CONTROLLER_COMPLETE
        elif plan.action == INVESTIGATION_ACTION_INSUFFICIENT:
            stop_reason = STOP_REASON_INSUFFICIENT
        else:
            new_queries, _duplicates = dedupe_proposed_queries(
                plan.queries,
                ledger.executed_query_hashes,
                max_queries=investigation.max_queries_per_round,
            )
            room = investigation.max_total_queries - len(ledger.executed_query_hashes)
            if not new_queries:
                stop_reason = STOP_REASON_NO_PROGRESS
            elif room <= 0:
                stop_reason = STOP_REASON_QUERY_BUDGET
            else:
                new_queries = new_queries[:room]
                if not new_queries:
                    stop_reason = STOP_REASON_QUERY_BUDGET

        ledger.set_observations(
            coverage=plan.coverage,
            gaps=plan.gaps,
            conflicts=plan.conflicts,
        )
        if stop_reason is not None:
            await _commit_round_observation(
                db,
                investigation=investigation,
                run=run,
                round_number=round_number,
                plan=plan,
                controller_meta=controller_meta,
                query_rows=[],
                queries_executed=0,
                entries_added=0,
                evidence_added=0,
                ledger=ledger,
                stop_reason=stop_reason,
            )
            await db.commit()
            break

        # 执行轮次：先持久化计划查询，再执行固定工具链
        round_row = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=investigation.workspace_id,
            owner_user_id=investigation.owner_user_id,
            round_number=round_number,
            status=INVESTIGATION_ROUND_RUNNING,
            controller_action=plan.action,
        )
        db.add(round_row)
        await db.flush()
        query_rows = await _persist_planned_queries(
            db,
            investigation=investigation,
            round_row=round_row,
            round_number=round_number,
            queries=new_queries,
        )
        await db.commit()

        executed, entries_added, evidence_added = await _execute_query_round(
            db,
            run=run,
            ctx=ctx,
            investigation=investigation,
            ledger=ledger,
            query_rows=query_rows,
            round_number=round_number,
        )
        await _commit_round_observation(
            db,
            investigation=investigation,
            run=run,
            round_number=round_number,
            plan=plan,
            controller_meta=controller_meta,
            query_rows=query_rows,
            queries_executed=executed,
            entries_added=entries_added,
            evidence_added=evidence_added,
            ledger=ledger,
            stop_reason=None,
        )
        await db.commit()

        # 确定性停止：各类预算优先于无进展，保证剩余额度耗尽时以正确原因停止
        if ledger.discovered_entry_count() >= investigation.max_entries:
            stop_reason = STOP_REASON_ENTRY_BUDGET
            break
        if ledger.distinct_evidence_count() >= investigation.max_evidence:
            stop_reason = STOP_REASON_EVIDENCE_BUDGET
            break
        if entries_added == 0 and evidence_added == 0:
            stop_reason = STOP_REASON_NO_PROGRESS
            break
        if len(ledger.executed_query_hashes) >= investigation.max_total_queries:
            stop_reason = STOP_REASON_QUERY_BUDGET
            break
        round_number += 1

    if stop_reason is None:
        stop_reason = STOP_REASON_MAX_ROUNDS
    investigation.stop_reason = stop_reason
    # 此处只提交停止检查点；终态 coverage/gaps 要等引用校验后才可写入。
    # 调查终止状态作为检查点提交，避免综合步骤的短会话被 SQLite 写锁阻塞
    await db.commit()

    # 最终综合（终态事务由外层 execute_run/process_one_run 提交）
    answer, run_status, cited_items = await _synthesize_investigation_answer(
        db,
        run=run,
        ctx=ctx,
        decision=decision,
        investigation=investigation,
        ledger=ledger,
        scope=scope,
        working_set=working_set,
    )
    if answer.status == "insufficient":
        investigation.status = INVESTIGATION_STATUS_INSUFFICIENT
    else:
        investigation.status = INVESTIGATION_STATUS_COMPLETED
    investigation.coverage_summary = json.dumps(ledger.coverage, ensure_ascii=False)
    investigation.gaps_summary = json.dumps(ledger.gaps, ensure_ascii=False)
    investigation.conflicts_summary = json.dumps(ledger.conflicts, ensure_ascii=False)
    summary = await run_fallback_summary(db, run.id)
    run.investigation_summary = json.dumps(
        {
            "requested_answer_mode": run.request_answer_mode or ANSWER_MODE_AUTO,
            "actual_answer_mode": run.actual_answer_mode,
            "rounds_completed": investigation.current_round,
            "queries_executed": investigation.total_queries_executed,
            "stop_reason": investigation.stop_reason,
            "coverage": ledger.coverage,
            "gaps": ledger.gaps,
            "conflicts": ledger.conflicts,
        },
        ensure_ascii=False,
    )
    await _build_output_version(
        db,
        run,
        decision,
        input_version=input_version,
        parent_seeds=working_set.items,
        cited_items=cited_items,
        working_set_limit=settings.knowledge_agent_working_set_limit,
    )
    await finalize_run(
        db,
        run,
        answer=answer,
        status=run_status,
        fallback_summary=summary,
    )
