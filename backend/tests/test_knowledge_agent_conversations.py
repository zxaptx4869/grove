"""知识对话与 Run 应用服务测试：所有权、范围、分页、幂等与并发冲突。"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select

from app.db.session import async_session_factory, engine
from app.models import (
    KnowledgeMessage,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    BASIS_MODE_AUTO,
    BASIS_MODE_KNOWLEDGE_ONLY,
    MESSAGE_TYPE_SCOPE_CHANGE,
    MESSAGE_TYPE_USER,
    RESULT_MODE_ANSWER,
    RESULT_MODE_ENTRIES,
    RUN_CANCELLED,
    RUN_COMPLETED,
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
from app.services.knowledge_agent.working_set import (
    create_context_version,
    get_active_context_version,
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
async def test_submit_basis_mode_compat_and_retry_keeps_first() -> None:
    """依据模式固化：显式 auto 保存；缺省兼容 knowledge_only；重试不改首次模式。"""
    async with async_session_factory() as db:
        user = await _user(db, "依据")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        auto_message, auto_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="basis-service-auto",
                message="解释一下预算分配",
                basis_mode=BASIS_MODE_AUTO,
            ),
        )
        assert auto_run.request_basis_mode == BASIS_MODE_AUTO
        auto_run_id = auto_run.id
        del auto_message

        # 同 client_message_id 重试携带不同依据模式：返回首次 Run，不更新固化模式
        retry_message, retry_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="basis-service-auto",
                message="解释一下预算分配",
                basis_mode=BASIS_MODE_KNOWLEDGE_ONLY,
            ),
        )
        assert retry_run.id == auto_run_id
        assert retry_run.request_basis_mode == BASIS_MODE_AUTO

        # 取消活动 Run 后旧客户端缺省提交：兼容为 knowledge_only
        auto_run.status = RUN_CANCELLED
        auto_run.active_slot = None
        await db.flush()
        _legacy_message, legacy_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="basis-service-legacy",
                message="闭水试验通常持续多久？",
            ),
        )
        assert legacy_run.request_basis_mode == BASIS_MODE_KNOWLEDGE_ONLY


@pytest.mark.asyncio
async def test_result_mode_resubmit_restores_source_run_context() -> None:
    """模式纠正由服务端恢复原问题、原范围与原输入工作集。"""
    async with async_session_factory() as db:
        user = await _user(db, "模式纠正")
        workspace = await _workspace_for(db, user)
        source_project = await _project(db, workspace, "原项目")
        current_project = await _project(db, workspace, "当前项目")
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(
                scope_type="project",
                project_id=source_project.id,
            ),
        )
        source_context = await create_context_version(
            db,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=source_project.id,
            project_name=source_project.name,
            topic_label="原主题",
            source_run_id=None,
            items=[],
        )
        source_message, source_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="source-question",
                message="原始问题",
                context_mode="continue",
                result_mode=RESULT_MODE_ANSWER,
            ),
        )
        source_run.status = RUN_COMPLETED
        source_run.actual_result_mode = RESULT_MODE_ANSWER
        source_run.context_decision = "continue"
        source_run.standalone_query = "原主题的独立问题"
        source_run.topic_label = "原主题"
        source_run.history_message_ids_json = "[1]"
        source_run.context_meta_json = '{"provider":"llm","is_fallback":false}'
        source_run.active_slot = None
        await db.flush()

        await change_scope(
            db,
            conversation,
            KnowledgeScopeChangeRequest(
                scope_type=SCOPE_PROJECT,
                project_id=current_project.id,
            ),
        )
        current_context = await create_context_version(
            db,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=current_project.id,
            project_name=current_project.name,
            topic_label="当前主题",
            source_run_id=None,
            items=[],
        )

        other_conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        with pytest.raises(HTTPException) as exc_info:
            await submit_message(
                db,
                other_conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id="cross-conversation",
                    source_run_id=source_run.id,
                    result_mode=RESULT_MODE_ENTRIES,
                ),
            )
        assert exc_info.value.status_code == 404

        with pytest.raises(HTTPException) as exc_info:
            await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id="same-result-mode",
                    source_run_id=source_run.id,
                    result_mode=RESULT_MODE_ANSWER,
                ),
            )
        assert exc_info.value.status_code == 422

        repeated_message, repeated_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="resubmit-question",
                source_run_id=source_run.id,
                result_mode=RESULT_MODE_ENTRIES,
            ),
        )

        assert repeated_message.content == source_message.content == "原始问题"
        assert repeated_message.scope_type == SCOPE_PROJECT
        assert repeated_message.project_id == source_project.id
        assert repeated_run.scope_type == SCOPE_PROJECT
        assert repeated_run.project_id == source_project.id
        assert repeated_run.input_context_version_id == source_context.id
        assert repeated_run.request_context_mode == "continue"
        assert repeated_run.request_answer_mode == "auto"
        assert repeated_run.request_result_mode == RESULT_MODE_ENTRIES
        assert repeated_run.context_decision == source_run.context_decision
        assert repeated_run.standalone_query == source_run.standalone_query
        assert repeated_run.topic_label == source_run.topic_label
        assert repeated_run.history_message_ids_json == source_run.history_message_ids_json
        # 创建模式纠正 Run 时不得提前关闭当前对话的活动工作集。
        assert (await get_active_context_version(db, conversation.id)).id == current_context.id


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
async def test_scope_change_same_scope_is_noop() -> None:
    """相同 Workspace/项目范围 PATCH 幂等 no-op：不追加事件、不改活动时间。"""
    async with async_session_factory() as db:
        user = await _user(db, "同范围")
        workspace = await _workspace_for(db, user)
        project = await _project(db, workspace, "同范围项目")
        workspace_conv = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        project_conv = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(
                scope_type="project",
                project_id=project.id,
            ),
        )
        await db.flush()
        workspace_activity = workspace_conv.last_activity_at
        project_activity = project_conv.last_activity_at

        returned_ws, event_ws = await change_scope(
            db,
            workspace_conv,
            KnowledgeScopeChangeRequest(scope_type="workspace"),
        )
        assert returned_ws.id == workspace_conv.id
        assert event_ws is None
        assert workspace_conv.last_activity_at == workspace_activity

        returned_project, event_project = await change_scope(
            db,
            project_conv,
            KnowledgeScopeChangeRequest(
                scope_type="project",
                project_id=project.id,
            ),
        )
        assert returned_project.id == project_conv.id
        assert event_project is None
        assert project_conv.last_activity_at == project_activity

        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeMessage)
                .where(KnowledgeMessage.conversation_id.in_(
                    [workspace_conv.id, project_conv.id]
                ))
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_scope_change_same_scope_during_active_run_is_noop() -> None:
    """活动 Run 期间提交相同范围仍为幂等 no-op，不返回 409、不产生事件。"""
    async with async_session_factory() as db:
        user = await _user(db, "活动同范围")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="active-same-1",
                message="进行中的问题",
            ),
        )
        await db.commit()

        returned, event = await change_scope(
            db,
            conversation,
            KnowledgeScopeChangeRequest(scope_type="workspace"),
        )
        assert returned.id == conversation.id
        assert event is None
        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeMessage)
                .where(KnowledgeMessage.conversation_id == conversation.id)
            )
        ).scalar_one()
        # 用户消息 + 助手占位，未新增 scope_change
        assert count == 2


@pytest.mark.asyncio
async def test_message_cursor_pagination() -> None:
    """游标分页：无 cursor 返回最近一页，页内正序，向前加载不重复不跳过。"""
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

        # 无 cursor：返回最近一页且页内按时间正序
        rows, next_cursor = await list_messages(
            db,
            conversation.id,
            limit=2,
        )
        assert [row.id for row in rows] == sorted(row.id for row in rows)
        user_contents = [
            row.content for row in rows if row.message_type == MESSAGE_TYPE_USER
        ]
        assert user_contents[-1] == "第 5 个问题"
        assert next_cursor is not None

        # 向前遍历全部消息：不重复、不遗漏；跨页顺序从最近到最早
        seen: list[int] = []
        cursor: str | None = None
        for _ in range(10):
            rows, cursor = await list_messages(
                db,
                conversation.id,
                cursor=cursor,
                limit=2,
            )
            assert [row.id for row in rows] == sorted(row.id for row in rows)
            seen.extend(reversed([row.id for row in rows]))
            if cursor is None:
                break
        # 每页 2 条、共 5 次提交 = 10 条消息
        assert len(seen) == 10
        assert len(set(seen)) == 10
        assert seen == sorted(seen, reverse=True)


@pytest.mark.asyncio
async def test_message_pagination_recent_first_and_before_cursor() -> None:
    """首页最近优先、尾页无游标、相同时间戳按 id 稳定排序且无重复。"""
    from datetime import UTC, datetime

    from sqlalchemy import update as sa_update

    async with async_session_factory() as db:
        user = await _user(db, "新分页")
        workspace = await _workspace_for(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        for index in range(6):
            _, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"np-{index}",
                    message=f"第 {index + 1} 个问题",
                ),
            )
            await db.commit()
            await cancel_run(db, run)
            await db.commit()

        # 把所有消息压到同一时间戳，验证 (created_at, id) 稳定序
        fixed_time = datetime.now(UTC)
        await db.execute(
            sa_update(KnowledgeMessage)
            .where(KnowledgeMessage.conversation_id == conversation.id)
            .values(created_at=fixed_time)
        )
        await db.commit()

        # 首页返回最近一页（最大 id 在后），页内正序
        rows, cursor = await list_messages(
            db,
            conversation.id,
            limit=3,
        )
        assert len(rows) == 3
        assert rows[-1].id == max(row.id for row in rows)
        user_contents = [
            row.content for row in rows if row.message_type == MESSAGE_TYPE_USER
        ]
        assert user_contents[-1] == "第 6 个问题"
        assert cursor is not None

        # 向前加载更早一页，与首页不重复
        older, cursor = await list_messages(
            db,
            conversation.id,
            cursor=cursor,
            limit=3,
        )
        assert len(older) == 3
        assert not {row.id for row in rows} & {row.id for row in older}
        older_user_contents = [
            row.content
            for row in older
            if row.message_type == MESSAGE_TYPE_USER
        ]
        assert older_user_contents[-1] == "第 5 个问题"
        before_cursor = cursor

        # 继续向前遍历全部剩余页：不重复、不遗漏，最终返回空页且无游标
        seen_ids = {row.id for row in rows} | {row.id for row in older}
        # 从最近页开始遍历：第 6 → 第 5 → … → 第 1
        all_user_contents = user_contents + older_user_contents
        cursor = before_cursor
        while cursor is not None:
            page, cursor = await list_messages(
                db,
                conversation.id,
                cursor=cursor,
                limit=3,
            )
            assert [row.id for row in page] == sorted(row.id for row in page)
            assert not seen_ids & {row.id for row in page}
            seen_ids |= {row.id for row in page}
            all_user_contents.extend(
                row.content
                for row in page
                if row.message_type == MESSAGE_TYPE_USER
            )
        # 12 条消息全部遍历且不重复；用户消息全部出现
        assert len(seen_ids) == 12
        assert sorted(all_user_contents) == [
            f"第 {index} 个问题" for index in range(1, 7)
        ]


@pytest.mark.asyncio
async def test_conversation_list_batch_hydrates_recent_run() -> None:
    """列表批量水合每个对话最近 Run 摘要，且只发一条 Runs 聚合查询。"""
    async with async_session_factory() as db:
        user = await _user(db, "列表Run")
        workspace = await _workspace_for(db, user)
        conversation_ids = []
        for index in range(3):
            conversation = await create_conversation(
                db,
                workspace.id,
                user.id,
                KnowledgeConversationCreate(scope_type="workspace"),
            )
            conversation_ids.append(conversation.id)
            for submit_index in range(2):
                _, run = await submit_message(
                    db,
                    conversation,
                    KnowledgeRunSubmitRequest(
                        client_message_id=f"list-{index}-{submit_index}",
                        message=f"列表问题 {index}-{submit_index}",
                    ),
                )
                await db.commit()
                await cancel_run(db, run)
                await db.commit()

        # 统计 list_conversations 期间对 knowledge_agent_runs 的 SELECT 次数
        run_select_count = {"count": 0}

        def _count_runs_select(conn, cursor, statement, parameters, context, executemany):
            if "FROM knowledge_agent_runs" in statement:
                run_select_count["count"] += 1

        event.listen(engine.sync_engine, "before_cursor_execute", _count_runs_select)
        try:
            summaries = await list_conversations(db, workspace.id, user.id)
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                _count_runs_select,
            )

        assert len(summaries) == 3
        for summary in summaries:
            assert summary.recent_run_id is not None
            assert summary.recent_run_status == RUN_CANCELLED
            assert summary.recent_run_updated_at is not None
        # 批量聚合查询只执行一次，不按会话逐条查询
        assert run_select_count["count"] == 1


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
