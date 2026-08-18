"""项目上下文 API：查询、纠正与手动重新生成。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_workspace
from app.models import Project, Workspace
from app.schemas.project_context import ProjectContextCorrectionUpdate, ProjectContextOut
from app.services.project_context import (
    apply_corrections,
    get_project_context_out,
    refresh_project_context,
)

router = APIRouter(prefix="/api/projects", tags=["project-context"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _get_owned_project(db: DbSession, workspace_id: int, project_id: int) -> Project:
    """按 Workspace 归属获取项目，不存在或越权返回 404。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("/{project_id}/context", response_model=ProjectContextOut)
async def get_project_context(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectContextOut:
    """返回项目上下文快照（公共上下文接口）。"""
    result = await get_project_context_out(db, workspace.id, project_id)
    await db.commit()
    return result


@router.patch("/{project_id}/context", response_model=ProjectContextOut)
async def correct_project_context(
    project_id: int,
    payload: ProjectContextCorrectionUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectContextOut:
    """保存用户纠正并安排防抖刷新。"""
    await _get_owned_project(db, workspace.id, project_id)
    await apply_corrections(db, project_id, payload)
    await db.commit()
    return await get_project_context_out(db, workspace.id, project_id)


@router.post("/{project_id}/context/refresh", response_model=ProjectContextOut)
async def regenerate_project_context(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectContextOut:
    """手动重新生成项目上下文并返回最新快照。"""
    await _get_owned_project(db, workspace.id, project_id)
    await refresh_project_context(db, project_id, "manual_refresh")
    await db.commit()
    return await get_project_context_out(db, workspace.id, project_id)
