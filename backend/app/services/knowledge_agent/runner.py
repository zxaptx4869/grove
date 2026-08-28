"""知识 Agent 固定执行图执行器：搜索 → 读 Entry → 读 Evidence → 组织回答 → 校验引用。"""

import logging
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge_agent import ANSWER_PROMPT_VERSION, run_knowledge_answer_agent
from app.core.config import get_settings
from app.models import KnowledgeAgentRun, KnowledgeMessage
from app.models.knowledge_agent import (
    RUN_COMPLETED,
    RUN_PARTIAL,
    RUN_PROCESSING,
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
from app.services.knowledge_agent.observability import (
    StageMeta,
    record_model_invocation,
    run_fallback_summary,
)
from app.services.knowledge_agent.runs import finalize_run
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    record_tool_result,
    search_confirmed_knowledge,
)

logger = logging.getLogger(__name__)


class RunCancelled(Exception):
    """Run 已被取消：模型结果不得写入正常回答。"""


async def _check_cancelled(db: AsyncSession, run_id: int) -> None:
    """步骤边界检查取消请求（从数据库重新读取，支持跨进程取消）。"""
    row = (
        await db.execute(
            select(KnowledgeAgentRun.cancel_requested, KnowledgeAgentRun.status).where(
                KnowledgeAgentRun.id == run_id
            )
        )
    ).first()
    if row is not None and row.cancel_requested and row.status == RUN_PROCESSING:
        raise RunCancelled()


def _insufficient_answer(text: str, note: str) -> KnowledgeAnswerOut:
    """确定性知识不足回答：不调用模型，不编造内容。"""
    return KnowledgeAnswerOut(
        answer=text,
        status="insufficient",
        insufficient_note=note,
    )


async def execute_run(db: AsyncSession, run: KnowledgeAgentRun) -> None:
    """执行一次 Run 的固定只读执行图，并在同一事务内提交终态。"""
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

    # 步骤 1：搜索正式知识（embedding + 重排阶段可观测）
    await _check_cancelled(db, run.id)
    run.current_step = STEP_SEARCH
    started = perf_counter()
    search = await search_confirmed_knowledge(
        db,
        ctx,
        query,
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
        params={"query": query[:200]},
        result={
            "total": len(search.items),
            "entry_ids": [item.entry_id for item in search.items],
        },
        duration_ms=duration_ms,
    )
    if not search.items:
        await _check_cancelled(db, run.id)
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
    await _check_cancelled(db, run.id)
    run.current_step = STEP_READ_ENTRIES
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
    if not entries.items:
        await _check_cancelled(db, run.id)
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

    # 步骤 3：读取并核验有限数量的 Source/Attachment 证据
    await _check_cancelled(db, run.id)
    run.current_step = STEP_READ_EVIDENCE
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

    if not verified_evidence:
        await _check_cancelled(db, run.id)
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

    # 步骤 4：组织回答（回答模型只接收句柄与核验原文）
    await _check_cancelled(db, run.id)
    run.current_step = STEP_ORGANIZE_ANSWER
    evidence_by_entry: dict[int, list] = {}
    for row in verified_evidence:
        evidence_by_entry.setdefault(row.entry_id, []).append(row)
    answer_entries: list[dict] = []
    for item in entries.items:
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
        query,
        scope,
        answer_entries,
    )
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=answer_meta,
        prompt_version=ANSWER_PROMPT_VERSION,
    )

    # 步骤 5：服务端校验引用（只保留本 Run 可引用句柄）
    await _check_cancelled(db, run.id)
    run.current_step = STEP_VALIDATE_REFERENCES
    answer = await build_validated_answer(db, run.id, draft)
    if answer_meta.is_fallback:
        answer = KnowledgeAnswerOut(
            answer=answer.answer,
            status="failed",
            insufficient_note=answer.insufficient_note or "回答模型不可用",
        )
    run_status = RUN_PARTIAL if answer_meta.is_fallback else RUN_COMPLETED

    # 步骤 6：终态原子提交
    await _check_cancelled(db, run.id)
    run.current_step = STEP_FINALIZE
    summary = await run_fallback_summary(db, run.id)
    await finalize_run(
        db,
        run,
        answer=answer,
        status=run_status,
        fallback_summary=summary,
    )
