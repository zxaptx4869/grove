"""候选查询 API（本轮只读）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_workspace
from app.models import Source, Workspace
from app.schemas.candidate import CandidateOut
from app.services.extraction import list_candidate_out

router = APIRouter(prefix="/api/sources", tags=["candidates"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _get_owned_source(db: DbSession, workspace_id: int, source_id: int) -> Source:
    """按 Workspace 归属获取 Source，不存在或越权返回 404。"""
    source = await db.get(Source, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="来源不存在")
    return source


@router.get("/{source_id}/candidates", response_model=list[CandidateOut])
async def list_candidates(
    source_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[CandidateOut]:
    """返回当前 active Extraction 的候选。"""
    await _get_owned_source(db, workspace.id, source_id)
    return await list_candidate_out(db, source_id)
