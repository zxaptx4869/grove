"""语义检索服务：确定性召回 + 文本模型语义重排。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.semantic import SemanticRankingDraft, run_semantic_agent
from app.models import Entry, Node, Project
from app.services.entry import entry_eager_options
from app.services.similarity import text_pair_similarity

logger = logging.getLogger(__name__)

_RECALL_LIMIT = 20
_RESULT_LIMIT = 10
_KEYWORD_BONUS = 60.0


def _keyword_hit(query: str, entry: Entry) -> bool:
    """判断查询是否作为子串命中 Entry 的关键字段（含目录与来源标题）。"""
    q = query.strip().casefold()
    if not q:
        return False
    fields = [entry.title, entry.content, entry.node.name, entry.node.description or ""]
    for evidence in entry.evidences:
        fields.append(evidence.source.title or "")
    return any(q in (field or "").casefold() for field in fields)


def _recall_by_query(entries: list[Entry], query: str, top_k: int) -> list[Entry]:
    """按查询与 Entry 的确定性相似度召回 top-K 候选。"""
    scored: list[tuple[float, Entry]] = []
    for entry in entries:
        score = text_pair_similarity(query, "", entry.title, entry.content)
        if _keyword_hit(query, entry):
            score += _KEYWORD_BONUS
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


def _recall_by_target(target: Entry, others: list[Entry], top_k: int) -> list[Entry]:
    """按锚点 Entry 与候选 Entry 的确定性相似度召回 top-K 候选。"""
    scored: list[tuple[float, Entry]] = []
    for entry in others:
        score = text_pair_similarity(
            target.title, target.content, entry.title, entry.content
        )
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


async def _load_entries(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None = None,
) -> list[Entry]:
    """加载当前 Workspace（或指定项目）内的已确认 Entry。"""
    stmt = (
        select(Entry)
        .join(Node, Entry.node_id == Node.id)
        .join(Project, Entry.project_id == Project.id)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Project.workspace_id == workspace_id)
    )
    if project_id is not None:
        stmt = stmt.where(Entry.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _order_by_ranking(
    candidates: list[Entry],
    draft: SemanticRankingDraft,
    provider: str,
    model: str | None,
    is_fallback: bool,
    limit: int,
) -> list[tuple[Entry, str, str, str | None, bool]]:
    """按语义重排结果映射回 Entry，返回 (Entry, reason, provider, model, is_fallback)。"""
    by_id = {entry.id: entry for entry in candidates}
    ordered: list[tuple[Entry, str, str, str | None, bool]] = []
    for item in draft.results[:limit]:
        entry = by_id.get(item.entry_id)
        if entry is None:
            continue
        ordered.append((entry, item.reason, provider, model, is_fallback))
    return ordered


async def semantic_search_entries(
    db: AsyncSession,
    workspace_id: int,
    query: str,
    project_id: int | None = None,
) -> list[tuple[Entry, str, str, str | None, bool]]:
    """语义搜索：确定性召回 + 语义重排，返回 (Entry, reason, provider, model, is_fallback)。"""
    if not query.strip():
        return []
    entries = await _load_entries(db, workspace_id, project_id)
    candidates = _recall_by_query(entries, query, _RECALL_LIMIT)
    if not candidates:
        return []
    draft, provider, model, is_fallback = await run_semantic_agent(
        db, workspace_id, query, candidates
    )
    if is_fallback:
        logger.warning("语义搜索降级：provider=%s model=%s", provider, model)
    return _order_by_ranking(candidates, draft, provider, model, is_fallback, _RESULT_LIMIT)


async def recommend_similar_entries(
    db: AsyncSession,
    workspace_id: int,
    target: Entry,
) -> list[tuple[Entry, str, str, str | None, bool]]:
    """为指定 Entry 推荐同一项目内语义相关的其他 Entry。"""
    entries = await _load_entries(db, workspace_id, target.project_id)
    others = [entry for entry in entries if entry.id != target.id]
    if not others:
        return []
    candidates = _recall_by_target(target, others, _RECALL_LIMIT)
    if not candidates:
        return []
    query = f"{target.title}\n{target.content[:300]}"
    draft, provider, model, is_fallback = await run_semantic_agent(
        db, workspace_id, query, candidates
    )
    if is_fallback:
        logger.warning("相似推荐降级：provider=%s model=%s", provider, model)
    return _order_by_ranking(candidates, draft, provider, model, is_fallback, _RESULT_LIMIT)
