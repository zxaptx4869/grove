"""语义检索 API：语义搜索与相似知识推荐。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DbSession, get_current_workspace
from app.models import Entry, Project, Workspace
from app.schemas.semantic_search import SemanticEntryOut
from app.services.entry import entry_out
from app.services.semantic_search import recommend_similar_entries, semantic_search_entries

router = APIRouter(prefix="/api", tags=["semantic-search"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


def _to_response(
    results: list[tuple[Entry, str, str, str | None, bool, str | None]],
) -> list[SemanticEntryOut]:
    """把语义检索结果组装为响应模型。"""
    return [
        SemanticEntryOut(
            **entry_out(entry).model_dump(),
            project_name=entry.project.name,
            reason=reason,
            provider=provider,
            model=model,
            error=error,
            is_fallback=is_fallback,
        )
        for entry, reason, provider, model, is_fallback, error in results
    ]


@router.get("/semantic-search", response_model=list[SemanticEntryOut])
async def semantic_search_endpoint(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
) -> list[SemanticEntryOut]:
    """项目内或全局语义搜索。"""
    if project_id is not None:
        project = await db.get(Project, project_id)
        if project is None or project.workspace_id != workspace.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    results = await semantic_search_entries(db, workspace.id, q, project_id)
    return _to_response(results)


@router.get("/entries/{entry_id}/similar", response_model=list[SemanticEntryOut])
async def similar_entries_endpoint(
    entry_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[SemanticEntryOut]:
    """返回某 Entry 同一项目内的相似知识推荐。"""
    target = await db.get(Entry, entry_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry 不存在")
    project = await db.get(Project, target.project_id)
    if project is None or project.workspace_id != workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry 不存在")

    results = await recommend_similar_entries(db, workspace.id, target)
    return _to_response(results)
