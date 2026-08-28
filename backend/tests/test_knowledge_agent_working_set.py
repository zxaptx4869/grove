"""知识 Agent 上下文版本与工作集服务测试。"""

import pytest

from app.db.session import async_session_factory
from app.models import (
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeWorkingSetItem,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    CONTEXT_CLOSE_REASON_NEW_TOPIC,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_CLOSED,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.working_set import (
    active_context_summary,
    get_active_context_version,
)
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


async def _conversation(db, user, workspace) -> KnowledgeConversation:
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="工作集测试",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _active_version(
    db,
    conversation: KnowledgeConversation,
    user,
    workspace,
    *,
    topic_label: str = "闭水试验",
) -> KnowledgeContextVersion:
    version = KnowledgeContextVersion(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        version_number=1,
        scope_type=SCOPE_WORKSPACE,
        topic_label=topic_label,
        status=CONTEXT_STATUS_ACTIVE,
        active_slot=ACTIVE_SLOT,
    )
    db.add(version)
    await db.flush()
    return version


@pytest.mark.asyncio
async def test_active_context_summary_returns_topic_and_entry_count() -> None:
    """活动版本摘要返回主题标签、版本 id 与正式 Entry 数。"""
    async with async_session_factory() as db:
        user = await create_user(db, "工作集")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        version = await _active_version(db, conversation, user, workspace)
        project = await create_project(db, workspace, "工作集项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        db.add(
            KnowledgeWorkingSetItem(
                context_version_id=version.id,
                entry_id=entry.id,
                entry_title=entry.title,
                project_name=project.name,
                include_reason="cited",
                sort_order=0,
            )
        )
        await db.commit()

        topic, version_id, entry_count = await active_context_summary(
            db, conversation.id
        )
        assert topic == "闭水试验"
        assert version_id == version.id
        assert entry_count == 1

        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.id == version.id


@pytest.mark.asyncio
async def test_active_context_summary_ignores_closed_versions() -> None:
    """关闭/被替换版本不再是活动版本，摘要返回空。"""
    async with async_session_factory() as db:
        user = await create_user(db, "关闭版本")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        closed = KnowledgeContextVersion(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            version_number=1,
            scope_type=SCOPE_WORKSPACE,
            topic_label="旧话题",
            status=CONTEXT_STATUS_CLOSED,
            close_reason=CONTEXT_CLOSE_REASON_NEW_TOPIC,
            active_slot=None,
        )
        db.add(closed)
        await db.commit()

        topic, version_id, entry_count = await active_context_summary(
            db, conversation.id
        )
        assert topic is None
        assert version_id is None
        assert entry_count == 0
        assert await get_active_context_version(db, conversation.id) is None


@pytest.mark.asyncio
async def test_conversation_without_version_has_empty_summary() -> None:
    """既有对话没有活动工作集版本：摘要为空，不影响旧对话。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无版本")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        await db.commit()

        topic, version_id, entry_count = await active_context_summary(
            db, conversation.id
        )
        assert (topic, version_id, entry_count) == (None, None, 0)
