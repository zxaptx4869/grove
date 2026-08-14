"""关键词搜索 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_workspace
from app.models import Project, Workspace
from app.schemas.search import SearchEntryOut
from app.services.entry import entry_out
from app.services.search import search_entries

router = APIRouter(prefix="/api", tags=["search"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


@router.get("/search", response_model=list[SearchEntryOut])
async def search_endpoint(
    q: str,
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
) -> list[SearchEntryOut]:
    """项目内或全局关键词搜索。"""
    if project_id is not None:
        project = await db.get(Project, project_id)
        if project is None or project.workspace_id != workspace.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    entries = await search_entries(db, workspace.id, q, project_id)
    return [
        SearchEntryOut(
            **entry_out(entry).model_dump(),
            project_name=entry.project.name,
        )
        for entry in entries
    ]
