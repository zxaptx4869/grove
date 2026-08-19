"""目录节点服务：受保护删除校验与子树统计。"""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, Node


async def subtree_node_ids(
    db: AsyncSession,
    project_id: int,
    root_id: int,
) -> set[int]:
    """收集节点自身与全部后代的 id。"""
    all_nodes = (
        (
            await db.execute(
                select(Node.id, Node.parent_id).where(Node.project_id == project_id)
            )
        ).all()
    )
    children_by_parent: dict[int | None, list[int]] = {}
    for node_id, parent_id in all_nodes:
        children_by_parent.setdefault(parent_id, []).append(node_id)
    result: set[int] = {root_id}
    stack = list(children_by_parent.get(root_id, []))
    while stack:
        current = stack.pop()
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


async def count_subtree_entries_total(
    db: AsyncSession,
    project_id: int,
    node_ids: set[int],
) -> int:
    """统计节点子树内正式 Entry 总数。"""
    if not node_ids:
        return 0
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Entry)
                .where(Entry.project_id == project_id, Entry.node_id.in_(node_ids))
            )
        ).scalar_one()
    )


async def assert_subtree_removable(
    db: AsyncSession,
    project_id: int,
    node_ids: set[int],
) -> None:
    """子树含正式 Entry 时拒绝删除（AI 移除与手动删除共用）。"""
    total = await count_subtree_entries_total(db, project_id, node_ids)
    if total > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"目录节点包含 {total} 条正式知识，无法删除",
        )
