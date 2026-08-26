"""语义检索服务：确定性召回 + 文本模型语义重排。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.semantic import SemanticRankingDraft, run_semantic_agent
from app.models import Entry, Node, Project
from app.services.entry import entry_eager_options
from app.services.vector_search import hybrid_recall_by_query, hybrid_recall_by_target

logger = logging.getLogger(__name__)

_RECALL_LIMIT = 20
_RESULT_LIMIT = 10


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
    error: str | None,
    limit: int,
) -> list[tuple[Entry, str, str, str | None, bool, str | None]]:
    """按语义重排结果映射回 Entry，返回 (Entry, reason, provider, model, is_fallback, error)。"""
    by_id = {entry.id: entry for entry in candidates}
    ordered: list[tuple[Entry, str, str, str | None, bool, str | None]] = []
    for item in draft.results[:limit]:
        entry = by_id.get(item.entry_id)
        if entry is None:
            continue
        ordered.append((entry, item.reason, provider, model, is_fallback, error))
    return ordered


async def semantic_search_entries(
    db: AsyncSession,
    workspace_id: int,
    query: str,
    project_id: int | None = None,
) -> list[tuple[Entry, str, str, str | None, bool, str | None]]:
    """语义搜索：确定性召回 + 语义重排，返回含 provider/model/is_fallback/error 的结果。"""
    if not query.strip():
        return []
    entries = await _load_entries(db, workspace_id, project_id)
    candidates = await hybrid_recall_by_query(db, workspace_id, entries, query, _RECALL_LIMIT)
    if not candidates:
        return []
    draft, provider, model, is_fallback, error = await run_semantic_agent(
        db, workspace_id, query, candidates
    )
    if is_fallback:
        logger.warning("语义搜索降级：provider=%s model=%s error=%s", provider, model, error)
    return _order_by_ranking(
        candidates, draft, provider, model, is_fallback, error, _RESULT_LIMIT
    )


async def recommend_similar_entries(
    db: AsyncSession,
    workspace_id: int,
    target: Entry,
) -> list[tuple[Entry, str, str, str | None, bool, str | None]]:
    """为指定 Entry 推荐同一项目内语义相关的其他 Entry。"""
    entries = await _load_entries(db, workspace_id, target.project_id)
    others = [entry for entry in entries if entry.id != target.id]
    if not others:
        return []
    candidates = await hybrid_recall_by_target(db, workspace_id, target, others, _RECALL_LIMIT)
    if not candidates:
        return []
    query = f"{target.title}\n{target.content[:300]}"
    draft, provider, model, is_fallback, error = await run_semantic_agent(
        db, workspace_id, query, candidates
    )
    if is_fallback:
        logger.warning("相似推荐降级：provider=%s model=%s error=%s", provider, model, error)
    return _order_by_ranking(
        candidates, draft, provider, model, is_fallback, error, _RESULT_LIMIT
    )
