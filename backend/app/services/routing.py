"""候选目录推荐（路由）服务。"""

import json
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.organizing import NodeAlternativeDraft, NodeRecommendationDraft, run_routing_agent
from app.models import Candidate, Node, Source
from app.models.extraction import (
    ROUTING_NEEDS_REVIEW,
    ROUTING_NO_SUITABLE,
    ROUTING_PENDING,
    ROUTING_RECOMMENDED,
)
from app.services.extraction import get_active_candidates

logger = logging.getLogger(__name__)


def _dump_alternatives(alternatives: list[NodeAlternativeDraft]) -> str | None:
    if not alternatives:
        return None
    return json.dumps(
        [item.model_dump() for item in alternatives],
        ensure_ascii=False,
    )


async def clear_candidate_routing(db: AsyncSession, source_id: int) -> None:
    """清除来源候选的旧目录推荐并标记为待路由。"""
    await db.execute(
        update(Candidate)
        .where(Candidate.source_id == source_id)
        .values(
            recommended_node_id=None,
            node_alternatives=None,
            node_reason=None,
            routing_status=ROUTING_PENDING,
        )
    )


async def route_source(db: AsyncSession, source_id: int) -> None:
    """为来源的当前候选计算并落库目录推荐。"""
    source = await db.get(Source, source_id)
    if source is None or source.project_id is None:
        return

    candidates = await get_active_candidates(db, source_id)
    if not candidates:
        return

    nodes = (
        await db.execute(
            select(Node)
            .where(Node.project_id == source.project_id)
            .order_by(Node.position)
        )
    ).scalars().all()
    node_ids = {node.id for node in nodes}

    draft = await run_routing_agent(db, source.workspace_id, candidates, list(nodes))
    by_id = {candidate.id: candidate for candidate in candidates}
    for recommendation in draft.recommendations:
        candidate = by_id.get(recommendation.candidate_id)
        if candidate is None:
            continue
        await _apply_recommendation(candidate, recommendation, node_ids)


async def _apply_recommendation(
    candidate: Candidate,
    recommendation: NodeRecommendationDraft,
    node_ids: set[int],
) -> None:
    """校验推荐并落库；非法主建议降级为需要确认或暂无合适位置。"""
    valid_alternatives = [
        item for item in recommendation.node_alternatives if item.node_id in node_ids
    ]
    candidate.node_alternatives = _dump_alternatives(valid_alternatives)

    if recommendation.recommended_node_id in node_ids:
        candidate.recommended_node_id = recommendation.recommended_node_id
        candidate.node_reason = recommendation.node_reason
        candidate.routing_status = (
            recommendation.routing_status
            if recommendation.routing_status in {ROUTING_RECOMMENDED, ROUTING_NEEDS_REVIEW}
            else ROUTING_RECOMMENDED
        )
    else:
        candidate.recommended_node_id = None
        candidate.node_reason = None
        candidate.routing_status = (
            ROUTING_NEEDS_REVIEW if valid_alternatives else ROUTING_NO_SUITABLE
        )
