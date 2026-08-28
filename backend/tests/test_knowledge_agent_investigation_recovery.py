"""知识 Agent 调查恢复与取消测试：检查点、崩溃重放、取消与终态一致性。"""

import json
import uuid

import pytest
from sqlalchemy import select

from app.agents.investigation import InvestigationControllerDraft
from app.db.session import async_session_factory
from app.knowledge_agent_worker import claim_next_run, process_one_run
from app.models import (
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    ANSWER_MODE_INVESTIGATE,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_ROUND_COMPLETED,
    INVESTIGATION_STATUS_CANCELLED,
    INVESTIGATION_STATUS_COMPLETED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_PROCESSING,
    RUN_WAITING,
    STOP_REASON_CANCELLED,
    STOP_REASON_CONTROLLER_COMPLETE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.tools import SearchResultItem, SearchToolOutput
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
)
from tests.test_knowledge_agent_worker import _cancel_other_waiting_runs


def _search_result(entry, project_name: str = "项目") -> SearchResultItem:
    return SearchResultItem(
        entry_id=entry.id,
        title=entry.title,
        project_name=project_name,
        node_path="",
        summary=entry.content[:200],
        source_count=1,
    )


def _controller_meta() -> StageMeta:
    return StageMeta(
        purpose="investigation_controller",
        provider="llm",
        model="fake-controller",
        is_fallback=False,
        error=None,
        duration_ms=1,
    )


def _synthesis_meta() -> StageMeta:
    return StageMeta(
        purpose="synthesis",
        provider="llm",
        model="fake-synthesis",
        is_fallback=False,
        error=None,
        duration_ms=1,
    )


def _synthesis_agent(handle_by_entry: dict[int, str] | None = None):
    """综合回答替身：引用给定 Entry 的 Evidence 句柄。"""

    async def _fake(
        db,
        workspace_id,
        query,
        scope_label,
        entries,
        *,
        purpose=None,
        synthesis_context=None,
    ):
        citations = []
        for item in entries:
            for evidence in item.get("evidences", []):
                if handle_by_entry is None or item["entry_id"] in handle_by_entry:
                    citations.append(
                        KnowledgeCitationDraft(evidence_handle=evidence["handle"])
                    )
        return (
            KnowledgeAnswerDraft(
                answer="恢复后的综合回答。",
                citations=citations,
            ),
            _synthesis_meta(),
        )

    return _fake


def _scripted_search(results_by_query: dict[str, list]):
    async def _fake(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        items = results_by_query.get(query, [])
        for item in items:
            ctx.discovered_entry_ids.add(item.entry_id)
        return SearchToolOutput(items=items)

    return _fake


async def _investigate_run(db, user, workspace, message: str = "闭水试验放水时机？"):
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type="workspace",
        title="恢复测试对话",
    )
    db.add(conversation)
    await db.flush()
    _user_message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"recovery-{uuid.uuid4().hex[:8]}",
            message=message,
        ),
    )
    run.request_answer_mode = ANSWER_MODE_INVESTIGATE
    await db.flush()
    return conversation, run


async def _load_investigation(db, run_id):
    investigation = (
        await db.execute(
            select(KnowledgeInvestigation).where(
                KnowledgeInvestigation.run_id == run_id
            )
        )
    ).scalar_one_or_none()
    rounds = (
        await db.execute(
            select(KnowledgeInvestigationRound).where(
                KnowledgeInvestigationRound.investigation_id == investigation.id
            )
        )
    ).scalars().all()
    queries = (
        await db.execute(
            select(KnowledgeInvestigationQuery).where(
                KnowledgeInvestigationQuery.investigation_id == investigation.id
            )
        )
    ).scalars().all()
    return investigation, list(rounds), list(queries)


@pytest.mark.asyncio
async def test_crash_mid_round_resets_and_replays_without_duplicates(
    monkeypatch,
) -> None:
    """工具阶段崩溃：未完成轮次被安全重置重放，轮次/查询/Evidence/回答不重复。"""
    async with async_session_factory() as db:
        user = await create_user(db, "轮中崩溃")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "崩溃项目")
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
        _conversation, run = await _investigate_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

    state = {"crashed": False}

    async def _flaky_search(db, ctx, query, *, recall_limit, context_limit, seed_entries=None):
        if not state["crashed"]:
            state["crashed"] = True
            raise RuntimeError("模拟工具阶段进程崩溃")
        ctx.discovered_entry_ids.add(entry.id)
        return SearchToolOutput(items=[_search_result(entry)])

    async def _controller(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        if not executed_queries:
            return (
                InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                ),
                _controller_meta(),
            )
        return (
            InvestigationControllerDraft(action=INVESTIGATION_ACTION_ANSWER),
            _controller_meta(),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _flaky_search,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        _controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
        _synthesis_agent(),
    )

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_WAITING
        assert run.retry_count == 1

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_COMPLETED
        investigation, rounds, queries = await _load_investigation(db, run_id)
        assert investigation.status == INVESTIGATION_STATUS_COMPLETED
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        assert investigation.total_queries_executed == 1
        assert len(rounds) == 2  # 第 1 轮搜索 + 第 2 轮回答观察
        assert all(round_row.status == INVESTIGATION_ROUND_COMPLETED for round_row in rounds)
        assert len(queries) == 1
        evidences = (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == run_id
                )
            )
        ).scalars().all()
        assert len(evidences) == 1
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant.content == "恢复后的综合回答。"


@pytest.mark.asyncio
async def test_recovery_after_two_committed_rounds_resumes_third(monkeypatch) -> None:
    """完成两轮后崩溃：恢复复用已提交轮次与账本，从第三轮继续且不重复。"""
    async with async_session_factory() as db:
        user = await create_user(db, "两轮恢复")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "恢复项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验验收前不得放水。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="验收规则",
            content="闭水试验验收前不得放水。",
            quote="闭水试验验收前不得放水",
        )
        _conversation, run = await _investigate_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id
        entry_ids = {entry_a.id: entry_a, entry_b.id: entry_b}

    state = {"calls": 0}

    async def _controller(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        state["calls"] += 1
        if state["calls"] == 3:
            raise RuntimeError("模拟第三轮控制器调用前崩溃")
        if state["calls"] in (1, 2):
            query = "闭水试验持续多久" if state["calls"] == 1 else "闭水试验放水时机"
            return (
                InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=[query],
                ),
                _controller_meta(),
            )
        return (
            InvestigationControllerDraft(action=INVESTIGATION_ACTION_ANSWER),
            _controller_meta(),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        _controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _scripted_search(
            {
                "闭水试验持续多久": [_search_result(entry_a)],
                "闭水试验放水时机": [_search_result(entry_b)],
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
        _synthesis_agent(handle_by_entry=set(entry_ids)),
    )

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_WAITING
        assert run.retry_count == 1
        investigation, rounds, queries = await _load_investigation(db, run_id)
        assert investigation.current_round == 2
        assert len(rounds) == 2
        assert all(round_row.status == INVESTIGATION_ROUND_COMPLETED for round_row in rounds)
        assert len(queries) == 2

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_COMPLETED
        investigation, rounds, queries = await _load_investigation(db, run_id)
        assert investigation.current_round == 3
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        assert investigation.total_queries_executed == 2
        assert len(rounds) == 3
        assert len(queries) == 2
        answer = json.loads(run.answer_json)
        assert len(answer["citations"]) == 2


@pytest.mark.asyncio
async def test_cancel_during_investigation_preserves_audit(monkeypatch) -> None:
    """调查中跨会话取消：保留已提交轮次审计，不产生回答或工作集。"""
    async with async_session_factory() as db:
        user = await create_user(db, "调查取消")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "取消项目")
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
        _conversation, run = await _investigate_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id
        entry_id = entry.id

    async def _search_sets_cancel(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        async with async_session_factory() as other:
            other_run = await other.get(KnowledgeAgentRun, run_id)
            other_run.cancel_requested = True
            await other.commit()
        ctx.discovered_entry_ids.add(entry_id)
        return SearchToolOutput(items=[])

    async def _controller(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        return (
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_SEARCH,
                queries=["闭水试验"],
            ),
            _controller_meta(),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _search_sets_cancel,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        _controller,
    )

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_CANCELLED
        assert run.answer_json is None
        assert run.output_context_version_id is None
        investigation, rounds, queries = await _load_investigation(db, run_id)
        assert investigation.status == INVESTIGATION_STATUS_CANCELLED
        assert investigation.stop_reason == STOP_REASON_CANCELLED
        # 已提交的计划轮次保留审计
        assert len(rounds) >= 1
        assert len(queries) >= 1
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant.content == ""


@pytest.mark.asyncio
async def test_two_workers_compete_for_investigation_run() -> None:
    """两个 Worker 竞争：investigate Run 只能被一个 Worker 领取。"""
    async with async_session_factory() as db:
        user = await create_user(db, "竞争调查")
        workspace = await create_workspace(db, user)
        _conversation, run = await _investigate_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)

        first = await claim_next_run()
        second = await claim_next_run()
        assert first == run.id
        assert second is None
        run = await db.get(KnowledgeAgentRun, run.id)
        await db.refresh(run)
        assert run.status == RUN_PROCESSING


@pytest.mark.asyncio
async def test_final_transaction_failure_requeues_and_completes_once(
    monkeypatch,
) -> None:
    """最终事务失败：不暴露半成品答案，按租约恢复后只生成一次回答。"""
    async with async_session_factory() as db:
        user = await create_user(db, "终态失败")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "终态项目")
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
        _conversation, run = await _investigate_run(db, user, workspace)
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run_id = run.id

    async def _controller(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        if not executed_queries:
            return (
                InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                ),
                _controller_meta(),
            )
        return (
            InvestigationControllerDraft(action=INVESTIGATION_ACTION_ANSWER),
            _controller_meta(),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        _controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _scripted_search({"闭水试验持续多久": [_search_result(entry)]}),
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
        _synthesis_agent(),
    )

    from app.services.knowledge_agent import investigation_runner as inv_runner_module

    original_finalize = inv_runner_module.finalize_run
    state = {"failed": False}

    async def _flaky_finalize(db, run, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("模拟终态事务提交失败")
        return await original_finalize(db, run, **kwargs)

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.finalize_run",
        _flaky_finalize,
    )

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_WAITING
        assert run.retry_count == 1
        assert run.answer_json is None

    assert await process_one_run() is True
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run.status == RUN_COMPLETED
        assert run.answer_json is not None
        investigation, _rounds, _queries = await _load_investigation(db, run_id)
        assert investigation.status == INVESTIGATION_STATUS_COMPLETED
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        # 恢复不重复轮次：停止检查点已提交，恢复直接进入综合
        assert investigation.current_round == 2
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant.content == "恢复后的综合回答。"
        contexts = (
            await db.execute(
                select(KnowledgeContextVersion).where(
                    KnowledgeContextVersion.source_run_id == run_id
                )
            )
        ).scalars().all()
        assert len(contexts) == 1
