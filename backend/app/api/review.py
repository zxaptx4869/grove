"""确认台 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select

from app.api.deps import DbSession, get_current_workspace
from app.models import Candidate, Project, Source, Workspace
from app.models.extraction import CANDIDATE_PENDING
from app.models.source import REVIEW_PARTIAL, REVIEW_PENDING
from app.schemas.candidate import CandidateOut
from app.schemas.review import (
    BatchCandidateDecisionRequest,
    BatchUpdateDirectoryRequest,
    BatchUpdateDirectoryResult,
    CandidateDecisionUpdate,
    CandidateUpdate,
    ProjectBatchDecisionRequest,
    ProjectBatchDecisionResult,
    ReviewCandidateOut,
    ReviewSourceOut,
)
from app.services.candidate_review import (
    batch_decide_candidates,
    batch_decide_project_candidates,
    batch_update_candidates_directory,
    decide_candidate,
    edit_candidate,
    list_project_review_candidates,
)
from app.services.extraction import candidate_out

router = APIRouter(prefix="/api", tags=["review"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _get_owned_project(db: DbSession, workspace_id: int, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


async def _get_owned_candidate(
    db: DbSession,
    workspace_id: int,
    candidate_id: int,
) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选不存在")
    source = await db.get(Source, candidate.source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选不存在")
    return candidate


async def _get_owned_source(db: DbSession, workspace_id: int, source_id: int) -> Source:
    source = await db.get(Source, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="来源不存在")
    return source


@router.get("/projects/{project_id}/review/sources", response_model=list[ReviewSourceOut])
async def list_review_sources(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[ReviewSourceOut]:
    """返回项目内待审 Source 及其候选计数。"""
    await _get_owned_project(db, workspace.id, project_id)
    pending_expr = func.sum(case((Candidate.status == CANDIDATE_PENDING, 1), else_=0))
    total_expr = func.count(Candidate.id)
    rows = (
        await db.execute(
            select(
                Source.id,
                Source.title,
                Source.note,
                Source.status,
                Source.created_at,
                pending_expr.label("pending_count"),
                total_expr.label("total_count"),
            )
            .join(Candidate, Candidate.source_id == Source.id)
            .where(Source.project_id == project_id)
            .group_by(Source.id)
            .having(pending_expr > 0)
            .order_by(Source.created_at.desc())
        )
    ).all()
    return [
        ReviewSourceOut(
            id=item.id,
            title=item.title,
            note=item.note,
            status=item.status,
            review_status=(
                REVIEW_PARTIAL
                if int(item.total_count) > int(item.pending_count or 0)
                else REVIEW_PENDING
            ),
            pending_candidate_count=int(item.pending_count or 0),
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.get(
    "/projects/{project_id}/review/candidates",
    response_model=list[ReviewCandidateOut],
)
async def list_review_candidates(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[ReviewCandidateOut]:
    """返回项目内全部待采纳候选（批量视图用）。"""
    await _get_owned_project(db, workspace.id, project_id)
    return await list_project_review_candidates(db, project_id)


@router.post(
    "/projects/{project_id}/review/candidates/batch-decision",
    response_model=list[ProjectBatchDecisionResult],
)
async def batch_decision_project_endpoint(
    project_id: int,
    payload: ProjectBatchDecisionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[ProjectBatchDecisionResult]:
    """对项目内选中候选执行批量确认或拒绝。"""
    await _get_owned_project(db, workspace.id, project_id)
    return await batch_decide_project_candidates(db, project_id, payload)


@router.post(
    "/projects/{project_id}/review/candidates/batch-update-directory",
    response_model=BatchUpdateDirectoryResult,
)
async def batch_update_directory_endpoint(
    project_id: int,
    payload: BatchUpdateDirectoryRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> BatchUpdateDirectoryResult:
    """把统一目录持久化到选中候选。"""
    await _get_owned_project(db, workspace.id, project_id)
    return await batch_update_candidates_directory(db, project_id, payload)


@router.patch("/candidates/{candidate_id}", response_model=CandidateOut)
async def update_candidate(
    candidate_id: int,
    payload: CandidateUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CandidateOut:
    """编辑候选字段。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    await edit_candidate(db, candidate, payload)
    await db.commit()
    return candidate_out(candidate)


@router.post("/candidates/{candidate_id}/decision", response_model=CandidateOut)
async def decide_candidate_endpoint(
    candidate_id: int,
    payload: CandidateDecisionUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> CandidateOut:
    """采纳、拒绝或重新打开候选。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    await decide_candidate(db, candidate, payload.status)
    await db.commit()
    return candidate_out(candidate)


@router.post(
    "/sources/{source_id}/candidates/batch-decision",
    response_model=list[CandidateOut],
)
async def batch_decision_endpoint(
    source_id: int,
    payload: BatchCandidateDecisionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[CandidateOut]:
    """批量采纳或拒绝同一 Source 内的候选。"""
    await _get_owned_source(db, workspace.id, source_id)
    candidates = await batch_decide_candidates(db, source_id, payload)
    await db.commit()
    return [candidate_out(candidate) for candidate in candidates]
