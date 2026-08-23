"""Entry 与来源证据 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, get_current_workspace
from app.models import Candidate, Entry, Node, Project, Source, Workspace
from app.schemas.entry import (
    AddEvidenceRequest,
    ApplyRevisionRequest,
    ApplyRevisionSuggestionRequest,
    ArchiveCandidateRequest,
    EntryOut,
    EntryUpdate,
    EntryVersionOut,
    NewNodeArchiveRequest,
    RestoreRequest,
    RevisionRefineRequest,
    RevisionSuggestionOut,
    RevisionSuggestionRequest,
)
from app.services.entry import (
    add_evidence_to_entry,
    apply_ai_revision_to_entry,
    apply_revision_to_entry,
    archive_candidate,
    archive_candidate_with_new_node,
    edit_entry,
    entry_eager_options,
    entry_out,
    entry_version_out_list,
    generate_revision_suggestion,
    list_entries_by_node,
    list_entry_versions,
    list_project_entries,
    refine_revision_suggestion,
    restore_entry_version,
)

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
            select(Entry)
            .options(*entry_eager_options())
            .where(Entry.id == entry_id)
            .execution_options(populate_existing=True)
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


@router.post(
    "/candidates/{candidate_id}/archive-with-new-node",
    response_model=EntryOut,
)
async def archive_candidate_with_new_node_endpoint(
    candidate_id: int,
    payload: NewNodeArchiveRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """创建或复用节点，并在同一事务内归档候选。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    entry = await archive_candidate_with_new_node(db, candidate, payload)
    await db.commit()
    return entry_out(entry)


@router.post(
    "/candidates/{candidate_id}/add-evidence",
    response_model=EntryOut,
)
async def add_evidence_endpoint(
    candidate_id: int,
    payload: AddEvidenceRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """把候选来源证据补充到已有 Entry。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    await _get_owned_entry(db, workspace.id, payload.entry_id)
    entry = await add_evidence_to_entry(db, candidate, payload.entry_id)
    await db.commit()
    return entry_out(entry)


@router.post(
    "/candidates/{candidate_id}/apply-revision",
    response_model=EntryOut,
)
async def apply_revision_endpoint(
    candidate_id: int,
    payload: ApplyRevisionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """把候选修订草稿应用到已有 Entry。"""
    candidate = await _get_owned_candidate(db, workspace.id, candidate_id)
    await _get_owned_entry(db, workspace.id, payload.entry_id)
    entry = await apply_revision_to_entry(db, candidate, payload)
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


@router.get("/entries/{entry_id}/versions", response_model=list[EntryVersionOut])
async def list_entry_versions_endpoint(
    entry_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[EntryVersionOut]:
    """返回 Entry 的保留版本快照列表（按版本号倒序）。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    versions = await list_entry_versions(db, entry.id)
    return await entry_version_out_list(db, versions)


@router.post("/entries/{entry_id}/restore", response_model=EntryOut)
async def restore_entry_endpoint(
    entry_id: int,
    payload: RestoreRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """把 Entry 恢复到指定版本，并追加恢复版本。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    await restore_entry_version(db, entry, payload.version_id)
    await db.commit()
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    return entry_out(entry)


@router.post(
    "/entries/{entry_id}/revision-suggestion",
    response_model=RevisionSuggestionOut,
)
async def revision_suggestion_endpoint(
    entry_id: int,
    payload: RevisionSuggestionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> RevisionSuggestionOut:
    """对单条 Entry 生成 AI 修订建议草稿。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    result = await generate_revision_suggestion(db, workspace.id, entry, payload)
    await db.commit()
    return result


@router.post(
    "/entries/{entry_id}/revision-suggestion/refine",
    response_model=RevisionSuggestionOut,
)
async def revision_suggestion_refine_endpoint(
    entry_id: int,
    payload: RevisionRefineRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> RevisionSuggestionOut:
    """基于完整对话历史与当前草稿继续调整修订建议。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    result = await refine_revision_suggestion(db, workspace.id, entry, payload)
    await db.commit()
    return result


@router.post(
    "/entries/{entry_id}/revision-suggestion/apply",
    response_model=EntryOut,
)
async def revision_suggestion_apply_endpoint(
    entry_id: int,
    payload: ApplyRevisionSuggestionRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EntryOut:
    """应用确认后的 AI 修订草稿并追加版本。"""
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    await apply_ai_revision_to_entry(db, entry, payload)
    await db.commit()
    entry = await _get_owned_entry(db, workspace.id, entry_id)
    return entry_out(entry)


@router.get("/projects/{project_id}/nodes/{node_id}/entries", response_model=list[EntryOut])
async def list_node_entries(
    project_id: int,
    node_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
    scope: str = "direct",
) -> list[EntryOut]:
    """返回某项目某节点下的 Entry（仅本节点、严格后代或包含子树）。"""
    if scope not in {"direct", "descendants", "subtree"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的知识范围")
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    node = await db.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")
    entries = await list_entries_by_node(db, project_id, node_id, scope)
    return [entry_out(entry) for entry in entries]


@router.get("/projects/{project_id}/entries", response_model=list[EntryOut])
async def list_all_project_entries(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[EntryOut]:
    """返回某项目全部已确认 Entry（思维导图项目总根使用）。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    entries = await list_project_entries(db, project_id)
    return [entry_out(entry) for entry in entries]
