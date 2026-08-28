"""版本化工作集服务：活动版本读取、范围复验、输出版本构建与生命周期。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeContextVersion, KnowledgeWorkingSetItem
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    CONTEXT_STATUS_ACTIVE,
)


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
                KnowledgeWorkingSetItem.context_version_id
                == KnowledgeContextVersion.id,
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
