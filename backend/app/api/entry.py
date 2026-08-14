"""Entry 与来源证据 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, get_current_workspace
from app.models import Candidate, Entry, Node, Project, Source, Workspace
from app.schemas.entry import ArchiveCandidateRequest, EntryOut, EntryUpdate
from app.services.entry import archive_candidate, edit_entry, entry_out, list_entries_by_node

router = APIRouter(prefix="/api", tags=["entry"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


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


async def _get_owned_entry(db: DbSession, workspace_id: int, entry_id: int) -> Entry:
    entry = (
        await db.execute(
            select(Entry).options(selectinload(Entry.evidences)).where(Entry.id == entry_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry 不存在")
    project = await db.get(Project, entry.project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry 不存在")
    return entry


@router.post("/candidates/{candidate_id}/archive", response_model=EntryOut)
async def archive_candidate_endpoint(
    candidate_id: int,
    payload: ArchiveCandidateRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """采纳候选并归档为 Entry。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    entry = await archive_candidate(db, candidate, payload.node_id)
    await db.commit()
    return entry_out(entry)


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(
    entry_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """获取 Entry 详情与证据。"""
    return entry_out(await _get_owned_entry(db, workspace.id, entry_id))


@router.patch("/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: int,
    payload: EntryUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """编辑 Entry 或移动目录。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    await edit_entry(db, entry, payload)
    await db.commit()
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    return entry_out(entry)


@router.get("/projects/{project_id}/nodes/{node_id}/entries", response_model=list[EntryOut])
async def list_node_entries(
    project_id: int,
    node_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[EntryOut]:
    """返回某项目某节点下的 Entry。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    node = await db.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")
    entries = await list_entries_by_node(db, project_id, node_id)
    return [entry_out(entry) for entry in entries]
