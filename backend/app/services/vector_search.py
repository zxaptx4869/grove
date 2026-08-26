"""混合召回共享层：确定性召回 ∪ embedding 召回，RRF 融合排序。"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry
from app.services.embedding import encode_text
from app.services.similarity import text_pair_similarity
from app.services.vector_store import (
    cosine_similarity,
    entry_text,
    load_ready_vectors,
)

logger = logging.getLogger(__name__)

_RRF_K = 60
_EMBEDDING_RECALL_LIMIT = 30
_KEYWORD_BONUS = 60.0


def _keyword_hit(query: str, entry: Entry) -> bool:
    """判断查询是否作为子串命中 Entry 的关键字段（含目录与来源标题）。"""
    q = query.strip().casefold()
    if not q:
        return False
    fields = [entry.title, entry.content, entry.node.name, entry.node.description or ""]
    for evidence in entry.evidences:
        fields.append(evidence.source.title if evidence.source else "")
    return any(q in (field or "").casefold() for field in fields)


def _deterministic_by_query(entries: list[Entry], query: str) -> list[Entry]:
    """按查询与 Entry 的确定性相似度降序排序。"""
    scored: list[tuple[float, Entry]] = []
    for entry in entries:
        score = text_pair_similarity(query, "", entry.title, entry.content)
        if _keyword_hit(query, entry):
            score += _KEYWORD_BONUS
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored]


def _deterministic_by_target(target: Entry, others: list[Entry]) -> list[Entry]:
    """按锚点 Entry 与候选 Entry 的确定性相似度降序排序。"""
    scored: list[tuple[float, Entry]] = []
    for entry in others:
        score = text_pair_similarity(target.title, target.content, entry.title, entry.content)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored]


async def _embedding_scores(
    db: AsyncSession,
    workspace_id: int,
    entries: list[Entry],
    text: str,
) -> tuple[list[Entry], dict[int, float]]:
    """编码文本并返回范围内按余弦相似度降序的 Entry 与其相似度；embedding 不可用时为空。"""
    result = await encode_text(db, workspace_id, text)
    if result.is_fallback or result.vector is None:
        logger.info("embedding 不可用（%s），混合召回降级为确定性召回", result.error)
        return [], {}
    entry_ids = {entry.id for entry in entries}
    vectors = await load_ready_vectors(
        db, workspace_id, entry_ids=entry_ids, model=result.model
    )
    by_id = {entry.id: entry for entry in entries}
    scored: list[tuple[float, Entry]] = []
    for entry_id, vector in vectors:
        entry = by_id.get(entry_id)
        if entry is None:
            continue
        score = cosine_similarity(result.vector, vector)
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_entries = [entry for _, entry in scored[:_EMBEDDING_RECALL_LIMIT]]
    cosine_by_id = {entry.id: score for score, entry in scored}
    return top_entries, cosine_by_id


def _rrf_merge(*ranked_lists: list[Entry], top_k: int) -> list[Entry]:
    """对多路候选列表做 RRF 融合：score = Σ 1/(K + rank)。"""
    scores: dict[int, float] = {}
    by_id: dict[int, Entry] = {}
    for ranked in ranked_lists:
        for rank, entry in enumerate(ranked):
            scores[entry.id] = scores.get(entry.id, 0.0) + 1.0 / (_RRF_K + rank)
            by_id[entry.id] = entry
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [by_id[entry_id] for entry_id, _ in ordered[:top_k]]


async def hybrid_recall_by_query(
    db: AsyncSession,
    workspace_id: int,
    entries: list[Entry],
    query: str,
    top_k: int,
) -> list[Entry]:
    """语义搜索混合召回：确定性 ∪ embedding，embedding 不可用时降级纯确定性。"""
    deterministic = _deterministic_by_query(entries, query)
    embedding, _cosine = await _embedding_scores(db, workspace_id, entries, query)
    return _rrf_merge(deterministic, embedding, top_k=top_k)


async def hybrid_recall_by_target(
    db: AsyncSession,
    workspace_id: int,
    target: Entry,
    others: list[Entry],
    top_k: int,
) -> list[Entry]:
    """相似推荐混合召回：锚点 Entry 对比同项目其他 Entry。"""
    deterministic = _deterministic_by_target(target, others)
    embedding, _cosine = await _embedding_scores(
        db,
        workspace_id,
        others,
        entry_text(target),
    )
    return _rrf_merge(deterministic, embedding, top_k=top_k)


async def hybrid_recall_for_candidate(
    db: AsyncSession,
    workspace_id: int,
    candidate,
    entries: list[Entry],
    top_k: int,
) -> list[tuple[Entry, float | None]]:
    """关系判断混合召回：返回按融合排序的 (Entry, 向量相似度)；embedding 不可用时相似度为 None。"""
    deterministic = _deterministic_by_target(candidate, entries)
    embedding, cosine_by_id = await _embedding_scores(
        db,
        workspace_id,
        entries,
        f"{candidate.title or ''}\n{candidate.content or ''}",
    )
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    return [(entry, cosine_by_id.get(entry.id)) for entry in merged]
