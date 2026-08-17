"""候选决策与编辑服务。"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate
from app.models.extraction import (
    CANDIDATE_CONFIRMED,
    CANDIDATE_PENDING,
    CANDIDATE_REJECTED,
)
from app.schemas.review import BatchCandidateDecisionRequest, CandidateUpdate


async def edit_candidate(
    db: AsyncSession,
    candidate: Candidate,
    payload: CandidateUpdate,
) -> Candidate:
    """编辑候选字段；字段缺失表示不修改。"""
    fields = payload.model_fields_set
    if "title" in fields and payload.title is not None:
        candidate.title = payload.title
    if "content" in fields and payload.content is not None:
        candidate.content = payload.content
    if "main_type" in fields and payload.main_type is not None:
        candidate.main_type = payload.main_type
    if "info_nature" in fields:
        candidate.info_nature = payload.info_nature
    if "applicable_condition" in fields:
        candidate.applicable_condition = payload.applicable_condition
    if "note" in fields:
        candidate.note = payload.note
    return candidate


async def decide_candidate(
    db: AsyncSession,
    candidate: Candidate,
    decision_status: str,
) -> Candidate:
    """对单条候选执行决策并重算 Source 审阅状态。"""
    if decision_status not in {CANDIDATE_PENDING, CANDIDATE_CONFIRMED, CANDIDATE_REJECTED}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的决策状态")
    if decision_status == CANDIDATE_PENDING and candidate.entry_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档候选不能重新打开")
    candidate.status = decision_status
    return candidate


async def batch_decide_candidates(
    db: AsyncSession,
    source_id: int,
    payload: BatchCandidateDecisionRequest,
) -> list[Candidate]:
    """对同一 Source 内的候选批量决策。"""
    candidates = (
        await db.execute(
            select(Candidate).where(
                Candidate.source_id == source_id,
                Candidate.id.in_(payload.candidate_ids),
            )
        )
    ).scalars().all()
    if len(candidates) != len(set(payload.candidate_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="批量决策包含不属于当前来源的候选",
        )
    for candidate in candidates:
        candidate.status = payload.status
    return list(candidates)
