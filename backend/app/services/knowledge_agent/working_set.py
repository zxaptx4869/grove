"""版本化工作集服务：活动版本读取、范围复验、输出版本构建与生命周期。"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Entry,
    KnowledgeContextVersion,
    KnowledgeWorkingSetItem,
    Project,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    CONTEXT_CLOSE_REASON_REPLACED,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_CLOSED,
    CONTEXT_STATUS_SUPERSEDED,
    SCOPE_PROJECT,
    WORKING_SET_REASON_CITED,
    WORKING_SET_REASON_RECENT,
)
from app.services.knowledge_agent.evidence import build_node_path_map

logger = logging.getLogger(__name__)


@dataclass
class WorkingSetSeedItem:
    """复验有效的工作集种子：只含 Entry 线索与短快照。"""

    entry_id: int
    entry_title: str
    project_name: str | None = None
    node_path: str | None = None
    source_run_id: int | None = None
    include_reason: str = WORKING_SET_REASON_CITED
    last_used_at: datetime | None = None


@dataclass
class WorkingSetValidation:
    """输入工作集复验结果：有效种子与不可用项。"""

    items: list[WorkingSetSeedItem] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)


async def get_active_context_version(
    db: AsyncSession,
    conversation_id: int,
) -> KnowledgeContextVersion | None:
    """读取对话当前活动工作集版本（同一对话最多一个）。"""
    return (
        await db.execute(
            select(KnowledgeContextVersion).where(
                KnowledgeContextVersion.conversation_id == conversation_id,
                KnowledgeContextVersion.active_slot == ACTIVE_SLOT,
                KnowledgeContextVersion.status == CONTEXT_STATUS_ACTIVE,
            )
        )
    ).scalar_one_or_none()


async def active_context_summaries(
    db: AsyncSession,
    conversation_ids: list[int],
) -> dict[int, tuple[str | None, int | None, int]]:
    """批量返回对话的 (主题标签, 活动版本 id, Entry 数)。"""
    if not conversation_ids:
        return {}
    rows = (
        await db.execute(
            select(
                KnowledgeContextVersion.conversation_id,
                KnowledgeContextVersion.id,
                KnowledgeContextVersion.topic_label,
                func.count(KnowledgeWorkingSetItem.id),
            )
            .outerjoin(
                KnowledgeWorkingSetItem,
                (KnowledgeWorkingSetItem.context_version_id == KnowledgeContextVersion.id)
                & KnowledgeWorkingSetItem.entry_id.is_not(None),
            )
            .where(
                KnowledgeContextVersion.conversation_id.in_(conversation_ids),
                KnowledgeContextVersion.active_slot == ACTIVE_SLOT,
                KnowledgeContextVersion.status == CONTEXT_STATUS_ACTIVE,
            )
            .group_by(
                KnowledgeContextVersion.conversation_id,
                KnowledgeContextVersion.id,
                KnowledgeContextVersion.topic_label,
            )
        )
    ).all()
    return {
        conversation_id: (topic_label, version_id, int(entry_count))
        for conversation_id, version_id, topic_label, entry_count in rows
    }


async def active_context_summary(
    db: AsyncSession,
    conversation_id: int,
) -> tuple[str | None, int | None, int]:
    """返回单个对话的 (主题标签, 活动版本 id, Entry 数)。"""
    summaries = await active_context_summaries(db, [conversation_id])
    return summaries.get(conversation_id, (None, None, 0))


async def load_validated_working_set(
    db: AsyncSession,
    *,
    workspace_id: int,
    owner_user_id: int,
    conversation_id: int,
    scope_type: str,
    project_id: int | None,
    context_version_id: int | None,
) -> WorkingSetValidation:
    """加载固化输入工作集并复验：归属、范围与 Entry 现状。"""
    if context_version_id is None:
        return WorkingSetValidation()
    version = await db.get(KnowledgeContextVersion, context_version_id)
    if version is None:
        return WorkingSetValidation(
            unavailable=[{"entry_id": None, "reason": "输入工作集版本不存在"}]
        )
    if (
        version.workspace_id != workspace_id
        or version.owner_user_id != owner_user_id
        or version.conversation_id != conversation_id
    ):
        # 越权复用：不暴露任何 Entry 线索
        return WorkingSetValidation(
            unavailable=[{"entry_id": None, "reason": "工作集归属校验失败"}]
        )
    if (
        version.scope_type != scope_type
        or version.project_id != project_id
    ):
        return WorkingSetValidation(
            unavailable=[{"entry_id": None, "reason": "工作集范围与 Run 范围不匹配"}]
        )

    rows = (
        await db.execute(
            select(KnowledgeWorkingSetItem)
            .where(
                KnowledgeWorkingSetItem.context_version_id == version.id,
                KnowledgeWorkingSetItem.entry_id.is_not(None),
            )
            .order_by(KnowledgeWorkingSetItem.sort_order)
        )
    ).scalars().all()
    if not rows:
        return WorkingSetValidation()

    entry_ids = [row.entry_id for row in rows if row.entry_id is not None]
    entries = (
        await db.execute(
            select(Entry)
            .join(Project, Entry.project_id == Project.id)
            .options(selectinload(Entry.project))
            .where(
                Entry.id.in_(entry_ids),
                Project.workspace_id == workspace_id,
            )
        )
    ).scalars().all()
    entry_by_id = {entry.id: entry for entry in entries}
    path_by_node: dict[int, str] = {}
    loaded_project_ids: set[int] = set()
    for entry in entries:
        if entry.project_id is not None and entry.project_id not in loaded_project_ids:
            loaded_project_ids.add(entry.project_id)
            path_by_node.update(await build_node_path_map(db, entry.project_id))

    validation = WorkingSetValidation()
    seen: set[int] = set()
    for row in rows:
        entry_id = row.entry_id
        if entry_id is None or entry_id in seen:
            continue
        seen.add(entry_id)
        entry = entry_by_id.get(entry_id)
        if entry is None:
            validation.unavailable.append(
                {"entry_id": entry_id, "reason": "Entry 已删除"}
            )
            continue
        if scope_type == SCOPE_PROJECT and entry.project_id != project_id:
            validation.unavailable.append(
                {"entry_id": entry_id, "reason": "Entry 已移出 Run 范围"}
            )
            continue
        validation.items.append(
            WorkingSetSeedItem(
                entry_id=entry.id,
                entry_title=entry.title,
                project_name=entry.project.name if entry.project else None,
                node_path=path_by_node.get(entry.node_id, ""),
                source_run_id=row.source_run_id,
                include_reason=row.include_reason,
                last_used_at=row.last_used_at,
            )
        )
    return validation


def build_output_items(
    *,
    cited: list[dict],
    parent: list[WorkingSetSeedItem],
    decision: str,
    max_items: int,
) -> list[dict]:
    """构建输出版本工作集项：继续合并旧有效项，新话题替换；确定性截断。"""
    ordered: list[dict] = []
    seen: set[int] = set()
    for item in cited:
        entry_id = item.get("entry_id")
        if entry_id is None or entry_id in seen:
            continue
        ordered.append(
            {
                "entry_id": entry_id,
                "entry_title": item.get("entry_title", ""),
                "project_name": item.get("project_name"),
                "node_path": item.get("node_path"),
                "source_run_id": item.get("source_run_id"),
                "include_reason": WORKING_SET_REASON_CITED,
            }
        )
        seen.add(entry_id)
    if decision == CONTEXT_DECISION_CONTINUE and len(ordered) < max_items:
        recent_parent = sorted(
            parent,
            key=lambda item: item.last_used_at or datetime.min,
            reverse=True,
        )
        for old in recent_parent:
            if len(ordered) >= max_items:
                break
            if old.entry_id in seen:
                continue
            ordered.append(
                {
                    "entry_id": old.entry_id,
                    "entry_title": old.entry_title,
                    "project_name": old.project_name,
                    "node_path": old.node_path,
                    "source_run_id": old.source_run_id,
                    "include_reason": WORKING_SET_REASON_RECENT,
                }
            )
            seen.add(old.entry_id)
    return ordered[:max_items]


async def create_context_version(
    db: AsyncSession,
    *,
    conversation_id: int,
    workspace_id: int,
    owner_user_id: int,
    scope_type: str,
    project_id: int | None,
    project_name: str | None,
    topic_label: str,
    source_run_id: int | None,
    items: list[dict],
    parent_version_id: int | None = None,
) -> KnowledgeContextVersion:
    """创建新工作集版本：旧活动版本置 superseded，新版本接管活动槽。"""
    parent: KnowledgeContextVersion | None = None
    if parent_version_id is not None:
        parent = await db.get(KnowledgeContextVersion, parent_version_id)
    if parent is not None and parent.status == CONTEXT_STATUS_ACTIVE:
        parent.status = CONTEXT_STATUS_SUPERSEDED
        parent.close_reason = CONTEXT_CLOSE_REASON_REPLACED
        parent.active_slot = None
    if parent is not None:
        version_number = parent.version_number + 1
    else:
        max_number = (
            await db.execute(
                select(func.max(KnowledgeContextVersion.version_number)).where(
                    KnowledgeContextVersion.conversation_id == conversation_id
                )
            )
        ).scalar_one()
        version_number = (max_number or 0) + 1
    version = KnowledgeContextVersion(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        version_number=version_number,
        parent_version_id=parent.id if parent is not None else None,
        source_run_id=source_run_id,
        scope_type=scope_type,
        project_id=project_id,
        project_name=project_name,
        topic_label=topic_label,
        status=CONTEXT_STATUS_ACTIVE,
        active_slot=ACTIVE_SLOT,
    )
    db.add(version)
    await db.flush()
    for order, item in enumerate(items):
        db.add(
            KnowledgeWorkingSetItem(
                context_version_id=version.id,
                entry_id=item.get("entry_id"),
                entry_title=item.get("entry_title"),
                project_name=item.get("project_name"),
                node_path=item.get("node_path"),
                source_run_id=item.get("source_run_id"),
                include_reason=item.get("include_reason", WORKING_SET_REASON_CITED),
                sort_order=order,
            )
        )
    await db.flush()
    return version


async def close_active_context_version(
    db: AsyncSession,
    conversation_id: int,
    *,
    reason: str,
) -> bool:
    """关闭对话当前活动工作集版本（范围切换 / 显式新话题）。"""
    version = await get_active_context_version(db, conversation_id)
    if version is None:
        return False
    version.status = CONTEXT_STATUS_CLOSED
    version.close_reason = reason
    version.active_slot = None
    await db.flush()
    return True


async def get_conversation_context_versions(
    db: AsyncSession,
    conversation_id: int,
) -> list[KnowledgeContextVersion]:
    """读取对话全部历史版本（审计），按版本号升序。"""
    rows = (
        await db.execute(
            select(KnowledgeContextVersion)
            .where(KnowledgeContextVersion.conversation_id == conversation_id)
            .order_by(KnowledgeContextVersion.version_number)
        )
    ).scalars().all()
    return list(rows)
