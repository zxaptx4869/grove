"""候选决策与编辑服务。"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, Node, Source
from app.models.extraction import (
    CANDIDATE_CONFIRMED,
    CANDIDATE_KIND_RECOMMENDED,
    CANDIDATE_PENDING,
    CANDIDATE_REJECTED,
    RELATION_NEW,
    RELATION_PENDING,
    ROUTING_RECOMMENDED,
)
from app.schemas.review import (
    BatchCandidateDecisionRequest,
    BatchUpdateDirectoryRequest,
    BatchUpdateDirectoryResult,
    CandidateUpdate,
    ProjectBatchDecisionRequest,
    ProjectBatchDecisionResult,
    ReviewCandidateOut,
)
from app.services.entry import archive_candidate
from app.services.entry_relation import load_relation_targets
from app.services.extraction import candidate_out, parse_risk_flags


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
    if decision_status == CANDIDATE_REJECTED and candidate.status != CANDIDATE_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选已处理，不能拒绝")
    if decision_status == CANDIDATE_PENDING and candidate.entry_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已归档候选不能重新打开")
    candidate.status = decision_status
    return candidate


async def batch_decide_candidates(
    db: AsyncSession,
    source_id: int,
    payload: BatchCandidateDecisionRequest,
) -> list[Candidate]:
    """对同一 Source 内的候选批量决策（仅保留拒绝语义，确认请走项目级接口）。"""
    if payload.status == CANDIDATE_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该接口已废弃确认语义，请使用项目级批量确认",
        )
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


def _review_band(candidate: Candidate) -> str:
    """按确定性规则分流快审/精审。"""
    if (
        candidate.candidate_kind == CANDIDATE_KIND_RECOMMENDED
        and candidate.routing_status == ROUTING_RECOMMENDED
        and candidate.recommended_node_id is not None
        and not parse_risk_flags(candidate.risk_flags)
        and candidate.relation_status in {RELATION_PENDING, RELATION_NEW}
    ):
        return "quick"
    return "detailed"


async def list_project_review_candidates(
    db: AsyncSession,
    project_id: int,
) -> list[ReviewCandidateOut]:
    """返回项目内全部待采纳候选及来源信息与分流标记。"""
    rows = (
        await db.execute(
            select(Candidate, Source.title, Source.note)
            .join(Source, Candidate.source_id == Source.id)
            .where(Source.project_id == project_id, Candidate.status == CANDIDATE_PENDING)
            .order_by(Candidate.id)
        )
    ).all()
    candidates = [candidate for candidate, _, _ in rows]
    targets = await load_relation_targets(db, candidates)
    return [
        ReviewCandidateOut(
            **candidate_out(candidate, *targets.get(candidate.id, (None, None))).model_dump(),
            source_title=source_title,
            source_note=source_note,
            review_band=_review_band(candidate),
            user_node_id=candidate.user_node_id,
        )
        for candidate, source_title, source_note in rows
    ]


async def batch_decide_project_candidates(
    db: AsyncSession,
    project_id: int,
    payload: ProjectBatchDecisionRequest,
) -> list[ProjectBatchDecisionResult]:
    """对项目内选中候选执行批量确认/拒绝，逐条返回结果。"""
    rows = (
        await db.execute(
            select(Candidate, Source)
            .join(Source, Candidate.source_id == Source.id)
            .where(Candidate.id.in_(payload.candidate_ids))
        )
    ).all()
    by_id = {
        candidate.id: candidate
        for candidate, source in rows
        if source.project_id == project_id
    }
    candidate_ids = list(dict.fromkeys(payload.candidate_ids))
    if len(by_id) != len(candidate_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="批量决策包含不属于当前项目的候选",
        )

    results: list[ProjectBatchDecisionResult] = []
    for candidate_id in candidate_ids:
        candidate = by_id[candidate_id]
        try:
            if payload.action == "reject":
                await decide_candidate(db, candidate, CANDIDATE_REJECTED)
                await db.commit()
                results.append(
                    ProjectBatchDecisionResult(candidate_id=candidate_id, status="rejected")
                )
                continue

            node_id = (
                payload.node_id
                if payload.node_id is not None
                else candidate.user_node_id or candidate.recommended_node_id
            )
            if node_id is None:
                raise ValueError("候选没有可归档目录，请先精审")
            await archive_candidate(db, candidate, node_id)
            await db.commit()
            results.append(
                ProjectBatchDecisionResult(candidate_id=candidate_id, status="confirmed")
            )
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            results.append(
                ProjectBatchDecisionResult(
                    candidate_id=candidate_id,
                    status="failed",
                    error=str(exc)[:200],
                )
            )
    return results


async def batch_update_candidates_directory(
    db: AsyncSession,
    project_id: int,
    payload: BatchUpdateDirectoryRequest,
) -> BatchUpdateDirectoryResult:
    """把统一目录持久化到选中候选，返回更新数量。"""
    rows = (
        await db.execute(
            select(Candidate, Source)
            .join(Source, Candidate.source_id == Source.id)
            .where(Candidate.id.in_(payload.candidate_ids))
        )
    ).all()
    by_id = {
        candidate.id: candidate
        for candidate, source in rows
        if source.project_id == project_id
    }
    candidate_ids = list(dict.fromkeys(payload.candidate_ids))
    if len(by_id) != len(candidate_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="批量更新目录包含不属于当前项目的候选",
        )
    for candidate_id in candidate_ids:
        if by_id[candidate_id].status != CANDIDATE_PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="批量更新目录包含已处理候选",
            )
    node = await db.get(Node, payload.node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="目录节点不属于当前项目",
        )
    for candidate_id in candidate_ids:
        by_id[candidate_id].user_node_id = payload.node_id
    await db.commit()
    return BatchUpdateDirectoryResult(updated=len(candidate_ids))
