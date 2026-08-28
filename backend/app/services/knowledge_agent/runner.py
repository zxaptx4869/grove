"""知识 Agent 固定执行图执行器：上下文决策 → 澄清/检索 → Evidence → 回答 → 工作集。"""

import json
import logging
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.knowledge_agent import ANSWER_PROMPT_VERSION, run_knowledge_answer_agent
from app.agents.knowledge_context import CONTEXT_DECISION_PROMPT_VERSION
from app.core.config import get_settings
from app.models import (
    Entry,
    KnowledgeAgentRun,
    KnowledgeContextVersion,
    KnowledgeMessage,
    Project,
)
from app.models.knowledge_agent import (
    CONTEXT_DECISION_CLARIFY,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_MODE_AUTO,
    PURPOSE_CONTEXT_DECISION,
    RUN_COMPLETED,
    RUN_PARTIAL,
    RUN_PROCESSING,
    STEP_CONTEXT_DECISION,
    STEP_FINALIZE,
    STEP_ORGANIZE_ANSWER,
    STEP_READ_ENTRIES,
    STEP_READ_EVIDENCE,
    STEP_SEARCH,
    STEP_VALIDATE_REFERENCES,
)
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.conversations import scope_label
from app.services.knowledge_agent.evidence import build_validated_answer
from app.services.knowledge_agent.follow_up import (
    DEFAULT_CLARIFY_QUESTION,
    ContextDecisionResult,
    decide_context,
)
from app.services.knowledge_agent.observability import (
    StageMeta,
    record_model_invocation,
    record_reference_validation,
    run_fallback_summary,
)
from app.services.knowledge_agent.runs import (
    finalize_run,
    read_run_cancel_state,
    update_run_step,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    record_tool_result,
    search_confirmed_knowledge,
)
from app.services.knowledge_agent.working_set import (
    WorkingSetSeedItem,
    build_output_items,
    create_context_version,
    load_validated_working_set,
)

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    """Run 已被取消：模型结果不得写入正常回答。"""


async def _check_cancelled(run_id: int) -> None:
    """步骤边界检查取消请求：用独立短会话读取最新状态。"""
    cancel_requested, status = await read_run_cancel_state(run_id)
    if cancel_requested and status == RUN_PROCESSING:
        raise RunCancelled()


def _insufficient_answer(text: str, note: str) -> KnowledgeAnswerOut:
    """确定性知识不足回答：不调用模型，不编造内容。"""
    return KnowledgeAnswerOut(
        answer=text,
        status="insufficient",
        insufficient_note=note,
    )


def _restore_decision(run: KnowledgeAgentRun) -> ContextDecisionResult | None:
    """崩溃恢复：复用 Run 上已固化的上下文决策，不重复调用分类模型。"""
    if not run.context_decision or not run.standalone_query:
        return None
    try:
        meta_json = json.loads(run.context_meta_json or "{}")
    except (json.JSONDecodeError, TypeError):
        meta_json = {}
    try:
        history_ids = json.loads(run.history_message_ids_json or "[]")
    except (json.JSONDecodeError, TypeError):
        history_ids = []
    return ContextDecisionResult(
        decision=run.context_decision,
        standalone_query=run.standalone_query,
        topic_label=run.topic_label,
        clarify_question=meta_json.get("clarify_question"),
        degraded=bool(meta_json.get("is_fallback") or meta_json.get("error")),
        history_message_ids=list(history_ids),
        meta=StageMeta(
            purpose=PURPOSE_CONTEXT_DECISION,
            provider=meta_json.get("provider", "server"),
            model=meta_json.get("model"),
            is_fallback=bool(meta_json.get("is_fallback")),
            error=meta_json.get("error"),
            duration_ms=int(meta_json.get("duration_ms", 0)),
        ),
    )


def _persist_decision(
    run: KnowledgeAgentRun,
    decision: ContextDecisionResult,
) -> None:
    """把归一化后的决策写入 Run（决策阶段持久化，支持轮询与崩溃恢复）。"""
    run.context_decision = decision.decision
    run.standalone_query = decision.standalone_query
    run.topic_label = decision.topic_label
    run.history_message_ids_json = json.dumps(decision.history_message_ids)
    run.context_meta_json = json.dumps(
        {
            "provider": decision.meta.provider,
            "model": decision.meta.model,
            "is_fallback": decision.meta.is_fallback,
            "error": decision.meta.error,
            "duration_ms": decision.meta.duration_ms,
            "prompt_version": CONTEXT_DECISION_PROMPT_VERSION,
            "clarify_question": decision.clarify_question,
        },
        ensure_ascii=False,
    )


async def _build_output_version(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    decision: ContextDecisionResult,
    *,
    input_version: KnowledgeContextVersion | None,
    parent_seeds: list[WorkingSetSeedItem],
    cited_items: list[dict],
    working_set_limit: int,
) -> KnowledgeContextVersion | None:
    """按决策与最终有效引用推进工作集；返回输出版本（可能为 None）。"""
    if decision.decision == CONTEXT_DECISION_CLARIFY:
        return None
    if decision.decision == CONTEXT_DECISION_CONTINUE and not cited_items:
        # 继续追问无证据：保持旧活动版本，不推进
        return None
    items = build_output_items(
        cited=cited_items,
        parent=parent_seeds,
        decision=decision.decision,
        max_items=working_set_limit,
    )
    version = await create_context_version(
        db,
        conversation_id=run.conversation_id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
        topic_label=decision.topic_label or "未命名主题",
        source_run_id=run.id,
        items=items,
        parent_version_id=input_version.id if input_version is not None else None,
    )
    run.output_context_version_id = version.id
    return version


def _cited_items_from_answer(
    answer: KnowledgeAnswerOut,
    entries_by_id: dict[int, object],
    source_run_id: int,
) -> list[dict]:
    """从最终有效引用提取本轮引用的 Entry 线索（去重、按引用顺序）。"""
    cited: list[dict] = []
    seen: set[int] = set()
    for citation in answer.citations:
        entry_id = citation.entry_id
        if entry_id in seen or entry_id == 0:
            continue
        seen.add(entry_id)
        info = entries_by_id.get(entry_id)
        cited.append(
            {
                "entry_id": entry_id,
                "entry_title": citation.entry_title,
                "project_name": info.project_name if info is not None else None,
                "node_path": info.node_path if info is not None else None,
                "source_run_id": source_run_id,
            }
        )
    return cited


async def execute_run(db: AsyncSession, run: KnowledgeAgentRun) -> None:
    """执行一次 Run 的连续追问固定执行图。

    中间步骤的可观测记录（工具调用、模型调用、Evidence）在步骤边界提交，
    使 SQLite/MySQL 上的短会话步骤更新可写；最终回答、Run 终态、活动槽释放
    与可选输出工作集仍在终态事务一次性提交。
    """
    settings = get_settings()
    ctx = RunToolContext(
        run_id=run.id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
    )
    user_message = await db.get(KnowledgeMessage, run.user_message_id)
    query = user_message.content if user_message is not None else ""
    scope = scope_label(run.scope_type, run.project_name)

    # 步骤 0：上下文决策（固定输入版本 + 有限历史，历史只用于意图理解）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_CONTEXT_DECISION)
    input_version: KnowledgeContextVersion | None = None
    if run.input_context_version_id is not None:
        input_version = await db.get(
            KnowledgeContextVersion, run.input_context_version_id
        )
    active_topic_label = input_version.topic_label if input_version is not None else None
    working_set = await load_validated_working_set(
        db,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        conversation_id=run.conversation_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        context_version_id=run.input_context_version_id,
    )
    decision = _restore_decision(run)
    if decision is None:
        decision = await decide_context(
            db,
            workspace_id=run.workspace_id,
            conversation_id=run.conversation_id,
            current_message=query,
            request_mode=run.request_context_mode or CONTEXT_MODE_AUTO,
            active_topic_label=active_topic_label,
            working_set_titles=[item.entry_title for item in working_set.items],
            history_limit=settings.knowledge_agent_history_limit,
            history_message_chars=settings.knowledge_agent_history_message_chars,
            user_message_id=run.user_message_id,
        )
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=decision.meta,
            prompt_version=CONTEXT_DECISION_PROMPT_VERSION,
        )
        _persist_decision(run, decision)
        await db.commit()

    # 澄清分支：直接回复，不检索、不生成事实引用、不更新工作集
    if decision.decision == CONTEXT_DECISION_CLARIFY:
        await _check_cancelled(run.id)
        summary = await run_fallback_summary(db, run.id)
        await finalize_run(
            db,
            run,
            answer=KnowledgeAnswerOut(
                answer=decision.clarify_question or DEFAULT_CLARIFY_QUESTION,
                status="clarification",
            ),
            status=RUN_COMPLETED,
            fallback_summary=summary,
        )
        return

    # 工作集种子复验可观测：删除/越权/移出范围的项只记录不可用
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="working_set_seed",
        params={"context_version_id": run.input_context_version_id},
        result={
            "total": len(working_set.items) + len(working_set.unavailable),
            "valid": len(working_set.items),
            "denied": 0,
            "unavailable": len(working_set.unavailable),
            "reasons": [item["reason"] for item in working_set.unavailable[:20]],
        },
        duration_ms=0,
    )
    await db.commit()

    # 继续追问：复验有效的工作集种子进入服务端已发现集合；新话题不使用旧种子
    seed_entries: list[Entry] = []
    if decision.decision == CONTEXT_DECISION_CONTINUE and working_set.items:
        seed_ids = [seed.entry_id for seed in working_set.items]
        for seed in working_set.items:
            ctx.discovered_entry_ids.add(seed.entry_id)
        rows = (
            await db.execute(
                select(Entry)
                .join(Project, Entry.project_id == Project.id)
                .options(selectinload(Entry.project))
                .where(Entry.id.in_(seed_ids))
            )
        ).scalars().all()
        seed_entries = list(rows)

    # 步骤 1：搜索正式知识（工作集种子 + 独立查询新召回统一重排）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_SEARCH)
    started = perf_counter()
    search = await search_confirmed_knowledge(
        db,
        ctx,
        decision.standalone_query or query,
        recall_limit=settings.knowledge_agent_recall_limit,
        context_limit=settings.knowledge_agent_context_limit,
        seed_entries=seed_entries or None,
    )
    duration_ms = int((perf_counter() - started) * 1000)
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
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="search_confirmed_knowledge",
        params={"query": (decision.standalone_query or query)[:200]},
        result={
            "total": len(search.items),
            "entry_ids": [item.entry_id for item in search.items],
        },
        duration_ms=duration_ms,
    )
    await db.commit()
    if not search.items:
        await _check_cancelled(run.id)
        await _build_output_version(
            db,
            run,
            decision,
            input_version=input_version,
            parent_seeds=working_set.items,
            cited_items=[],
            working_set_limit=settings.knowledge_agent_working_set_limit,
        )
        summary = await run_fallback_summary(db, run.id)
        await finalize_run(
            db,
            run,
            answer=_insufficient_answer(
                "当前问答范围内没有找到与问题相关的已确认知识。",
                "没有召回相关正式 Entry",
            ),
            status=RUN_COMPLETED,
            fallback_summary=summary,
        )
        return

    # 步骤 2：批量读取候选 Entry（已发现集合 + 范围复验）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_READ_ENTRIES)
    entry_ids = [item.entry_id for item in search.items]
    started = perf_counter()
    entries = await read_entries(db, ctx, entry_ids)
    duration_ms = int((perf_counter() - started) * 1000)
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="read_entries",
        params={"entry_ids": entry_ids},
        result={
            "total": len(entries.items),
            "denied": len(entries.denied_entry_ids),
            "unavailable": len(entries.unavailable_entry_ids),
        },
        duration_ms=duration_ms,
    )
    await db.commit()
    if not entries.items:
        await _check_cancelled(run.id)
        await _build_output_version(
            db,
            run,
            decision,
            input_version=input_version,
            parent_seeds=working_set.items,
            cited_items=[],
            working_set_limit=settings.knowledge_agent_working_set_limit,
        )
        summary = await run_fallback_summary(db, run.id)
        await finalize_run(
            db,
            run,
            answer=_insufficient_answer(
                "检索到相关正式知识，但内容当前不可用，无法给出带引用的回答。",
                "Entry 内容不可用",
            ),
            status=RUN_PARTIAL,
            fallback_summary=summary,
        )
        return

    # 步骤 3：读取并核验有限数量的 Source/Attachment 证据（每轮重新生成当前 Run Evidence）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_READ_EVIDENCE)
    budget = settings.knowledge_agent_evidence_limit
    verified_evidence: list = []
    for item in entries.items:
        if budget <= 0:
            break
        source_ids = [source["source_id"] for source in item.sources]
        if not source_ids:
            continue
        started = perf_counter()
        evidence_result = await read_source_evidence(
            db,
            ctx,
            item.entry_id,
            source_ids[:budget],
        )
        duration_ms = int((perf_counter() - started) * 1000)
        budget -= len(source_ids[:budget])
        citable = [row for row in evidence_result.items if row.citable]
        unavailable = [row for row in evidence_result.items if not row.citable]
        await record_tool_result(
            db,
            run_id=run.id,
            tool_name="read_source_evidence",
            params={"entry_id": item.entry_id, "source_ids": source_ids},
            result={
                "total": len(evidence_result.items),
                "citable": len(citable),
                "denied": 0,
                "unavailable": len(unavailable),
            },
            duration_ms=duration_ms,
        )
        verified_evidence.extend(citable)
        if budget <= 0:
            break
    await db.commit()

    if not verified_evidence:
        await _check_cancelled(run.id)
        await _build_output_version(
            db,
            run,
            decision,
            input_version=input_version,
            parent_seeds=working_set.items,
            cited_items=[],
            working_set_limit=settings.knowledge_agent_working_set_limit,
        )
        summary = await run_fallback_summary(db, run.id)
        await finalize_run(
            db,
            run,
            answer=_insufficient_answer(
                "检索到相关正式知识，但其来源原文无法读取或核验，无法给出带引用的确定结论。",
                "没有可核验的 Source 证据",
            ),
            status=RUN_PARTIAL,
            fallback_summary=summary,
        )
        return

    # 步骤 4：组织回答（回答模型只接收句柄与核验原文，不接收历史回答）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_ORGANIZE_ANSWER)
    evidence_by_entry: dict[int, list] = {}
    for row in verified_evidence:
        evidence_by_entry.setdefault(row.entry_id, []).append(row)
    answer_entries: list[dict] = []
    entries_by_id: dict[int, object] = {}
    for item in entries.items:
        entries_by_id[item.entry_id] = item
        rows = evidence_by_entry.get(item.entry_id, [])
        if not rows:
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
                        "handle": row.evidence_handle,
                        "quote": row.quote,
                        "source_title": row.source_title,
                    }
                    for row in rows
                ],
            }
        )
    draft, answer_meta = await run_knowledge_answer_agent(
        db,
        run.workspace_id,
        decision.standalone_query or query,
        scope,
        answer_entries,
    )
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=answer_meta,
        prompt_version=ANSWER_PROMPT_VERSION,
    )
    await db.commit()

    # 步骤 5：服务端校验引用（只保留本 Run 可引用句柄）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_VALIDATE_REFERENCES)
    answer, ref_stats = await build_validated_answer(db, run.id, draft)
    factual_without_refs = not draft.insufficient and ref_stats.valid_count == 0
    if ref_stats.discarded_count > 0:
        await record_reference_validation(
            db,
            run.id,
            stats=ref_stats,
            note="部分引用被丢弃",
        )
    elif factual_without_refs:
        await record_reference_validation(
            db,
            run.id,
            stats=ref_stats,
            note="事实性回答没有有效引用",
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

    # 步骤 6：终态原子提交（回答 + Run 终态 + 活动槽释放 + 可选输出版本）
    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_FINALIZE)
    await _build_output_version(
        db,
        run,
        decision,
        input_version=input_version,
        parent_seeds=working_set.items,
        cited_items=cited_items,
        working_set_limit=settings.knowledge_agent_working_set_limit,
    )
    summary = await run_fallback_summary(db, run.id)
    await finalize_run(
        db,
        run,
        answer=answer,
        status=run_status,
        fallback_summary=summary,
    )
