"""Reader 问答服务：范围加载、证据召回、带引用回答与保存转候选。"""

import json
import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.reader import ReaderCitationDraft, run_reader_agent
from app.agents.semantic import run_semantic_agent
from app.models import Attachment, Candidate, Entry, Extraction, Node, Project, Source
from app.models.extraction import (
    CANDIDATE_KIND_RECOMMENDED,
    CANDIDATE_PENDING,
    EXTRACTION_ACTIVE,
)
from app.schemas.candidate import CandidateOut
from app.schemas.reader import (
    ReaderAnswerOut,
    ReaderAskRequest,
    ReaderCitationOut,
    ReaderConflictOut,
    ReaderSaveRequest,
)
from app.services.entry import entry_eager_options, list_entries_by_node
from app.services.extraction import candidate_out
from app.services.project_context import get_project_context_out
from app.services.semantic_search import _recall_by_query

logger = logging.getLogger(__name__)

_RECALL_LIMIT = 20
_CONTEXT_LIMIT = 15


async def _load_scope_entries(
    db: AsyncSession,
    project_id: int,
    node_id: int | None,
) -> list[Entry]:
    """加载问答范围内的已确认 Entry（节点子树或项目全部）。"""
    if node_id is not None:
        direct = await list_entries_by_node(db, project_id, node_id, "direct")
        descendants = await list_entries_by_node(db, project_id, node_id, "descendants")
        return direct + descendants
    result = await db.execute(
        select(Entry)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Entry.project_id == project_id)
    )
    return list(result.scalars().all())


async def _project_context_text(db: AsyncSession, workspace_id: int, project_id: int) -> str:
    """把项目上下文快照组装为 Reader 的文本输入。"""
    context = await get_project_context_out(db, workspace_id, project_id)
    parts: list[str] = []
    if context.project_summary:
        parts.append(f"项目概要：{context.project_summary}")
    if context.current_focus:
        parts.append(f"当前关注：{context.current_focus}")
    if context.directory_topics:
        parts.append(f"目录主题：{'、'.join(context.directory_topics)}")
    if context.recent_themes:
        parts.append(f"近期主题：{'、'.join(context.recent_themes)}")
    return "；".join(parts)


def _top_entries(candidates: list[Entry], draft, limit: int) -> list[Entry]:
    """按语义重排结果顺序取前 limit 条 Entry。"""
    by_id = {entry.id: entry for entry in candidates}
    ordered: list[Entry] = []
    seen: set[int] = set()
    for item in draft.results:
        entry = by_id.get(item.entry_id)
        if entry is not None and entry.id not in seen:
            ordered.append(entry)
            seen.add(entry.id)
        if len(ordered) >= limit:
            break
    for entry in candidates:
        if entry.id not in seen:
            ordered.append(entry)
            seen.add(entry.id)
        if len(ordered) >= limit:
            break
    return ordered


def _validate_citations(
    citations: list[ReaderCitationDraft],
    entries: list[Entry],
) -> list[ReaderCitationOut]:
    """保留属于范围内 Entry 且来源有效的引用，丢弃非法引用。"""
    entry_by_id = {entry.id: entry for entry in entries}
    validated: list[ReaderCitationOut] = []
    for citation in citations:
        entry = entry_by_id.get(citation.entry_id)
        if entry is None:
            continue
        evidence = next(
            (item for item in entry.evidences if item.source_id == citation.source_id),
            None,
        )
        if evidence is None:
            continue
        validated.append(
            ReaderCitationOut(
                entry_id=entry.id,
                entry_title=entry.title,
                source_id=evidence.source_id,
                source_title=evidence.source.title or "未命名来源",
                quote=citation.quote or evidence.quote or "",
            )
        )
    return validated


async def ask_reader(
    db: AsyncSession,
    workspace_id: int,
    project_id: int,
    request: ReaderAskRequest,
) -> ReaderAnswerOut:
    """执行一次问答：范围加载 → 证据召回 → Reader 生成 → 引用校验。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    node_id = request.node_id if request.scope == "node" else None
    node: Node | None = None
    if node_id is not None:
        node = await db.get(Node, node_id)
        if node is None or node.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")

    entries = await _load_scope_entries(db, project_id, node_id)
    if not entries:
        return ReaderAnswerOut(
            answer="当前问答范围内还没有已确认的正式知识。",
            insufficient=True,
            insufficient_note="范围内没有已确认 Entry",
        )

    candidates = _recall_by_query(entries, request.message, _RECALL_LIMIT)
    if not candidates:
        return ReaderAnswerOut(
            answer="当前问答范围内没有与问题相关的已确认知识。",
            insufficient=True,
            insufficient_note="没有召回相关 Entry",
        )

    draft, _provider, _model, _is_fallback, _error = await run_semantic_agent(
        db, workspace_id, request.message, candidates
    )
    context_entries = _top_entries(candidates, draft, _CONTEXT_LIMIT)

    scope_label = f"节点「{node.name}」及其子树" if node is not None else "整个项目"
    project_context_text = None
    if node_id is None:
        project_context_text = await _project_context_text(db, workspace_id, project_id)

    answer_draft, provider, model, is_fallback, error = await run_reader_agent(
        db,
        workspace_id,
        request.message,
        scope_label,
        context_entries,
        project_context_text,
    )

    citations = _validate_citations(answer_draft.citations, entries)
    valid_entry_ids = {entry.id for entry in entries}

    conflicts = [
        ReaderConflictOut(
            entry_id_a=item.entry_id_a,
            entry_id_b=item.entry_id_b,
            summary=item.summary,
        )
        for item in answer_draft.conflicts
        if item.entry_id_a in valid_entry_ids and item.entry_id_b in valid_entry_ids
    ]

    return ReaderAnswerOut(
        answer=answer_draft.answer,
        citations=citations,
        insufficient=answer_draft.insufficient,
        insufficient_note=answer_draft.insufficient_note,
        conflicts=conflicts,
        provider=provider,
        model=model,
        is_fallback=is_fallback,
        error=error,
    )


async def save_answer_as_candidate(
    db: AsyncSession,
    workspace_id: int,
    project_id: int,
    request: ReaderSaveRequest,
) -> CandidateOut:
    """校验引用并创建虚拟 Source、Extraction 与待采纳 Candidate。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    entry_ids = [citation.entry_id for citation in request.citations]
    entry_by_id: dict[int, Entry] = {}
    if entry_ids:
        rows = (
            await db.execute(
                select(Entry)
                .options(selectinload(Entry.evidences))
                .where(Entry.project_id == project_id, Entry.id.in_(entry_ids))
            )
        ).scalars().all()
        entry_by_id = {entry.id: entry for entry in rows}
        if len(entry_by_id) != len(set(entry_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="引用包含无效或越权的 Entry",
            )

    source_title = f"AI 阅读问答：{(request.question or '').strip()[:40]}" or "AI 阅读问答"
    source = Source(
        workspace_id=workspace_id,
        project_id=project_id,
        title=source_title[:255],
        note=request.question.strip(),
    )
    db.add(source)
    await db.flush()
    attachment = Attachment(
        source_id=source.id,
        kind="text",
        position=0,
        text_content=request.content,
    )
    db.add(attachment)
    await db.flush()

    extraction = Extraction(
        source_id=source.id,
        provider="reader",
        model="reader",
        prompt_version="v1",
        status=EXTRACTION_ACTIVE,
        discarded_count=0,
    )
    db.add(extraction)
    await db.flush()

    evidence_refs: list[dict] = []
    for citation in request.citations:
        entry = entry_by_id[citation.entry_id]
        evidence = next(
            (item for item in entry.evidences if item.source_id == citation.source_id),
            None,
        )
        if evidence is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="引用包含无效的来源",
            )
        evidence_refs.append(
            {
                "attachment_id": evidence.attachment_id,
                "quote": citation.quote or evidence.quote or "",
            }
        )

    candidate = Candidate(
        extraction_id=extraction.id,
        source_id=source.id,
        candidate_kind=CANDIDATE_KIND_RECOMMENDED,
        title=request.title,
        content=request.content,
        main_type="knowledge",
        info_nature=None,
        applicable_condition=None,
        note=None,
        evidence_refs=json.dumps(evidence_refs, ensure_ascii=False),
        reason="来自 AI 阅读回答",
        risk_flags="[]",
        status=CANDIDATE_PENDING,
    )
    db.add(candidate)
    await db.flush()
    return candidate_out(candidate)
