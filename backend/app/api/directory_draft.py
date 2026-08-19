"""Directory Draft 起草 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DbSession, get_current_workspace
from app.models import Node, Project, Workspace
from app.models.directory_draft import DirectoryDraft
from app.schemas.directory_draft import (
    ClarifySubmitRequest,
    DraftApplyRequest,
    DraftCreateRequest,
    DraftMessageSubmitRequest,
    DraftNodeInput,
    DraftNodesUpdateRequest,
    DraftOut,
    ExpandRequest,
)
from app.services.directory_draft import (
    apply_draft,
    create_or_reuse_draft,
    create_or_reuse_expand_draft,
    discard_draft,
    draft_out,
    expansion_diff,
    get_active_draft,
    list_draft_messages,
    submit_clarify_answers,
    submit_draft_message,
    update_draft_nodes,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/directory-draft",
    tags=["directory-draft"],
)
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _get_owned_project(db: DbSession, workspace_id: int, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


async def _load_out(db: DbSession, draft: DirectoryDraft) -> DraftOut:
    from app.models.directory_draft import DirectoryDraftNode

    await db.refresh(draft)
    nodes = (
        await db.execute(
            select(DirectoryDraftNode).where(DirectoryDraftNode.draft_id == draft.id)
        )
    ).scalars().all()
    messages = await list_draft_messages(db, draft.id)
    diff = await expansion_diff(db, draft) if draft.kind == "expand" else []
    return draft_out(draft, list(nodes), messages, diff=diff)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DraftOut)
async def create_draft_endpoint(
    project_id: int,
    payload: DraftCreateRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """创建或复用活跃草稿并执行首次澄清/起草步骤。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    draft = await create_or_reuse_draft(db, project)
    await db.commit()
    return await _load_out(db, draft)


@router.get("", response_model=DraftOut)
async def get_draft_endpoint(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """读取活跃草稿。"""
    await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    return await _load_out(db, draft)


@router.post("/expand", status_code=status.HTTP_201_CREATED, response_model=DraftOut)
async def create_expand_draft_endpoint(
    project_id: int,
    payload: ExpandRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """创建或复用活跃草稿并发起节点拓展。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    node = await db.get(Node, payload.node_id)
    if node is None or node.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")
    draft = await create_or_reuse_expand_draft(db, project, node)
    await db.commit()
    return await _load_out(db, draft)


@router.post("/clarify", response_model=DraftOut)
async def submit_clarify_endpoint(
    project_id: int,
    payload: ClarifySubmitRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """提交澄清答案并生成候选树。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    draft = await submit_clarify_answers(db, draft, project, payload.answers)
    await db.commit()
    return await _load_out(db, draft)


@router.patch("/nodes", response_model=DraftOut)
async def update_nodes_endpoint(
    project_id: int,
    payload: DraftNodesUpdateRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """内联编辑草稿节点树。"""
    await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    roots: list[DraftNodeInput] = payload.nodes
    draft = await update_draft_nodes(db, draft, roots)
    await db.commit()
    return await _load_out(db, draft)


@router.post("/apply", response_model=DraftOut)
async def apply_draft_endpoint(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
    payload: DraftApplyRequest | None = None,
) -> DraftOut:
    """确认应用草稿为正式目录。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    draft = await apply_draft(
        db,
        draft,
        project,
        removed_node_ids=payload.removed_node_ids if payload else [],
    )
    await db.commit()
    return await _load_out(db, draft)


@router.post("/discard", response_model=DraftOut)
async def discard_draft_endpoint(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """丢弃草稿。"""
    await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    draft = await discard_draft(db, draft)
    await db.commit()
    return await _load_out(db, draft)


@router.post("/messages", response_model=DraftOut)
async def submit_message_endpoint(
    project_id: int,
    payload: DraftMessageSubmitRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> DraftOut:
    """发送对话调整消息，返回更新后的草稿与消息。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    draft = await get_active_draft(db, project_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    draft = await submit_draft_message(db, draft, project, payload.content)
    await db.commit()
    return await _load_out(db, draft)
