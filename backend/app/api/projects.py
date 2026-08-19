"""项目与目录树 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DbSession, get_current_workspace
from app.models import Entry, Node, Project, Source, Workspace
from app.models.directory_draft import DRAFT_DISCARDED, DirectoryDraft
from app.schemas.project import (
    NodeCreate,
    NodeOut,
    NodeReorderRequest,
    NodeUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectStatusUpdate,
    ProjectUpdate,
)
from app.services.knowledge_tree import load_decoration_template, seed_project_nodes
from app.services.nodes import assert_subtree_removable, subtree_node_ids
from app.services.project_context import schedule_refresh

router = APIRouter(prefix="/api/projects", tags=["projects"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _get_owned_project(db: DbSession, workspace_id: int, project_id: int) -> Project:
    """按 Workspace 归属获取项目，不存在或越权返回 404。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


async def _get_project_node(db: DbSession, project_id: int, node_id: int) -> Node:
    """获取项目内节点，不存在返回 404。"""
    node = await db.get(Node, node_id)
    if node is None or node.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="节点不存在")
    return node


async def _delete_node_subtree(db: DbSession, node_id: int) -> None:
    """递归删除节点及其全部后代（应用层级联，兼容 SQLite 外键未启用）。"""
    children = (
        await db.execute(select(Node).where(Node.parent_id == node_id))
    ).scalars().all()
    for child in children:
        await _delete_node_subtree(db, child.id)
    node = await db.get(Node, node_id)
    if node is not None:
        await db.delete(node)


def _build_tree(nodes: list[Node], counts: dict[int, int] | None = None) -> list[NodeOut]:
    """按 parent_id 组装嵌套树（同级按 position 排序）。"""
    counts = counts or {}
    by_parent: dict[int | None, list[Node]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)
    for siblings in by_parent.values():
        siblings.sort(key=lambda item: item.position)

    def _children(parent_id: int | None) -> list[NodeOut]:
        result: list[NodeOut] = []
        for node in by_parent.get(parent_id, []):
            result.append(
                NodeOut(
                    id=node.id,
                    name=node.name,
                    description=node.description,
                    position=node.position,
                    entry_count=counts.get(node.id, 0),
                    children=_children(node.id),
                )
            )
        return result

    return _children(None)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    db: DbSession, workspace: CurrentWorkspace, status_filter: str | None = None
) -> list[ProjectOut]:
    """列出当前 Workspace 的项目（含节点数）。"""
    valid_statuses = {"active", "paused", "completed", "archived"}
    if status_filter is not None and status_filter not in valid_statuses:
        raise HTTPException(status_code=400, detail="无效的项目状态")
    query = select(Project).where(Project.workspace_id == workspace.id)
    if status_filter is not None:
        query = query.where(Project.status == status_filter)
    elif status_filter is None:
        query = query.where(Project.status != "archived")
    projects = (
        await db.execute(query.order_by(Project.created_at))
    ).scalars().all()

    counts = dict(
        (
            await db.execute(
                select(Node.project_id, func.count()).group_by(Node.project_id)
            )
        ).all()
    )
    return [
        ProjectOut(
            id=project.id,
            name=project.name,
            description=project.description,
            status=project.status,
            template=project.template,
            node_count=counts.get(project.id, 0),
            created_at=project.created_at,
        )
        for project in projects
    ]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectOut:
    """创建项目；默认创建空目录，保留旧模板请求的兼容行为。"""
    template = "empty"
    project = Project(
        workspace_id=workspace.id,
        name=payload.name,
        description=payload.description,
        status="active",
        template=template,
    )
    db.add(project)
    await db.flush()

    # 兼容历史 API 调用；正式创建界面不再提供模板选择。
    node_count = 0
    if payload.template == "decoration":
        node_count = await seed_project_nodes(db, project.id, load_decoration_template())

    await schedule_refresh(db, project.id, "project_updated")
    await db.commit()
    await db.refresh(project)
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        template=project.template,
        node_count=node_count,
        created_at=project.created_at,
    )


@router.patch("/{project_id}", response_model=ProjectOut)
async def rename_project(
    project_id: int,
    payload: ProjectUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectOut:
    """重命名项目。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    if payload.name is not None:
        project.name = payload.name
    if "description" in payload.model_fields_set:
        project.description = payload.description
        await schedule_refresh(db, project.id, "project_updated")
    await db.commit()
    await db.refresh(project)
    node_count = (
        await db.execute(
            select(func.count())
            .select_from(Node)
            .where(Node.project_id == project.id)
        )
    ).scalar_one()
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        template=project.template,
        node_count=int(node_count),
        created_at=project.created_at,
    )


@router.patch("/{project_id}/status", response_model=ProjectOut)
async def update_project_status(
    project_id: int,
    payload: ProjectStatusUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ProjectOut:
    """修改项目生命周期状态。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    project.status = payload.status
    await db.commit()
    await db.refresh(project)
    node_count = int(
        (
            await db.execute(
                select(func.count()).select_from(Node).where(Node.project_id == project.id)
            )
        ).scalar_one()
    )
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        status=project.status,
        template=project.template,
        node_count=node_count,
        created_at=project.created_at,
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> dict[str, bool]:
    """删除项目并级联删除全部节点。"""
    project = await _get_owned_project(db, workspace.id, project_id)
    # 删除项目前，把其 Source 置为未归属，保留原始材料与证据
    sources = (
        await db.execute(select(Source).where(Source.project_id == project.id))
    ).scalars().all()
    for source in sources:
        source.project_id = None

    roots = (
        await db.execute(
            select(Node).where(
                Node.project_id == project.id,
                Node.parent_id.is_(None),
            )
        )
    ).scalars().all()
    for root in roots:
        await _delete_node_subtree(db, root.id)
    await db.delete(project)
    await db.commit()
    return {"ok": True}


@router.get("/{project_id}/tree", response_model=list[NodeOut])
async def get_project_tree(
    project_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> list[NodeOut]:
    """返回项目目录树（嵌套、按顺序）。"""
    await _get_owned_project(db, workspace.id, project_id)
    nodes = (
        await db.execute(select(Node).where(Node.project_id == project_id))
    ).scalars().all()
    node_ids = [node.id for node in nodes]
    counts: dict[int, int] = {}
    if node_ids:
        rows = (
            await db.execute(
                select(Entry.node_id, func.count())
                .where(Entry.node_id.in_(node_ids))
                .group_by(Entry.node_id)
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in rows}
    return _build_tree(list(nodes), counts)


@router.post(
    "/{project_id}/nodes",
    status_code=status.HTTP_201_CREATED,
    response_model=NodeOut,
)
async def create_node(
    project_id: int,
    payload: NodeCreate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> NodeOut:
    """创建节点：根级或指定父节点下末尾。"""
    await _get_owned_project(db, workspace.id, project_id)
    parent_id = payload.parent_id
    if parent_id is not None:
        await _get_project_node(db, project_id, parent_id)

    sibling_count = (
        await db.execute(
            select(func.count())
            .select_from(Node)
            .where(Node.project_id == project_id, Node.parent_id == parent_id)
        )
    ).scalar_one()
    node = Node(
        project_id=project_id,
        parent_id=parent_id,
        name=payload.name,
        description=payload.description,
        position=int(sibling_count),
    )
    db.add(node)
    await schedule_refresh(db, project_id, "directory_changed")
    await db.commit()
    await db.refresh(node)
    return NodeOut(
        id=node.id,
        name=node.name,
        description=node.description,
        position=node.position,
        children=[],
    )


@router.patch("/{project_id}/nodes/{node_id}", response_model=NodeOut)
async def update_node(
    project_id: int,
    node_id: int,
    payload: NodeUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> NodeOut:
    """更新节点名称/描述。"""
    await _get_owned_project(db, workspace.id, project_id)
    node = await _get_project_node(db, project_id, node_id)
    if payload.name is not None:
        node.name = payload.name
    if payload.description is not None:
        node.description = payload.description
    if "parent_id" in payload.model_fields_set and payload.parent_id != node.parent_id:
        new_parent_id = payload.parent_id
        if new_parent_id is not None:
            new_parent = await _get_project_node(db, project_id, new_parent_id)
            if new_parent.id == node.id:
                raise HTTPException(status_code=400, detail="节点不能移动到自身")
            descendants = (
                await db.execute(select(Node).where(Node.project_id == project_id))
            ).scalars().all()
            parent_by_id = {item.id: item.parent_id for item in descendants}
            cursor = new_parent.id
            while cursor is not None:
                if cursor == node.id:
                    raise HTTPException(status_code=400, detail="节点不能移动到其后代")
                cursor = parent_by_id.get(cursor)
        old_parent_id = node.parent_id
        old_siblings = (
            await db.execute(
                select(Node)
                .where(Node.project_id == project_id, Node.parent_id == old_parent_id)
                .order_by(Node.position)
            )
        ).scalars().all()
        for position, sibling in enumerate(item for item in old_siblings if item.id != node.id):
            sibling.position = position
        new_siblings = (
            await db.execute(
                select(Node)
                .where(Node.project_id == project_id, Node.parent_id == new_parent_id)
                .order_by(Node.position)
            )
        ).scalars().all()
        node.parent_id = new_parent_id
        node.position = len(new_siblings)
    await schedule_refresh(db, project_id, "directory_changed")
    await db.commit()
    return NodeOut(
        id=node.id,
        name=node.name,
        description=node.description,
        position=node.position,
        children=[],
    )


@router.delete("/{project_id}/nodes/{node_id}")
async def delete_node(
    project_id: int,
    node_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> dict[str, bool]:
    """删除节点并级联删除后代；子树含正式 Entry 时拒绝。"""
    await _get_owned_project(db, workspace.id, project_id)
    node = await _get_project_node(db, project_id, node_id)
    subtree_ids = await subtree_node_ids(db, project_id, node.id)
    await assert_subtree_removable(db, project_id, subtree_ids)
    draft = (
        await db.execute(
            select(DirectoryDraft).where(
                DirectoryDraft.project_id == project_id,
                DirectoryDraft.kind == "expand",
                DirectoryDraft.target_node_id == node.id,
                DirectoryDraft.status.in_(
                    ["drafting", "awaiting_input", "pending_confirm", "failed"]
                ),
            )
        )
    ).scalar_one_or_none()
    if draft is not None:
        draft.status = DRAFT_DISCARDED
    await _delete_node_subtree(db, node.id)
    await schedule_refresh(db, project_id, "directory_changed")
    await db.commit()
    return {"ok": True}


@router.post("/{project_id}/nodes/reorder")
async def reorder_nodes(
    project_id: int,
    payload: NodeReorderRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> dict[str, bool]:
    """调整同级节点顺序（ordered_ids 为该父节点下的完整新顺序）。"""
    await _get_owned_project(db, workspace.id, project_id)
    parent_id = payload.parent_id
    if parent_id is not None:
        await _get_project_node(db, project_id, parent_id)

    siblings = (
        await db.execute(
            select(Node)
            .where(Node.project_id == project_id, Node.parent_id == parent_id)
            .order_by(Node.position)
        )
    ).scalars().all()
    by_id = {node.id: node for node in siblings}

    if sorted(payload.ordered_ids) != sorted(by_id.keys()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="排序列表必须包含该父节点下的全部节点",
        )

    for position, node_id in enumerate(payload.ordered_ids):
        by_id[node_id].position = position
    await schedule_refresh(db, project_id, "directory_changed")
    await db.commit()
    return {"ok": True}
