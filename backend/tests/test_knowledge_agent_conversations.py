"""知识对话与 Run 应用服务测试：所有权、范围、分页、幂等与并发冲突。"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models import (
    KnowledgeMessage,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    MESSAGE_TYPE_SCOPE_CHANGE,
    RUN_CANCELLED,
    RUN_WAITING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeConversationCreate,
    KnowledgeRunSubmitRequest,
    KnowledgeScopeChangeRequest,
)
from app.services.knowledge_agent.conversations import (
    change_scope,
    create_conversation,
    get_owned_conversation,
    list_conversations,
    list_messages,
)
from app.services.knowledge_agent.runs import (
    cancel_run,
    get_owned_run,
    submit_message,
)


async def _user(db, prefix: str = "对话") -> User:
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    user = User(username=username, password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _workspace_for(db, user: User) -> Workspace:
    workspace = Workspace(name=f"{user.username} 的空间")
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.flush()
    return workspace


async def _project(db, workspace: Workspace, name: str = "项目A") -> Project:
    project = Project(
        workspace_id=workspace.id,
        name=name,
        template="empty",
        status="active",
    )
    db.add(project)
    await db.flush()
    return project


@pytest.mark.asyncio
async def test_create_conversation_workspace_and_project_scope() -> None:
    """Workspace 与项目范围创建；越权项目 404。"""
    async with async_session_factory() as db:
        user = await _user(db)
        workspace = await _workspace_for(db, user)
        project = await _project(db, workspace)

        ws_conv = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        assert ws_conv.scope_type == SCOPE_WORKSPACE
        assert ws_conv.project_id is None

        project_conv = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="project", project_id=project.id),
        )
        assert project_conv.scope_type == SCOPE_PROJECT
        assert project_conv.project_id == project.id

        other_user = await _user(db, "越权")
        other_ws = await _workspace_for(db, other_user)
        with pytest.raises(HTTPException) as exc_info:
            await create_conversation(
                db,
                other_ws.id,
                other_user.id,
                KnowledgeConversationCreate(scope_type="project", project_id=project.id),
            )
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_conversation_ownership_isolation() -> None:
    """跨 Workspace 与其他用户一律 404，不暴露对象是否存在。"""
    async with async_session_factory() as db:
        owner = await _user(db, "所有者")
        workspace = await _workspace_for(db, owner)
        conversation = await create_conversation(
            db,
            workspace.id,
            owner.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        await db.commit()

        other_user = await _user(db, "其他空间")
        other_ws = await _workspace_for(db, other_user)
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_conversation(db, other_ws.id, other_user.id, conversation.id)
        assert exc_info.value.status_code == 404

        # 同 Workspace 的其他用户也不可见
        member = await _user(db, "同空间成员")
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="owner"))
        await db.flush()
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_conversation(db, workspace.id, member.id, conversation.id)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_idempotent_and_title() -> None:
    """重复 client_message_id 返回首次消息与 Run；首条问题确定标题。"""
    async with async_session_factory() as db:
        user = await _user(db, "幂等")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        payload = KnowledgeRunSubmitRequest(
            client_message_id="client-retry-1",
            message="  闭水试验通常持续多久？  ",
        )
        user_message, run = await submit_message(db, conversation, payload)
        await db.commit()

        second_message, second_run = await submit_message(db, conversation, payload)
        assert second_message.id == user_message.id
        assert second_run.id == run.id

        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeMessage)
                .where(
                    KnowledgeMessage.conversation_id == conversation.id,
                    KnowledgeMessage.client_message_id == "client-retry-1",
                )
            )
        ).scalar_one()
        assert count == 1
        assert conversation.title == "闭水试验通常持续多久？"
        assert user_message.scope_type == SCOPE_WORKSPACE
        assert run.status == RUN_WAITING
        assert run.active_slot == "active"
        assert run.user_message_id == user_message.id
        assert run.assistant_message_id is not None


@pytest.mark.asyncio
async def test_submit_rejects_blank_and_active_conflict() -> None:
    """空白消息 422；活动 Run 期间新问题 409 且不创建记录。"""
    async with async_session_factory() as db:
        user = await _user(db, "冲突")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        with pytest.raises(HTTPException) as exc_info:
            await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(client_message_id="blank-1", message="   \n "),
            )
        assert exc_info.value.status_code == 422

        await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="first-1", message="第一个问题"),
        )
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(client_message_id="second-1", message="第二个问题"),
            )
        assert exc_info.value.status_code == 409

        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeMessage)
                .where(KnowledgeMessage.conversation_id == conversation.id)
            )
        ).scalar_one()
        # 用户消息 + 助手占位，第二条问题未创建
        assert count == 2


@pytest.mark.asyncio
async def test_scope_change_adds_message_and_keeps_history_snapshot() -> None:
    """空闲对话切换范围追加 scope_change 系统消息，历史消息保留旧快照。"""
    async with async_session_factory() as db:
        user = await _user(db, "切换")
        workspace = await _workspace_for(db, user)
        project = await _project(db, workspace, "水电项目")
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        user_message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="scope-1", message="切换前问题"),
        )
        await db.commit()
        # 先取消等待中的 Run，释放活动槽，空闲后才允许切换范围
        await cancel_run(db, run)
        await db.commit()

        conversation, event_message = await change_scope(
            db,
            conversation,
            KnowledgeScopeChangeRequest(scope_type="project", project_id=project.id),
        )
        await db.commit()

        assert conversation.scope_type == SCOPE_PROJECT
        assert conversation.project_id == project.id
        assert event_message.message_type == MESSAGE_TYPE_SCOPE_CHANGE
        assert event_message.scope_type == SCOPE_PROJECT
        assert event_message.project_id == project.id
        assert "全部知识" in event_message.content
        assert "水电项目" in event_message.content
        # 历史用户消息保留生成时 Workspace 快照
        assert user_message.scope_type == SCOPE_WORKSPACE
        assert user_message.project_id is None


@pytest.mark.asyncio
async def test_scope_change_conflict_with_active_run() -> None:
    """活动 Run 期间切换范围返回 409 且范围不变。"""
    async with async_session_factory() as db:
        user = await _user(db, "活动切换")
        workspace = await _workspace_for(db, user)
        project = await _project(db, workspace)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="active-1", message="进行中的问题"),
        )
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await change_scope(
                db,
                conversation,
                KnowledgeScopeChangeRequest(scope_type="project", project_id=project.id),
            )
        assert exc_info.value.status_code == 409
        assert conversation.scope_type == SCOPE_WORKSPACE
        assert conversation.project_id is None


@pytest.mark.asyncio
async def test_message_cursor_pagination() -> None:
    """游标分页稳定顺序且不重复不跳过。"""
    async with async_session_factory() as db:
        user = await _user(db, "分页")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        for index in range(5):
            _, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"page-{index}",
                    message=f"第 {index + 1} 个问题",
                ),
            )
            await db.commit()
            await cancel_run(db, run)
            await db.commit()

        seen: list[int] = []
        cursor: str | None = None
        for _ in range(10):
            rows, cursor = await list_messages(
                db,
                conversation.id,
                cursor=cursor,
                limit=2,
            )
            seen.extend(row.id for row in rows)
            if cursor is None:
                break
        assert len(seen) == 10
        assert len(set(seen)) == 10
        assert seen == sorted(seen)


@pytest.mark.asyncio
async def test_cancel_waiting_run_releases_slot() -> None:
    """取消 waiting Run 释放活动槽，随后可提交新问题。"""
    async with async_session_factory() as db:
        user = await _user(db, "取消")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="cancel-1", message="要被取消的问题"),
        )
        await db.commit()

        await cancel_run(db, run)
        await db.commit()
        assert run.status == RUN_CANCELLED
        assert run.active_slot is None

        _, new_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="cancel-2", message="取消后的问题"),
        )
        assert new_run.id != run.id
        assert new_run.status == RUN_WAITING


@pytest.mark.asyncio
async def test_get_owned_run_rejects_other_workspace() -> None:
    """跨 Workspace 查询 Run 返回 404。"""
    async with async_session_factory() as db:
        user = await _user(db, "Run所有权")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(client_message_id="run-1", message="问题"),
        )
        await db.commit()

        other = await _user(db, "另一用户")
        other_ws = await _workspace_for(db, other)
        with pytest.raises(HTTPException) as exc_info:
            await get_owned_run(db, other_ws.id, other.id, run.id)
        assert exc_info.value.status_code == 404
        owned = await get_owned_run(db, workspace.id, user.id, run.id)
        assert owned.id == run.id


@pytest.mark.asyncio
async def test_list_conversations_ordered_by_activity() -> None:
    """列表只返回当前用户与 Workspace 的对话，按最近活动排序。"""
    async with async_session_factory() as db:
        user = await _user(db, "列表")
        workspace = await _workspace_for(db, user)
        first = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        second = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        await submit_message(
            db,
            second,
            KnowledgeRunSubmitRequest(client_message_id="list-1", message="活跃对话"),
        )
        await db.commit()

        rows = await list_conversations(db, workspace.id, user.id)
        ids = [row.id for row in rows]
        assert ids == [second.id, first.id]

        other = await _user(db, "他空间")
        other_ws = await _workspace_for(db, other)
        assert await list_conversations(db, other_ws.id, other.id) == []
