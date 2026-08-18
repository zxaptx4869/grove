"""候选与已有 Entry 的关系建议服务。"""

import json
import logging
import re

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.relation import EntryRevisionDraft, run_relation_agent
from app.models import Candidate, Entry, Node, Source
from app.models.extraction import (
    RELATION_CONFLICT,
    RELATION_DUPLICATE,
    RELATION_NEW,
    RELATION_PENDING,
    RELATION_SUPPLEMENT,
)
from app.services.extraction import get_active_candidates

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize(value: str) -> str:
    """归一化文本：去空白/标点并转小写。"""
    return _PUNCT_RE.sub("", value).casefold()


def _bigrams(value: str) -> set[str]:
    """提取字符 bigram 集合。"""
    normalized = _normalize(value)
    return {normalized[i : i + 2] for i in range(max(0, len(normalized) - 1))}


def _overlap(left: set[str], right: set[str]) -> float:
    """计算两个集合的 Jaccard 重叠。"""
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _similarity_score(candidate: Candidate, entry: Entry) -> float:
    """计算候选与 Entry 的确定性相似度。"""
    candidate_title = _normalize(candidate.title)
    entry_title = _normalize(entry.title)
    score = 0.0
    if candidate_title and candidate_title == entry_title:
        score += 100
    elif candidate_title and entry_title and (
        candidate_title in entry_title or entry_title in candidate_title
    ):
        score += 40

    score += _overlap(_bigrams(candidate.title), _bigrams(entry.title)) * 30
    score += _overlap(_bigrams(candidate.content), _bigrams(entry.content)) * 20
    return score


def retrieve_similar_entries(
    entries: list[Entry],
    candidate: Candidate,
    top_k: int = 5,
) -> list[Entry]:
    """从项目 Entry 中为候选返回 top-K 相似 Entry。"""
    scored = [
        (score, entry)
        for entry in entries
        if (score := _similarity_score(candidate, entry)) > 0
    ]
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

    similar = {
        candidate.id: retrieve_similar_entries(entries, candidate)
        for candidate in candidates
    }
    draft = await run_relation_agent(db, source.workspace_id, candidates, similar)
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
