"""知识 Agent Worker 当前统一链路、恢复、重试与取消测试。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.knowledge_agent_worker import claim_next_run, process_one_run, recover_stale_runs
from app.models import KnowledgeAgentRun, KnowledgeConversation, KnowledgeMessage
from app.models.knowledge_agent import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.run_control import RunCancelled
from app.services.knowledge_agent.runs import submit_message
from tests._knowledge_agent_fixtures import create_user, create_workspace
from tests.knowledge_agent_test_helpers import conversation_and_run, run_id_counter


async def _cancel_other_waiting_runs(
    db,
    keep_run_id: int | None = None,
    keep_run_ids: set[int] | None = None,
) -> None:
    """取消共享测试库中其他等待 Run，确保 Worker 领取本测试目标。"""
    keep = set(keep_run_ids or set())
    if keep_run_id is not None:
        keep.add(keep_run_id)
    rows = (
        await db.execute(
            select(KnowledgeAgentRun).where(KnowledgeAgentRun.status == RUN_WAITING)
        )
    ).scalars().all()
    for row in rows:
        if row.id not in keep:
            row.status = RUN_CANCELLED
            row.active_slot = None
    await db.commit()


@pytest.mark.asyncio
async def test_claim_serial_processing() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "领取")
        workspace = await create_workspace(db, user)
        conversations = [
            KnowledgeConversation(
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                title=f"领取{index}",
            )
            for index in range(2)
        ]
        db.add_all(conversations)
        await db.flush()
        run_ids: set[int] = set()
        for conversation in conversations:
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
    assert {first_id, second_id} == run_ids
    assert await claim_next_run() is None


@pytest.mark.asyncio
async def test_recover_current_claim_requeues_once_and_exhaustion_fails() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "恢复")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="恢复",
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
            current_step="claim",
            retry_count=0,
            max_retries=1,
        )
        exhausted = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            claimed_at=datetime.now(UTC) - timedelta(days=1),
            current_step="claim",
            retry_count=1,
            max_retries=1,
        )
        db.add_all([stale, exhausted])
        await db.commit()

        assert await recover_stale_runs() == 1
        await db.refresh(stale)
        await db.refresh(exhausted)
        assert stale.status == RUN_WAITING
        assert stale.retry_count == 1
        assert exhausted.status == RUN_FAILED
        assert "超过恢复上限" in (exhausted.error or "")


@pytest.mark.asyncio
async def test_recover_stale_legacy_answer_snapshot_fails_without_requeue() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "旧快照")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="旧快照",
        )
        db.add(conversation)
        await db.flush()
        legacy = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot="active",
            claimed_at=datetime.now(UTC) - timedelta(days=1),
            current_step="composite_answer_execute",
            run_kind="answer",
            retry_count=0,
            max_retries=1,
            composite_answer_execution_json='{"status":"processing"}',
        )
        db.add(legacy)
        await db.commit()

        assert await recover_stale_runs() == 0
        await db.refresh(legacy)
        assert legacy.status == RUN_FAILED
        assert legacy.active_slot is None
        assert legacy.retry_count == 0
        assert legacy.composite_answer_execution_json == '{"status":"processing"}'
        assert "旧或未知 answer 执行快照" in (legacy.error or "")


@pytest.mark.asyncio
async def test_recover_processing_without_claimed_at_fails() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "历史脏数据")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="历史恢复",
        )
        db.add(conversation)
        await db.flush()
        historical = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot="active",
            claimed_at=None,
            current_step="context_decision",
            run_kind="answer",
        )
        db.add(historical)
        await db.commit()

        assert await recover_stale_runs() == 0
        await db.refresh(historical)
        assert historical.status == RUN_FAILED
        assert historical.active_slot is None
        assert "缺少 claimed_at" in (historical.error or "")


@pytest.mark.asyncio
async def test_process_cancelled_run_releases_slot() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "取消")
        workspace = await create_workspace(db, user)
        _conversation, run = await conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run.cancel_requested = True
        await db.commit()
        run_id = run.id

    assert await process_one_run() is True
    async with async_session_factory() as db:
        final = await db.get(KnowledgeAgentRun, run_id)
        assert final.status == RUN_CANCELLED
        assert final.active_slot is None
        assert final.answer_json is None


@pytest.mark.asyncio
async def test_cancel_from_other_session_discards_late_result(monkeypatch) -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "跨会话取消")
        workspace = await create_workspace(db, user)
        _conversation, run = await conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

    async def adapter(db, current_run):
        async with async_session_factory() as other:
            row = await other.get(KnowledgeAgentRun, current_run.id)
            row.cancel_requested = True
            await other.commit()
        raise RunCancelled("跨会话取消")

    monkeypatch.setattr("app.knowledge_agent_worker.execute_dialogue_loop_run", adapter)
    assert await process_one_run() is True
    async with async_session_factory() as db:
        final = await db.get(KnowledgeAgentRun, run_id)
        assert final.status == RUN_CANCELLED
        assert final.active_slot is None
        assert final.answer_json is None


@pytest.mark.asyncio
async def test_dialogue_loop_crash_requeues_and_retries_same_run(monkeypatch) -> None:
    calls: list[int] = []

    async def adapter(db, run):
        calls.append(run.id)
        if len(calls) == 1:
            raise RuntimeError("统一循环中途崩溃")
        run.status = RUN_COMPLETED
        run.current_step = None
        run.active_slot = None
        run.answer_json = json.dumps({"answer": "恢复成功", "status": "completed"})

    monkeypatch.setattr("app.knowledge_agent_worker.execute_dialogue_loop_run", adapter)
    async with async_session_factory() as db:
        user = await create_user(db, "统一循环重试")
        workspace = await create_workspace(db, user)
        conversation, run = await conversation_and_run(db, user, workspace)
        run_id = run.id
        conversation_id = conversation.id
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    assert await process_one_run() is True
    assert await process_one_run() is True
    async with async_session_factory() as db:
        completed = await db.get(KnowledgeAgentRun, run_id)
        messages = (
            await db.execute(
                select(KnowledgeMessage).where(
                    KnowledgeMessage.conversation_id == conversation_id
                )
            )
        ).scalars().all()
        assert completed.status == RUN_COMPLETED
        assert calls == [run_id, run_id]
        assert len(messages) == 2


@pytest.mark.asyncio
async def test_retry_limit_exhausted_marks_failed(monkeypatch) -> None:
    async def boom(db, run):
        raise RuntimeError("持续失败")

    monkeypatch.setattr("app.knowledge_agent_worker.execute_dialogue_loop_run", boom)
    async with async_session_factory() as db:
        user = await create_user(db, "超限")
        workspace = await create_workspace(db, user)
        _conversation, run = await conversation_and_run(db, user, workspace)
        run.max_retries = 0
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

    assert await process_one_run() is True
    async with async_session_factory() as db:
        failed = await db.get(KnowledgeAgentRun, run_id)
        assert failed.status == RUN_FAILED
        assert failed.active_slot is None
        assert "超过恢复上限" in (failed.error or "")
