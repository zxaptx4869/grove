"""混合召回共享层：确定性召回 ∪ embedding 召回，RRF 融合排序。"""

import logging
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry
from app.models.knowledge_agent import PURPOSE_EMBEDDING
from app.services.embedding import encode_text
from app.services.knowledge_agent.observability import StageMeta
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
        # 查询作为问题文本时可能同时命中标题与正文：分别按「标题 vs 标题」和
        # 「正文 vs 正文」比较并取更优，避免自然语言问题只能匹配标题。
        score = max(
            text_pair_similarity(query, "", entry.title, ""),
            text_pair_similarity("", query, "", entry.content),
        )
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
) -> tuple[list[Entry], dict[int, float], StageMeta]:
    """编码文本并返回范围内按余弦相似度降序的 Entry、相似度与阶段元数据。"""
    started = perf_counter()
    result = await encode_text(db, workspace_id, text)
    meta = StageMeta(
        purpose=PURPOSE_EMBEDDING,
        provider=result.provider,
        model=result.model,
        is_fallback=result.is_fallback,
        error=result.error,
        duration_ms=int((perf_counter() - started) * 1000),
    )
    if result.is_fallback or result.vector is None:
        logger.debug("embedding 不可用（%s），混合召回降级为确定性召回", result.error)
        return [], {}, meta
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
    return top_entries, cosine_by_id, meta


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
    *,
    return_scores: bool = False,
) -> list[Entry] | tuple[list[Entry], dict[int, float]]:
    """语义搜索混合召回：确定性 ∪ embedding，embedding 不可用时降级纯确定性。"""
    deterministic = _deterministic_by_query(entries, query)
    embedding, cosine, _meta = await _embedding_scores(db, workspace_id, entries, query)
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    if return_scores:
        return merged, cosine
    return merged


async def hybrid_recall_by_query_with_meta(
    db: AsyncSession,
    workspace_id: int,
    entries: list[Entry],
    query: str,
    top_k: int,
) -> tuple[list[Entry], dict[int, float], StageMeta]:
    """语义搜索混合召回（带 embedding 阶段元数据），供知识 Agent 可观测性使用。"""
    deterministic = _deterministic_by_query(entries, query)
    embedding, cosine, meta = await _embedding_scores(db, workspace_id, entries, query)
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    return merged, cosine, meta


async def hybrid_recall_by_target(
    db: AsyncSession,
    workspace_id: int,
    target: Entry,
    others: list[Entry],
    top_k: int,
    *,
    return_scores: bool = False,
) -> list[Entry] | tuple[list[Entry], dict[int, float]]:
    """相似推荐混合召回：锚点 Entry 对比同项目其他 Entry。"""
    deterministic = _deterministic_by_target(target, others)
    embedding, cosine, _meta = await _embedding_scores(
        db,
        workspace_id,
        others,
        entry_text(target),
    )
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    if return_scores:
        return merged, cosine
    return merged


async def hybrid_recall_by_target_with_meta(
    db: AsyncSession,
    workspace_id: int,
    target: Entry,
    others: list[Entry],
    top_k: int,
) -> tuple[list[Entry], dict[int, float], StageMeta]:
    """相似推荐混合召回（带 embedding 阶段元数据）。"""
    deterministic = _deterministic_by_target(target, others)
    embedding, cosine, meta = await _embedding_scores(
        db,
        workspace_id,
        others,
        entry_text(target),
    )
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    return merged, cosine, meta


async def hybrid_recall_for_candidate(
    db: AsyncSession,
    workspace_id: int,
    candidate,
    entries: list[Entry],
    top_k: int,
) -> tuple[list[tuple[Entry, float | None]], tuple[Entry, float] | None]:
    """关系判断混合召回：返回 (按融合排序的 (Entry, 向量相似度), 余弦最高的 Entry)。

    阈值规则应基于「候选集内最大余弦」判定，而不是 RRF 融合第一名的余弦；
    embedding 不可用时最大余弦为 None。
    """
    deterministic = _deterministic_by_target(candidate, entries)
    embedding, cosine_by_id, _meta = await _embedding_scores(
        db,
        workspace_id,
        entries,
        f"{candidate.title or ''}\n{candidate.content or ''}",
    )
    merged = _rrf_merge(deterministic, embedding, top_k=top_k)
    ranked = [(entry, cosine_by_id.get(entry.id)) for entry in merged]
    by_id = {entry.id: entry for entry in entries}
    best: tuple[Entry, float] | None = None
    for entry_id, score in cosine_by_id.items():
        entry = by_id.get(entry_id)
        if entry is None:
            continue
        if best is None or score > best[1]:
            best = (entry, score)
    return ranked, best
