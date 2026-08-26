"""候选与已有 Entry 的关系建议服务。"""

import json
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.relation import (
    EntryRevisionDraft,
    RelationDraft,
    RelationRecommendationDraft,
    run_relation_agent,
)
from app.models import Candidate, Entry, Node, Source
from app.models.extraction import (
    RELATION_CONFLICT,
    RELATION_DUPLICATE,
    RELATION_NEW,
    RELATION_PENDING,
    RELATION_SUPPLEMENT,
)
from app.services.extraction import get_active_candidates
from app.services.similarity import text_pair_similarity
from app.services.vector_search import hybrid_recall_for_candidate

logger = logging.getLogger(__name__)

# 关系判断阈值初值（保守区间，中间带交给 LLM）；待小样本标定后调整
RELATION_HIGH_SIMILARITY = 0.85
RELATION_LOW_SIMILARITY = 0.45


def retrieve_similar_entries(
    entries: list[Entry],
    candidate: Candidate,
    top_k: int = 5,
) -> list[Entry]:
    """从项目 Entry 中为候选返回 top-K 相似 Entry。"""
    scored: list[tuple[float, Entry]] = []
    for entry in entries:
        score = text_pair_similarity(
            candidate.title, candidate.content, entry.title, entry.content
        )
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:top_k]]


def _dump_revision_draft(draft: EntryRevisionDraft | None) -> str | None:
    """把修订草稿序列化为 JSON 文本。"""
    if draft is None:
        return None
    return json.dumps(draft.model_dump(), ensure_ascii=False)


def _apply_recommendation(
    candidate: Candidate,
    recommendation,
    valid_entry_ids: set[int],
) -> None:
    """校验关系建议并落库；非法结果降级为新知识。"""
    status = recommendation.relation_status
    target_id = recommendation.target_entry_id
    downgrade_reason: str | None = None

    if status not in {RELATION_NEW, RELATION_DUPLICATE, RELATION_SUPPLEMENT, RELATION_CONFLICT}:
        status = RELATION_NEW
        target_id = None
        downgrade_reason = "关系建议无效，按新知识处理"

    if status in {RELATION_DUPLICATE, RELATION_SUPPLEMENT, RELATION_CONFLICT}:
        if target_id is None or target_id not in valid_entry_ids:
            status = RELATION_NEW
            target_id = None
            downgrade_reason = "目标 Entry 无效，按新知识处理"

    if status == RELATION_SUPPLEMENT and recommendation.revision_draft is None:
        status = RELATION_DUPLICATE
        downgrade_reason = "缺少修订草稿，按补充来源处理"

    if status == RELATION_NEW:
        target_id = None

    candidate.relation_status = status
    candidate.relation_target_entry_id = target_id
    candidate.relation_reason = downgrade_reason or recommendation.reason or None
    candidate.revision_draft = (
        _dump_revision_draft(recommendation.revision_draft)
        if status in {RELATION_SUPPLEMENT, RELATION_CONFLICT}
        else None
    )


async def clear_candidate_relations(db: AsyncSession, source_id: int) -> None:
    """清除来源候选的旧关系建议并标记为待判断。"""
    await db.execute(
        update(Candidate)
        .where(Candidate.source_id == source_id)
        .values(
            relation_status=RELATION_PENDING,
            relation_target_entry_id=None,
            relation_reason=None,
            revision_draft=None,
        )
    )


async def route_relations(db: AsyncSession, source_id: int) -> None:
    """为来源的当前候选检索相似 Entry 并落库关系建议。"""
    source = await db.get(Source, source_id)
    if source is None or source.project_id is None:
        return

    candidates = await get_active_candidates(db, source_id)
    if not candidates:
        return

    entries = (
        await db.execute(select(Entry).where(Entry.project_id == source.project_id))
    ).scalars().all()
    if not entries:
        for candidate in candidates:
            candidate.relation_status = RELATION_NEW
            candidate.relation_target_entry_id = None
            candidate.relation_reason = None
            candidate.revision_draft = None
        return

    similar: dict[int, list[Entry]] = {}
    rule_decisions: list[RelationRecommendationDraft] = []
    llm_candidates: list[Candidate] = []
    for candidate in candidates:
        ranked = await hybrid_recall_for_candidate(
            db, source.workspace_id, candidate, entries, top_k=5
        )
        similar[candidate.id] = [entry for entry, _ in ranked]
        top_entry, top_cosine = ranked[0] if ranked else (None, None)
        if top_cosine is not None and top_entry is not None:
            if top_cosine >= RELATION_HIGH_SIMILARITY:
                rule_decisions.append(
                    RelationRecommendationDraft(
                        candidate_id=candidate.id,
                        relation_status=RELATION_DUPLICATE,
                        target_entry_id=top_entry.id,
                        reason=(
                            f"向量相似度 {top_cosine:.2f} ≥ 阈值"
                            f" {RELATION_HIGH_SIMILARITY}，规则判定重复"
                        ),
                    )
                )
                continue
            if top_cosine <= RELATION_LOW_SIMILARITY:
                rule_decisions.append(
                    RelationRecommendationDraft(
                        candidate_id=candidate.id,
                        relation_status=RELATION_NEW,
                        reason=(
                            f"向量相似度 {top_cosine:.2f} ≤ 阈值"
                            f" {RELATION_LOW_SIMILARITY}，规则判定新知识"
                        ),
                    )
                )
                continue
        llm_candidates.append(candidate)

    draft = RelationDraft(recommendations=list(rule_decisions))
    if llm_candidates:
        llm_similar = {
            candidate.id: similar.get(candidate.id, []) for candidate in llm_candidates
        }
        llm_draft = await run_relation_agent(
            db, source.workspace_id, llm_candidates, llm_similar
        )
        draft.recommendations.extend(llm_draft.recommendations)

    valid_entry_ids = {entry.id for entry in entries}
    by_id = {candidate.id: candidate for candidate in candidates}
    for recommendation in draft.recommendations:
        candidate = by_id.get(recommendation.candidate_id)
        if candidate is None:
            continue
        _apply_recommendation(candidate, recommendation, valid_entry_ids)


async def load_relation_targets(
    db: AsyncSession,
    candidates: list[Candidate],
) -> dict[int, tuple[str | None, str | None]]:
    """批量加载候选关系目标 Entry 的标题与目录名。"""
    target_ids = {
        candidate.relation_target_entry_id
        for candidate in candidates
        if candidate.relation_target_entry_id is not None
    }
    if not target_ids:
        return {}
    rows = await db.execute(
        select(Entry.id, Entry.title, Node.name)
        .join(Node, Entry.node_id == Node.id)
        .where(Entry.id.in_(target_ids))
    )
    return {entry_id: (title, node_name) for entry_id, title, node_name in rows}
