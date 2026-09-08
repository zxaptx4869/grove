"""Knowledge Agent 实验使用的真实项目目录只读查询。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, Node, Project, WorkspaceMember
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    TOOL_COMPLETED,
    TOOL_DENIED,
    TOOL_EMPTY,
    TOOL_PARTIAL,
)
from app.services.knowledge_agent.read_tools import ReadToolExecution, ReadToolParams
from app.services.knowledge_agent.tools import RunToolContext

DIRECTORY_TOOL_VERSION = "v1"
DIRECTORY_FIND_DEFAULT_LIMIT = 20


class ListProjectDirectoriesParams(ReadToolParams):
    """按项目根、指定父节点、名称/路径或整树叶子统计查询目录。"""

    project_id: int | None = Field(default=None, ge=1)
    project_name: str | None = Field(default=None, min_length=1, max_length=64)
    parent_node_id: int | None = Field(default=None, ge=1)
    operation: Literal["children", "find", "leaf_summary"] = "children"
    name: str | None = Field(default=None, min_length=1, max_length=128)
    path: str | None = Field(default=None, min_length=1, max_length=2048)
    match: Literal["exact", "contains"] = "exact"
    limit: int = Field(default=DIRECTORY_FIND_DEFAULT_LIMIT, ge=1, le=50)

    @model_validator(mode="after")
    def require_project_reference(self) -> ListProjectDirectoriesParams:
        if self.project_id is None and not (self.project_name or "").strip():
            raise ValueError("必须提供 project_id 或 project_name")
        if self.project_name is not None:
            self.project_name = self.project_name.strip()
            if not self.project_name:
                raise ValueError("project_name 不能为空")
        if self.name is not None:
            self.name = self.name.strip()
            if not self.name:
                raise ValueError("name 不能为空")
        if self.path is not None:
            segments = [segment.strip() for segment in self.path.split("/")]
            if not all(segments):
                raise ValueError("目录路径必须由非空名称组成")
            self.path = " / ".join(segments)
        if self.operation == "find":
            if (self.name is None) == (self.path is None):
                raise ValueError("目录定位必须且只能提供 name 或 path")
            if self.parent_node_id is not None:
                raise ValueError("目录定位不能同时指定父节点")
        elif self.name is not None or self.path is not None:
            raise ValueError("只有 find 操作可以提供 name 或 path")
        if self.operation == "leaf_summary" and self.parent_node_id is not None:
            raise ValueError("叶子节点聚合不能同时指定父节点")
        return self


def _ordered_nodes(nodes: list[Node]) -> list[Node]:
    """产品目录树同级顺序：position 相同时以 id 稳定回退。"""

    return sorted(nodes, key=lambda node: (node.position, node.id))


def _node_paths(nodes: list[Node]) -> dict[int, str]:
    by_id = {node.id: node for node in nodes}
    cache: dict[int, str] = {}

    def path_for(node_id: int, visiting: set[int] | None = None) -> str:
        if node_id in cache:
            return cache[node_id]
        node = by_id[node_id]
        visiting = visiting or set()
        if node_id in visiting:
            return node.name
        visiting.add(node_id)
        if node.parent_id is None or node.parent_id not in by_id:
            path = node.name
        else:
            path = f"{path_for(node.parent_id, visiting)} / {node.name}"
        cache[node_id] = path
        return path

    for node in nodes:
        path_for(node.id)
    return cache


def _node_depths(nodes: list[Node]) -> dict[int, int]:
    """以一级目录深度 0 计算真实父链深度；异常环路保守停止。"""

    by_id = {node.id: node for node in nodes}
    depths: dict[int, int] = {}
    for node in nodes:
        depth = 0
        current = node
        visited = {node.id}
        while current.parent_id is not None:
            parent = by_id.get(current.parent_id)
            if parent is None or parent.id in visited:
                break
            depth += 1
            visited.add(parent.id)
            current = parent
        depths[node.id] = depth
    return depths


def _directory_item(
    project: Project,
    node: Node,
    *,
    paths: dict[int, str],
    depths: dict[int, int],
    parent_ids: set[int],
    entry_count: int | None = None,
) -> dict:
    """构造目录工具各操作共用的权威 Node 身份。"""

    item = {
        "node_id": node.id,
        "name": node.name,
        "project_id": project.id,
        "project_name": project.name,
        "parent_node_id": node.parent_id,
        "path": paths[node.id],
        "depth": depths[node.id],
        "is_leaf": node.id not in parent_ids,
        "position": node.position,
    }
    if entry_count is not None:
        item["entry_count"] = entry_count
    return item


def _find_directories(
    project: Project,
    nodes: list[Node],
    paths: dict[int, str],
    depths: dict[int, int],
    params: ListProjectDirectoriesParams,
) -> ReadToolExecution:
    """在单一已授权项目的完整 Node 集合中按名称或路径定位。"""

    parent_ids = {node.parent_id for node in nodes if node.parent_id is not None}
    if params.path is not None:
        matched = [node for node in nodes if paths[node.id] == params.path]
        match_kind = "path"
    else:
        exact = [node for node in nodes if node.name == params.name]
        if exact or params.match == "exact":
            matched = exact
            match_kind = "exact"
        else:
            matched = [node for node in nodes if params.name in node.name]
            match_kind = "contains"
    ordered = sorted(matched, key=lambda node: (paths[node.id], node.id))
    total_count = len(ordered)
    selected = ordered[: params.limit]
    has_more = total_count > len(selected)
    items = [
        _directory_item(
            project,
            node,
            paths=paths,
            depths=depths,
            parent_ids=parent_ids,
        )
        for node in selected
    ]
    if total_count == 0:
        match_status = "not_found"
        status = TOOL_EMPTY
        completeness = RESULT_COMPLETENESS_COMPLETE
        error = None
    elif match_kind == "contains":
        match_status = "contains_candidates"
        status = TOOL_PARTIAL
        completeness = (
            RESULT_COMPLETENESS_LIMITED if has_more else RESULT_COMPLETENESS_COMPLETE
        )
        error = "没有精确匹配，以下为名称包含候选，请根据完整路径确认"
    elif total_count == 1:
        match_status = "unique"
        status = TOOL_COMPLETED
        completeness = RESULT_COMPLETENESS_COMPLETE
        error = None
    else:
        match_status = "ambiguous"
        status = TOOL_PARTIAL
        completeness = (
            RESULT_COMPLETENESS_LIMITED if has_more else RESULT_COMPLETENESS_COMPLETE
        )
        error = "找到多个同名目录，请根据完整路径选择"
    payload = {
        "project": {"id": project.id, "name": project.name},
        "operation": "find",
        "query": {
            "name": params.name,
            "path": params.path,
            "requested_match": params.match,
            "applied_match": match_kind,
        },
        "match_status": match_status,
        "items": items,
        "total_count": total_count,
        "returned_count": len(items),
        "has_more": has_more,
    }
    reason_code = {
        "unique": "directory_found",
        "ambiguous": "directory_name_ambiguous",
        "contains_candidates": "directory_contains_candidates",
        "not_found": "directory_not_found",
    }[match_status]
    payload["reason_code"] = reason_code
    return ReadToolExecution(
        status=status,
        payload=payload,
        completeness=completeness,
        audit_summary={
            "status": status,
            "reason_code": reason_code,
            "project_id": project.id,
            "operation": "find",
            "match_status": match_status,
            "applied_match": match_kind,
            "total_count": total_count,
            "returned_count": len(items),
            "has_more": has_more,
            "completeness": completeness,
        },
        error=error,
    )


def _leaf_summary(project: Project, nodes: list[Node], paths: dict[int, str]) -> dict:
    """从同一项目的完整 Node 集合确定性计算整树叶子节点。"""

    by_id = {node.id: node for node in nodes}
    parent_ids = {node.parent_id for node in nodes if node.parent_id is not None}
    leaves = _ordered_nodes([node for node in nodes if node.id not in parent_ids])
    roots = _ordered_nodes([node for node in nodes if node.parent_id is None])

    def root_id_for(node: Node) -> int | None:
        current = node
        visited: set[int] = set()
        while current.parent_id is not None and current.id not in visited:
            visited.add(current.id)
            parent = by_id.get(current.parent_id)
            if parent is None:
                return None
            current = parent
        return current.id if current.parent_id is None else None

    counts = {root.id: 0 for root in roots}
    detached_count = 0
    for leaf in leaves:
        root_id = root_id_for(leaf)
        if root_id in counts:
            counts[root_id] += 1
        else:
            detached_count += 1
    buckets = [
        {"key": str(root.id), "label": root.name, "count": counts[root.id]}
        for root in roots
    ]
    if detached_count:
        buckets.append({"key": "detached", "label": "未挂接目录", "count": detached_count})
    return {
        "project": {"id": project.id, "name": project.name},
        "operation": "leaf_summary",
        "definition": "没有任何直接子 Node 的项目目录节点",
        "value": len(leaves),
        "total_count": len(leaves),
        "returned_count": len(buckets),
        "group_by": "root_directory",
        "buckets": buckets,
        "has_more": False,
        "sample_leaf_nodes": [
            {"node_id": node.id, "name": node.name, "path": paths[node.id]}
            for node in leaves[:10]
        ],
    }


async def list_project_directories_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: ListProjectDirectoriesParams,
) -> ReadToolExecution:
    """读取当前授权 Workspace 内项目的根级或直接子目录。"""

    member = (
        await db.execute(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == ctx.workspace_id,
                WorkspaceMember.user_id == ctx.owner_user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        return ReadToolExecution(
            status=TOOL_DENIED,
            payload={},
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            audit_summary={"status": TOOL_DENIED, "reason_code": "workspace_access_denied"},
            error="当前用户无权访问该 Workspace",
        )

    project_stmt = select(Project).where(Project.workspace_id == ctx.workspace_id)
    if ctx.project_id is not None:
        project_stmt = project_stmt.where(Project.id == ctx.project_id)
    if params.project_id is not None:
        project_stmt = project_stmt.where(Project.id == params.project_id)
    if params.project_name is not None:
        project_stmt = project_stmt.where(Project.name == params.project_name)
    projects = (await db.execute(project_stmt.limit(2))).scalars().all()
    if not projects:
        inaccessible = False
        if params.project_id is not None:
            inaccessible = (
                await db.execute(
                    select(Project.id).where(Project.id == params.project_id)
                )
            ).scalar_one_or_none() is not None
        # 名称只在当前 Workspace 内解析，不能借错误语义泄露其他空间的同名项目。
        return ReadToolExecution(
            status=TOOL_DENIED,
            payload={},
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            audit_summary={
                "status": TOOL_DENIED,
                "reason_code": "project_access_denied" if inaccessible else "project_not_found",
            },
            error=(
                "当前用户无权访问该项目"
                if inaccessible
                else "项目不存在或不在当前授权范围"
            ),
        )
    if len(projects) > 1:
        return ReadToolExecution(
            status=TOOL_DENIED,
            payload={},
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            audit_summary={"status": TOOL_DENIED, "reason_code": "project_name_ambiguous"},
            error="项目名称不唯一，请使用项目 ID",
        )
    project = projects[0]
    nodes = list(
        (
            await db.execute(
                select(Node).where(Node.project_id == project.id)
            )
        ).scalars().all()
    )
    by_id = {node.id: node for node in nodes}
    paths = _node_paths(nodes)
    depths = _node_depths(nodes)
    if params.operation == "find":
        return _find_directories(project, nodes, paths, depths, params)
    if params.operation == "leaf_summary":
        payload = _leaf_summary(project, nodes, paths)
        return ReadToolExecution(
            status=TOOL_COMPLETED,
            payload=payload,
            completeness=RESULT_COMPLETENESS_COMPLETE,
            audit_summary={
                "status": TOOL_COMPLETED,
                "project_id": project.id,
                "operation": "leaf_summary",
                "leaf_count": payload["value"],
                "root_bucket_count": payload["returned_count"],
                "has_more": False,
                "completeness": RESULT_COMPLETENESS_COMPLETE,
            },
        )
    parent = by_id.get(params.parent_node_id) if params.parent_node_id is not None else None
    if params.parent_node_id is not None and parent is None:
        return ReadToolExecution(
            status=TOOL_DENIED,
            payload={},
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            audit_summary={"status": TOOL_DENIED, "reason_code": "parent_not_in_project"},
            error="父节点不属于指定项目",
        )

    children = [
        node
        for node in nodes
        if node.parent_id == params.parent_node_id
    ]
    ordered = _ordered_nodes(children)
    parent_ids = {node.parent_id for node in nodes if node.parent_id is not None}
    entry_counts = (
        dict(
            (
                await db.execute(
                    select(Entry.node_id, func.count())
                    .where(Entry.node_id.in_([node.id for node in ordered]))
                    .group_by(Entry.node_id)
                )
            ).all()
        )
        if ordered
        else {}
    )
    items = [
        _directory_item(
            project,
            node,
            paths=paths,
            depths=depths,
            parent_ids=parent_ids,
            entry_count=int(entry_counts.get(node.id, 0)),
        )
        for node in ordered
    ]
    payload = {
        "project": {"id": project.id, "name": project.name},
        "parent": (
            {
                "node_id": parent.id,
                "name": parent.name,
                "path": paths[parent.id],
            }
            if parent is not None
            else None
        ),
        "items": items,
        "total_count": len(items),
        "returned_count": len(items),
        "has_more": False,
    }
    status = TOOL_COMPLETED if items else TOOL_EMPTY
    return ReadToolExecution(
        status=status,
        payload=payload,
        completeness=RESULT_COMPLETENESS_COMPLETE,
        audit_summary={
            "status": status,
            "project_id": project.id,
            "parent_node_id": params.parent_node_id,
            "total_count": len(items),
            "returned_count": len(items),
            "has_more": False,
            "completeness": RESULT_COMPLETENESS_COMPLETE,
        },
    )


async def list_project_directories(
    db: AsyncSession,
    ctx: RunToolContext,
    params: ListProjectDirectoriesParams,
) -> ReadToolExecution:
    """公开给共享 registry 的 v1 处理器别名。"""

    return await list_project_directories_handler(db, ctx, params)
