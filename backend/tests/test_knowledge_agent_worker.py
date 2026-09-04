"""知识 Agent Worker 测试：原子领取、崩溃恢复、重试上限、取消与终态提交。"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.knowledge_agent_worker import (
    claim_next_run,
    process_one_run,
    recover_stale_runs,
)
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    PURPOSE_BASIS_ROUTE,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_WORKSPACE,
    TOOL_ERROR,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.basis import BasisPlan
from app.services.knowledge_agent.composite_answer import (
    normalize_composite_answer_plan,
    plan_and_persist_composite_answer,
)
from app.services.knowledge_agent.composite_answer_execution import (
    composite_request_fingerprint,
    execute_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.structured_query_tools import (
    STRUCTURED_QUERY_TOOL_REGISTRY,
)
from app.services.knowledge_agent.tools import RunToolContext, SearchToolOutput
from app.services.knowledge_agent.working_set import (
    get_active_context_version,
    get_conversation_context_versions,
)
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


async def _never_cancel() -> None:
    return None


@pytest.mark.asyncio
async def test_composite_recovery_reuses_completed_fingerprint_and_runs_missing(
    monkeypatch,
) -> None:
    """租约恢复后复用已提交请求，只重放缺失的只读结构化请求。"""
    from app.services.knowledge_agent.structured_query_execution import (
        StructuredQueryExecutionResult,
    )

    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "total",
                    "order": 0,
                    "summary": "统计总数",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "nature",
                    "order": 1,
                    "summary": "按性质分组",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "first",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["total"],
                },
                {
                    "id": "second",
                    "entry_set": {},
                    "outputs": [
                        {"kind": "group_count", "group_by": "info_nature"}
                    ],
                    "requirement_ids": ["nature"],
                },
            ],
            "reason": "两份独立结构化输入",
        }
    )
    executed: list[str] = []

    async def _structured(db, ctx, query_plan, *, cancel_check, settings=None):
        await cancel_check()
        executed.append(query_plan.outputs[0].kind)
        return StructuredQueryExecutionResult(
            status="completed",
            set_completeness="complete",
            entries=None,
            count=None,
            group_counts=[
                {
                    "group_by": "info_nature",
                    "buckets": [{"key": "fact", "count": 2}],
                    "truncated": False,
                    "status": "completed",
                    "completeness": "complete",
                }
            ],
            output_completeness={
                "entries": None,
                "count": None,
                "group_count": {"info_nature": "complete"},
            },
            warnings=[],
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.execute_structured_query_plan",
        _structured,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "复合恢复")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "统计知识")
        first = plan.structured_requests[0]
        fingerprint = composite_request_fingerprint(
            run.id,
            plan,
            request_id=first.id,
            kind="structured",
            params=first.query_plan.model_dump(mode="json", by_alias=True),
        )
        fact = CompositeToolFact(
            handle="res_" + "1" * 24,
            request_id="s1",
            requirement_ids=["r1"],
            kind="count",
            text="符合条件的知识条目共 2 条。",
            completeness="complete",
            summary={"value": 2},
        )
        run.composite_answer_execution_json = CompositeAnswerExecutionSnapshot(
            inputs=[
                CompositeExecutionInputSnapshot(
                    request_id="s1",
                    kind="structured",
                    requirement_ids=["r1"],
                    fingerprint=fingerprint,
                    status="completed",
                    completeness="complete",
                    result_handles=[fact.handle],
                )
            ],
            tool_facts=[fact],
        ).model_dump_json()
        await db.commit()
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=run.scope_type,
            project_id=run.project_id,
            project_name=run.project_name,
        )
        result = await execute_composite_answer_plan(
            db,
            run,
            ctx,
            plan,
            cancel_check=_never_cancel,
        )

    assert executed == ["group_count"]
    assert [item.request_id for item in result.snapshot.inputs] == ["s1", "s2"]
    assert [fact.request_id for fact in result.snapshot.tool_facts] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_composite_recovery_reuses_persisted_planning_fallback(monkeypatch) -> None:
    """规划失败记录提交后，租约恢复不得再次调用规划模型。"""
    async def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("恢复不应重新规划")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _forbidden,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "规划失败恢复")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "复合问题")
        db.add(
            KnowledgeAgentModelInvocation(
                run_id=run.id,
                purpose="composite_answer_plan",
                prompt_version="v1",
                provider="llm",
                model="fake",
                is_fallback=True,
                error="规划失败",
                duration_ms=1,
            )
        )
        await db.commit()

        plan = await plan_and_persist_composite_answer(
            db,
            run,
            current_message="复合问题",
            standalone_query="复合问题",
            scope_label="全部知识",
            context_decision="new_topic",
            topic_summary=None,
            allowed_statements=[],
            feature_enabled=True,
        )
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose
                    == "composite_answer_plan",
                )
            )
        ).scalars().all()

    assert plan is None
    assert len(invocations) == 1


@pytest.mark.asyncio
async def test_composite_retrieval_exception_records_failed_tool_call(monkeypatch) -> None:
    """检索工具抛异常时同时保留失败审计和 partial 执行快照。"""
    plan = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "knowledge",
                    "order": 0,
                    "summary": "查询知识",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                }
            ],
            "retrieval_requests": [
                {
                    "id": "search",
                    "query": "测试检索",
                    "requirement_ids": ["knowledge"],
                }
            ],
        }
    )

    async def _failed_search(*args, **kwargs):
        raise RuntimeError("模拟检索失败")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _failed_search,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "检索失败审计")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "查询知识")
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=run.scope_type,
            project_id=run.project_id,
            project_name=run.project_name,
        )
        result = await execute_composite_answer_plan(
            db,
            run,
            ctx,
            plan,
            cancel_check=_never_cancel,
        )
        calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalars().all()

    assert result.snapshot.inputs[0].status == "partial"
    assert len(calls) == 1
    assert calls[0].tool_name == "search_confirmed_knowledge"
    assert calls[0].status == TOOL_ERROR
    assert "模拟检索失败" in (calls[0].error or "")


@pytest.mark.asyncio
async def test_tool_call_fingerprint_reuses_committed_aggregate_result() -> None:
    """同 Run/版本/参数指纹复用已提交 count，不重复执行并追加调用记录。"""
    async with async_session_factory() as db:
        user = await create_user(db, "工具恢复")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "有多少知识")
        run.status = RUN_PROCESSING
        await db.flush()
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=run.scope_type,
            project_id=run.project_id,
            project_name=run.project_name,
        )
        params = {"entry_set": {}, "operation": "count"}
        first = await dispatch_read_tool(
            db,
            ctx,
            tool_name="aggregate_entries",
            tool_version="v1",
            params=params,
            budget=ReadToolBudget(3, 3, 60000),
            cancel_check=_never_cancel,
            registry=STRUCTURED_QUERY_TOOL_REGISTRY,
        )
        await db.commit()
        second = await dispatch_read_tool(
            db,
            ctx,
            tool_name="aggregate_entries",
            tool_version="v1",
            params=params,
            budget=ReadToolBudget(3, 3, 60000),
            cancel_check=_never_cancel,
            registry=STRUCTURED_QUERY_TOOL_REGISTRY,
        )
        calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalars().all()

    assert first.reused is False
    assert second.reused is True
    assert second.payload == first.payload == {"value": 0}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_structured_query_cancel_during_plan_discards_late_plan(
    monkeypatch,
) -> None:
    """规划期间取消后，迟到计划不固化且 Worker 原子释放活动槽。"""

    async def _decide(db, **kwargs):
        del db
        message = kwargs["current_message"]
        return ContextDecisionResult(
            decision="new_topic",
            standalone_query=message,
            topic_label=message,
            clarify_question=None,
            degraded=False,
            history_message_ids=[],
            meta=StageMeta(
                purpose="context_decision",
                provider="server",
                model=None,
                is_fallback=False,
                error=None,
                duration_ms=0,
            ),
        )

    async def _planner(db, workspace_id, **kwargs):
        del db, workspace_id, kwargs
        async with async_session_factory() as other:
            row = await other.get(KnowledgeAgentRun, run_id)
            assert row is not None
            row.cancel_requested = True
            await other.commit()
        return (
            StructuredQueryPlanDraft.model_validate(
                {"entry_set": {}, "outputs": [{"kind": "count"}]}
            ),
            StageMeta(
                purpose="structured_query_plan",
                provider="test",
                model="test-model",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner",
        _planner,
    )
    monkeypatch.setattr(
        get_settings(), "knowledge_agent_structured_query_enabled", True
    )
    async with async_session_factory() as db:
        user = await create_user(db, "规划取消")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "统计知识")
        run.request_result_mode = "entries"
        run_id = run.id
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    assert await process_one_run() is True
    async with async_session_factory() as db:
        final = await db.get(KnowledgeAgentRun, run_id)
        assert final is not None
        assert final.status == RUN_CANCELLED
        assert final.active_slot is None
        assert final.structured_query_plan_json is None
        assert final.entry_result_json is None


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
        # 独立命名会话，避免遮蔽外层 db；退出 async with 后连接归还连接池
        async with async_session_factory() as check_db:
            run = await check_db.get(KnowledgeAgentRun, run.id)
            assert run.status == RUN_CANCELLED
            assert run.active_slot is None
            assert run.answer_json is None
            assistant = await check_db.get(KnowledgeMessage, run.assistant_message_id)
            assert assistant.content == ""


@pytest.mark.asyncio
async def test_cancel_from_other_session_during_processing(monkeypatch) -> None:
    """处理中跨会话取消：Worker 步骤边界必须读到取消标记并丢弃结果。"""
    async with async_session_factory() as db:
        user = await create_user(db, "跨会话取消")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
    run_id = run.id

    async def _search_sets_cancel(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        """模拟 Worker 持有 run 对象期间，另一个会话提交取消请求。"""
        async with async_session_factory() as other:
            other_run = await other.get(KnowledgeAgentRun, run_id)
            other_run.cancel_requested = True
            await other.commit()
        return SearchToolOutput(items=[])

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.search_confirmed_knowledge",
        _search_sets_cancel,
    )
    assert await process_one_run() is True

    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
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


@pytest.mark.asyncio
async def test_crash_recovery_reuses_input_version_without_duplicates(
    monkeypatch,
) -> None:
    """崩溃恢复继续使用 Run 固化输入版本；不重复决策、不产生多个活动版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "版本恢复")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "版本恢复项目")
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
        conversation, first_run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=first_run.id)

        # 第一轮：正常完成并建立活动版本
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, first_run.id)
            ctx = RunToolContext(
                run_id=run.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                project_id=None,
                project_name=None,
            )
            verified = await _evidence_for_run(db, ctx)
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
            first_run = await db.get(KnowledgeAgentRun, first_run.id)
            assert first_run.status == RUN_COMPLETED
            first_version = await get_active_context_version(db, conversation.id)
            assert first_version is not None
            assert first_version.source_run_id == first_run.id

        # 第二轮 continue：提交固化输入版本后在回答校验阶段崩溃
        async with async_session_factory() as db:
            _message, second_run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"recover-{run_id_counter()}",
                    message="为什么不能提前放水？",
                    context_mode="continue",
                ),
            )
            second_run_id = second_run.id
            assert second_run.input_context_version_id == first_version.id
            await db.commit()
            await _cancel_other_waiting_runs(db, keep_run_id=second_run_id)

        async def _boom(db, run_id, draft):
            raise RuntimeError("模拟回答校验阶段崩溃")

        with monkeypatch.context() as ctx:
            ctx.setattr(
                "app.services.knowledge_agent.runner.build_validated_answer",
                _boom,
            )
            assert await process_one_run() is True

        async with async_session_factory() as db:
            second_run = await db.get(KnowledgeAgentRun, second_run_id)
            assert second_run.status == RUN_WAITING
            assert second_run.retry_count == 1
            assert second_run.output_context_version_id is None
            assert second_run.input_context_version_id == first_version.id
            decision_calls = (
                await db.execute(
                    select(KnowledgeAgentModelInvocation).where(
                        KnowledgeAgentModelInvocation.run_id == second_run_id,
                        KnowledgeAgentModelInvocation.purpose == "context_decision",
                    )
                )
            ).scalars().all()
            assert len(decision_calls) == 1
            active = await get_active_context_version(db, conversation.id)
            assert active.id == first_version.id

        # 重试：复用已固化决策与输入版本，只生成一个输出版本
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, second_run_id)
            ctx = RunToolContext(
                run_id=run.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                project_id=None,
                project_name=None,
            )
            verified = await _evidence_for_run(db, ctx)
            retry_handle = verified[0].evidence_handle
            await db.commit()
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验验收前不得提前放水。",
                    citations=[KnowledgeCitationDraft(evidence_handle=retry_handle)],
                )
            ),
        )
        assert await process_one_run() is True

        async with async_session_factory() as db:
            second_run = await db.get(KnowledgeAgentRun, second_run_id)
            assert second_run.status == RUN_COMPLETED
            assert second_run.output_context_version_id is not None
            versions = await get_conversation_context_versions(
                db, conversation.id
            )
            assert len(versions) == 2
            active = await get_active_context_version(db, conversation.id)
            assert active.id == second_run.output_context_version_id
            assert active.parent_version_id == first_version.id
            decision_calls = (
                await db.execute(
                    select(KnowledgeAgentModelInvocation).where(
                        KnowledgeAgentModelInvocation.run_id == second_run_id,
                        KnowledgeAgentModelInvocation.purpose == "context_decision",
                    )
                )
            ).scalars().all()
            assert len(decision_calls) == 1
            assistant = await db.get(KnowledgeMessage, second_run.assistant_message_id)
            assert assistant.content == "闭水试验验收前不得提前放水。"


@pytest.mark.asyncio
async def test_basis_crash_recovery_reuses_plan_without_replan(monkeypatch) -> None:
    """依据规划已提交后崩溃：恢复复用同一策略，不重复调用规划器。"""
    calls = {"plan": 0}

    async def _plan(
        db,
        *,
        workspace_id,
        request_basis_mode,
        objective,
        scope_label,
        topic_summary,
        context_decision,
        current_message,
        allowed_statements,
        feature_enabled,
    ):
        calls["plan"] += 1
        return BasisPlan(
            strategy="hybrid",
            needs_grove=True,
            requires_external_material=False,
            candidate_statement_ids=[allowed_statements[-1].message_id],
            degraded=False,
            meta=StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model="fake-basis",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan",
        _plan,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "依据恢复")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "依据恢复项目")
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
        run.request_basis_mode = "auto"
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

        async def _boom_search(*args, **kwargs):
            raise RuntimeError("模拟规划提交后、搜索前崩溃")

        with monkeypatch.context() as ctx:
            ctx.setattr(
                "app.services.knowledge_agent.runner.search_confirmed_knowledge",
                _boom_search,
            )
            assert await process_one_run() is True

        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            assert run.status == RUN_WAITING
            assert run.retry_count == 1
            assert run.planned_basis_strategy == "hybrid"
            assert run.planned_basis_json is not None
            assert run.answer_json is None
            assert run.answer_basis_json is None
        assert calls["plan"] == 1

        # 第二次处理：复用已提交规划完成（不重新规划）
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            ctx2 = RunToolContext(
                run_id=run.id,
                workspace_id=run.workspace_id,
                owner_user_id=run.owner_user_id,
                scope_type=run.scope_type,
                project_id=run.project_id,
                project_name=run.project_name,
            )
            verified = await _evidence_for_run(db, ctx2)
            handle = verified[0].evidence_handle
            await db.commit()
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _open_fake_answer_agent(handle),
        )
        assert await process_one_run() is True

        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            assert run.status == RUN_COMPLETED
            assert run.planned_basis_strategy == "hybrid"
            basis = json.loads(run.answer_basis_json)
            assert basis["grove"]["used"] is True
            assert basis["grove"]["citation_count"] == 1
            assert basis["user_statements"]["message_ids"] == [run.user_message_id]
            invocations = (
                await db.execute(
                    select(KnowledgeAgentModelInvocation).where(
                        KnowledgeAgentModelInvocation.run_id == run_id,
                        KnowledgeAgentModelInvocation.purpose == PURPOSE_BASIS_ROUTE,
                    )
                )
            ).scalars().all()
            assert len(invocations) == 1
        assert calls["plan"] == 1


def _open_fake_answer_agent(handle: str):
    """接受开放参数并引用给定句柄的回答替身。"""

    async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
        return (
            KnowledgeAnswerDraft(
                answer="闭水试验通常持续 24 小时。",
                citations=[KnowledgeCitationDraft(evidence_handle=handle)],
                core_question_answered=True,
                coverage_complete=True,
            ),
            StageMeta(
                purpose="answer",
                provider="llm",
                model="fake-answer",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    return _fake


@pytest.mark.asyncio
async def test_cancelled_open_run_does_not_commit_late_answer_or_basis(
    monkeypatch,
) -> None:
    """开放 Run 取消：已提交的规划保留，但迟到回答与实际依据都不落库。"""
    async def _plan(
        db,
        *,
        workspace_id,
        request_basis_mode,
        objective,
        scope_label,
        topic_summary,
        context_decision,
        current_message,
        allowed_statements,
        feature_enabled,
    ):
        return BasisPlan(
            strategy="model_first",
            needs_grove=False,
            requires_external_material=False,
            candidate_statement_ids=[],
            degraded=False,
            meta=StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model="fake-basis",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan",
        _plan,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "取消开放")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="解释通用概念",
        )
        run.request_basis_mode = "auto"
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

    async def _answer_sets_cancel(
        db,
        workspace_id,
        query,
        scope_label,
        entries,
        **kwargs,
    ):
        """模拟模型返回前，另一会话提交取消请求。"""
        async with async_session_factory() as other:
            other_run = await other.get(KnowledgeAgentRun, run_id)
            other_run.cancel_requested = True
            await other.commit()
        return (
            KnowledgeAnswerDraft(
                answer="迟到的一般回答。",
                core_question_answered=True,
                coverage_complete=True,
            ),
            StageMeta(
                purpose="answer",
                provider="llm",
                model="fake-answer",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _answer_sets_cancel,
    )
    assert await process_one_run() is True

    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_CANCELLED
        assert run.active_slot is None
        assert run.answer_json is None
        assert run.answer_basis_json is None
        # 规划检查点已提交：策略保留供审计，未漂移为其他模式
        assert run.planned_basis_strategy == "model_first"
