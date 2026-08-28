"""知识 Agent Worker 测试：原子领取、崩溃恢复、重试上限、取消与终态提交。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.knowledge_agent_worker import (
    claim_next_run,
    process_one_run,
    recover_stale_runs,
)
from app.models import (
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.tools import RunToolContext
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)
from tests.test_knowledge_agent_runner import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
    _conversation_and_run,
    _evidence_for_run,
    _fake_answer_agent,
    run_id_counter,
)


async def _cancel_other_waiting_runs(
    db,
    keep_run_id: int | None = None,
    keep_run_ids: set[int] | None = None,
) -> None:
    """取消共享测试库中其他等待 Run，确保 Worker 领取目标是本测试创建的 Run。"""
    keep = set(keep_run_ids or set())
    if keep_run_id is not None:
        keep.add(keep_run_id)
    rows = (
        await db.execute(
            select(KnowledgeAgentRun).where(KnowledgeAgentRun.status == RUN_WAITING)
        )
    ).scalars().all()
    for row in rows:
        if row.id in keep:
            continue
        row.status = RUN_CANCELLED
        row.active_slot = None
    await db.commit()


@pytest.mark.asyncio
async def test_claim_serial_processing() -> None:
    """原子领取：两个 waiting Run 依次领取，不会重复领取同一个。"""
    async with async_session_factory() as db:
        user = await create_user(db, "领取")
        workspace = await create_workspace(db, user)
        first = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="领取一",
        )
        second = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="领取二",
        )
        db.add(first)
        db.add(second)
        await db.flush()
        run_ids: set[int] = set()
        for conversation in (first, second):
            _message, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"claim-{run_id_counter()}",
                    message="问题",
                ),
            )
            run_ids.add(run.id)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_ids=run_ids)

        first_id = await claim_next_run()
        second_id = await claim_next_run()
        third_id = await claim_next_run()
        assert first_id is not None and second_id is not None
        assert first_id != second_id
        assert third_id is None
        assert {first_id, second_id} == run_ids

        async with async_session_factory() as db:
            runs = (
                await db.execute(select(KnowledgeAgentRun))
            ).scalars().all()
            claimed = {run for run in runs if run.id in {first_id, second_id}}
            assert all(run.status == RUN_PROCESSING for run in claimed)
            assert all(run.claimed_at is not None for run in claimed)


@pytest.mark.asyncio
async def test_recover_stale_run_requeues_once_then_fails() -> None:
    """租约超时的 processing Run 在重试上限内重新入队，超过则失败。"""
    async with async_session_factory() as db:
        user = await create_user(db, "恢复")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="恢复测试",
        )
        db.add(conversation)
        await db.flush()
        stale = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot="active",
            claimed_at=datetime.now(UTC) - timedelta(days=1),
            retry_count=0,
            max_retries=1,
        )
        exhausted = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot=None,
            claimed_at=datetime.now(UTC) - timedelta(days=1),
            retry_count=1,
            max_retries=1,
        )
        db.add(stale)
        db.add(exhausted)
        await db.commit()
        await _cancel_other_waiting_runs(db)

        recovered = await recover_stale_runs()
        assert recovered == 1
        await db.refresh(stale)
        await db.refresh(exhausted)
        assert stale.status == RUN_WAITING
        assert stale.retry_count == 1
        assert stale.claimed_at is None
        assert exhausted.status == RUN_FAILED
        assert exhausted.active_slot is None
        assert "超过恢复上限" in (exhausted.error or "")

        # 重新入队后可再次领取
        claimed_id = await claim_next_run()
        assert claimed_id == stale.id


@pytest.mark.asyncio
async def test_process_cancelled_run_releases_slot() -> None:
    """取消请求在领取后被处理：Run 标记 cancelled 且不写入回答。"""
    async with async_session_factory() as db:
        user = await create_user(db, "取消执行")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "取消项目")
        _conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run.cancel_requested = True
        await db.commit()

        assert await process_one_run() is True
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run.id)
            assert run.status == RUN_CANCELLED
            assert run.active_slot is None
            assert run.answer_json is None
            assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
            assert assistant.content == ""


@pytest.mark.asyncio
async def test_crash_recovery_requeues_and_retries_successfully(monkeypatch) -> None:
    """执行中异常：Run 重新入队一次且不留下半成品回答；重试后正常完成。"""
    async with async_session_factory() as db:
        user = await create_user(db, "崩溃恢复")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "恢复项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        _conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)

        # 第一次执行：构建引用阶段模拟崩溃
        async def _boom(db, run_id, draft):
            raise RuntimeError("模拟进程崩溃")

        with monkeypatch.context() as ctx:
            ctx.setattr(
                "app.services.knowledge_agent.runner.build_validated_answer",
                _boom,
            )
            assert await process_one_run() is True

        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run.id)
            assert run.status == RUN_WAITING
            assert run.retry_count == 1
            assert run.claimed_at is None
            assert run.answer_json is None
            assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
            assert assistant.content == ""

        # 第二次执行：正常完成
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run.id)
            ctx2 = RunToolContext(
                run_id=run.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                project_id=None,
                project_name=None,
            )
            verified = await _evidence_for_run(db, ctx2)
            handle = verified[0].evidence_handle
            await db.commit()
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验通常持续 24 小时。",
                    citations=[KnowledgeCitationDraft(evidence_handle=handle)],
                )
            ),
        )
        assert await process_one_run() is True
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run.id)
            assert run.status == RUN_COMPLETED
            assert run.active_slot is None
            answer = json.loads(run.answer_json)
            assert answer["citations"][0]["quote"] == "闭水试验通常持续 24 小时"


@pytest.mark.asyncio
async def test_retry_limit_exhausted_marks_failed(monkeypatch) -> None:
    """超过恢复上限：Run 进入 failed 终态并释放活动槽。"""
    async with async_session_factory() as db:
        user = await create_user(db, "超限")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "超限项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        _conversation, run = await _conversation_and_run(db, user, workspace)
        run.max_retries = 0
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)

        async def _boom(db, run_id, draft):
            raise RuntimeError("持续失败")

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.build_validated_answer",
            _boom,
        )
        assert await process_one_run() is True
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run.id)
            assert run.status == RUN_FAILED
            assert run.active_slot is None
            assert "超过恢复上限" in (run.error or "")
            assert run.answer_json is None
