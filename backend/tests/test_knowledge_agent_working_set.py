"""知识 Agent 上下文版本与工作集服务测试。"""

import pytest

from app.db.session import async_session_factory
from app.models import (
    Entry,
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeWorkingSetItem,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    CONTEXT_CLOSE_REASON_NEW_TOPIC,
    CONTEXT_CLOSE_REASON_REPLACED,
    CONTEXT_CLOSE_REASON_SCOPE_CHANGE,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_DECISION_NEW_TOPIC,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_CLOSED,
    CONTEXT_STATUS_SUPERSEDED,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.working_set import (
    WorkingSetSeedItem,
    active_context_summary,
    build_output_items,
    close_active_context_version,
    create_context_version,
    get_active_context_version,
    get_conversation_context_versions,
    load_validated_working_set,
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


async def _entry(
    db,
    workspace,
    project,
    *,
    title: str = "闭水试验",
    text: str = "闭水试验通常持续 24 小时。",
) -> Entry:
    node = await create_child_node(db, project, "施工")
    source, attachment = await create_source_attachment(
        db,
        workspace,
        project,
        text_content=text,
    )
    return await create_entry_with_evidence(
        db,
        project,
        node,
        source,
        attachment,
        title=title,
        content=text,
        quote=text.strip("。"),
    )


async def _item(
    db,
    version: KnowledgeContextVersion,
    entry: Entry,
    *,
    reason: str = "cited",
    sort_order: int = 0,
) -> KnowledgeWorkingSetItem:
    item = KnowledgeWorkingSetItem(
        context_version_id=version.id,
        entry_id=entry.id,
        entry_title=entry.title,
        project_name="项目",
        include_reason=reason,
        sort_order=sort_order,
    )
    db.add(item)
    await db.flush()
    return item


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


@pytest.mark.asyncio
async def test_working_set_isolation_and_scope_revalidation() -> None:
    """工作集读取校验用户、Workspace、对话与范围；删除/越权项只记不可用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "隔离复验")
        workspace = await create_workspace(db, user)
        other_user = await create_user(db, "他人")
        other_workspace = await create_workspace(db, other_user)
        conversation = await _conversation(db, user, workspace)
        project = await create_project(db, workspace, "复验项目")
        entry = await _entry(db, workspace, project)
        version = await _active_version(db, conversation, user, workspace)
        await _item(db, version, entry)
        await db.commit()

        # 越权 Workspace / 用户 / 对话：不暴露任何 Entry
        wrong_ws = await load_validated_working_set(
            db,
            workspace_id=other_workspace.id,
            owner_user_id=other_user.id,
            conversation_id=conversation.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            context_version_id=version.id,
        )
        assert wrong_ws.items == []
        assert wrong_ws.unavailable[0]["reason"] == "工作集归属校验失败"

        other_conv = await _conversation(db, other_user, other_workspace)
        wrong_conv = await load_validated_working_set(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=other_conv.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            context_version_id=version.id,
        )
        assert wrong_conv.items == []

        # 范围不匹配：不加载
        wrong_scope = await load_validated_working_set(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=conversation.id,
            scope_type=SCOPE_PROJECT,
            project_id=project.id,
            context_version_id=version.id,
        )
        assert wrong_scope.items == []
        assert wrong_scope.unavailable[0]["reason"] == "工作集范围与 Run 范围不匹配"

        # 正常加载
        valid = await load_validated_working_set(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=conversation.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            context_version_id=version.id,
        )
        assert len(valid.items) == 1
        assert valid.items[0].entry_id == entry.id
        assert valid.unavailable == []

        # Entry 删除后：只记录不可用，不复用线索
        await db.delete(entry)
        await db.commit()
        deleted = await load_validated_working_set(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=conversation.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            context_version_id=version.id,
        )
        assert deleted.items == []
        assert any(item["reason"] == "Entry 已删除" for item in deleted.unavailable)


@pytest.mark.asyncio
async def test_project_scope_entry_moved_out_is_unavailable() -> None:
    """项目范围下 Entry 移出项目：种子不可用但记录原因。"""
    async with async_session_factory() as db:
        user = await create_user(db, "移出范围")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        project_a = await create_project(db, workspace, "甲项目")
        project_b = await create_project(db, workspace, "乙项目")
        entry = await _entry(db, workspace, project_a, title="甲知识")
        version = KnowledgeContextVersion(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            version_number=1,
            scope_type=SCOPE_PROJECT,
            project_id=project_a.id,
            project_name="甲项目",
            topic_label="甲知识",
            status=CONTEXT_STATUS_ACTIVE,
            active_slot=ACTIVE_SLOT,
        )
        db.add(version)
        await db.flush()
        await _item(db, version, entry)
        await db.commit()

        entry.project_id = project_b.id
        await db.commit()
        result = await load_validated_working_set(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=conversation.id,
            scope_type=SCOPE_PROJECT,
            project_id=project_a.id,
            context_version_id=version.id,
        )
        assert result.items == []
        assert any(
            item["reason"] == "Entry 已移出 Run 范围" for item in result.unavailable
        )


@pytest.mark.asyncio
async def test_build_output_items_continue_merges_and_truncates() -> None:
    """继续合并旧有效项与本轮引用，优先本轮引用并按上限确定性截断。"""
    parent_items = [
        WorkingSetSeedItem(entry_id=101, entry_title="旧一", last_used_at=None),
        WorkingSetSeedItem(entry_id=102, entry_title="旧二", last_used_at=None),
    ]
    cited = [
        {"entry_id": 102, "entry_title": "旧二", "project_name": "P"},
        {"entry_id": 201, "entry_title": "新一", "project_name": "P"},
        {"entry_id": 202, "entry_title": "新二", "project_name": "P"},
    ]
    merged = build_output_items(
        cited=cited,
        parent=parent_items,
        decision=CONTEXT_DECISION_CONTINUE,
        max_items=3,
    )
    assert [item["entry_id"] for item in merged] == [102, 201, 202]
    assert all(item["include_reason"] == "cited" for item in merged)

    with_cap = build_output_items(
        cited=cited,
        parent=parent_items,
        decision=CONTEXT_DECISION_CONTINUE,
        max_items=2,
    )
    assert [item["entry_id"] for item in with_cap] == [102, 201]

    # 旧项在容量允许时按最近使用补足
    from datetime import UTC, datetime

    parent_items[0].last_used_at = datetime.now(UTC)
    parent_items[1].last_used_at = datetime(2020, 1, 1, tzinfo=UTC)
    with_recent = build_output_items(
        cited=[],
        parent=parent_items,
        decision=CONTEXT_DECISION_CONTINUE,
        max_items=2,
    )
    assert [item["entry_id"] for item in with_recent] == [101, 102]
    assert with_recent[0]["include_reason"] == "recent"


@pytest.mark.asyncio
async def test_build_output_items_new_topic_replaces_parent() -> None:
    """新话题输出版本只围绕本轮引用，不继承旧主题项。"""
    parent_items = [
        WorkingSetSeedItem(entry_id=101, entry_title="旧一"),
    ]
    cited = [
        {"entry_id": 201, "entry_title": "新话题知识", "project_name": "P"},
    ]
    replaced = build_output_items(
        cited=cited,
        parent=parent_items,
        decision=CONTEXT_DECISION_NEW_TOPIC,
        max_items=15,
    )
    assert [item["entry_id"] for item in replaced] == [201]

    empty = build_output_items(
        cited=[],
        parent=parent_items,
        decision=CONTEXT_DECISION_NEW_TOPIC,
        max_items=15,
    )
    assert empty == []


@pytest.mark.asyncio
async def test_create_context_version_supersedes_parent() -> None:
    """创建子版本：旧活动版本置 superseded，新版本唯一活动。"""
    async with async_session_factory() as db:
        user = await create_user(db, "版本链")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        project = await create_project(db, workspace, "版本项目")
        entry = await _entry(db, workspace, project)
        parent = await _active_version(db, conversation, user, workspace)
        await _item(db, parent, entry)
        await db.commit()

        child = await create_context_version(
            db,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
            topic_label="闭水试验（续）",
            source_run_id=None,
            items=[
                {
                    "entry_id": entry.id,
                    "entry_title": entry.title,
                    "project_name": project.name,
                    "node_path": "施工",
                }
            ],
            parent_version_id=parent.id,
        )
        await db.commit()

        await db.refresh(parent)
        assert parent.status == CONTEXT_STATUS_SUPERSEDED
        assert parent.close_reason == CONTEXT_CLOSE_REASON_REPLACED
        assert parent.active_slot is None
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.id == child.id
        assert active.version_number == 2
        assert active.parent_version_id == parent.id
        versions = await get_conversation_context_versions(db, conversation.id)
        assert [v.version_number for v in versions] == [1, 2]


@pytest.mark.asyncio
async def test_close_active_version_releases_slot() -> None:
    """关闭活动版本：状态 closed、活动槽释放且可再建新版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "关闭")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        await _active_version(db, conversation, user, workspace, topic_label="旧主题")
        await db.commit()

        closed = await close_active_context_version(
            db,
            conversation.id,
            reason=CONTEXT_CLOSE_REASON_SCOPE_CHANGE,
        )
        assert closed is True
        await db.commit()
        active = await get_active_context_version(db, conversation.id)
        assert active is None
        versions = await get_conversation_context_versions(db, conversation.id)
        assert versions[0].status == CONTEXT_STATUS_CLOSED
        assert versions[0].close_reason == CONTEXT_CLOSE_REASON_SCOPE_CHANGE

        # 关闭后可建立新话题版本
        new_version = await create_context_version(
            db,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
            topic_label="新话题",
            source_run_id=None,
            items=[],
        )
        await db.commit()
        assert new_version.status == CONTEXT_STATUS_ACTIVE
        assert new_version.version_number == 2


@pytest.mark.asyncio
async def test_create_version_rollback_keeps_old_active() -> None:
    """终态事务失败回滚：不切换活动工作集，旧版本保持活动。"""
    async with async_session_factory() as db:
        user = await create_user(db, "回滚")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        parent = await _active_version(db, conversation, user, workspace)
        conversation_id = conversation.id
        parent_id = parent.id
        await db.commit()

        await create_context_version(
            db,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
            topic_label="不应生效",
            source_run_id=None,
            items=[],
            parent_version_id=parent.id,
        )
        await db.rollback()

    async with async_session_factory() as verify:
        active = await get_active_context_version(verify, conversation_id)
        assert active is not None
        assert active.id == parent_id
        assert active.status == CONTEXT_STATUS_ACTIVE


@pytest.mark.asyncio
async def test_active_summary_keeps_empty_topic_version() -> None:
    """空主题版本（无 Entry 项）仍返回活动摘要且 entry_count=0。"""
    async with async_session_factory() as db:
        user = await create_user(db, "空主题摘要")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        version = await _active_version(db, conversation, user, workspace)
        await db.commit()

        topic, version_id, entry_count = await active_context_summary(
            db, conversation.id
        )
        assert topic == "闭水试验"
        assert version_id == version.id
        assert entry_count == 0
