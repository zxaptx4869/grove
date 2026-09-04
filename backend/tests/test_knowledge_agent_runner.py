"""知识 Agent 固定执行图与分阶段可观测性测试。"""

import json
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from app.agents.knowledge_agent import (
    KnowledgeAnswerDraft,
    KnowledgeAnswerPointDraft,
    KnowledgeCitationDraft,
)
from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import Settings
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeWorkingSetItem,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    BASIS_STRATEGY_HYBRID,
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_MODEL_FIRST,
    CONTEXT_DECISION_CLARIFY,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_DECISION_NEW_TOPIC,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_SUPERSEDED,
    PURPOSE_BASIS_ROUTE,
    RESULT_MODE_ENTRIES,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_PROCESSING,
    SCOPE_WORKSPACE,
    STEP_SEARCH,
    TOOL_EMPTY,
    TOOL_ERROR,
    TOOL_PARTIAL,
)
from app.schemas.knowledge_agent import KnowledgeAnswerOut, KnowledgeRunSubmitRequest
from app.services.knowledge_agent.basis import BasisPlan, build_answer_basis
from app.services.knowledge_agent.composite_answer import (
    normalize_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_response import (
    CompositeAnswerResult,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
)
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.observability import StageMeta, run_fallback_summary
from app.services.knowledge_agent.runner import RunCancelled, execute_run
from app.services.knowledge_agent.runs import (
    read_run_cancel_state,
    submit_message,
    update_run_step,
)
from app.services.knowledge_agent.shared_execution_graph import (
    compile_shared_execution_graph,
    dump_shared_execution_graph,
    execute_shared_execution_graph_plan,
    run_scope_fingerprint,
)
from app.services.knowledge_agent.structured_query import (
    plan_and_persist_structured_query,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    search_confirmed_knowledge,
)
from app.services.knowledge_agent.working_set import get_active_context_version
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


async def _conversation_and_run(db, user, workspace, message: str = "闭水试验通常持续多久？"):
    """创建对话与 waiting Run（经服务幂等提交）。"""
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="执行测试",
    )
    db.add(conversation)
    await db.flush()
    user_message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"run-{run_id_counter()}",
            message=message,
        ),
    )
    del user_message
    return conversation, run


_counter = 0


@pytest.fixture(autouse=True)
def _default_decision(monkeypatch):
    """默认上下文决策替身：非降级 new_topic，避免离线模型污染正常路径断言。"""

    async def _decide(
        db,
        *,
        workspace_id,
        conversation_id,
        current_message,
        request_mode,
        active_topic_label,
        working_set_titles,
        history_limit,
        history_message_chars,
        user_message_id=None,
        exclude_run_id=None,
    ):
        return ContextDecisionResult(
            decision="new_topic",
            standalone_query=current_message,
            topic_label=current_message[:30],
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

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.decide_context",
        _decide,
    )

    async def _resolve_mode(
        db,
        *,
        workspace_id,
        request_mode,
        objective,
        topic_summary,
    ):
        # 默认快速路径：不产生路由降级，避免污染既有无降级断言
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        return AnswerModeResolution(mode="quick")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _resolve_mode,
    )

    async def _resolve_result_mode(
        db,
        *,
        workspace_id,
        request_mode,
        objective,
        scope_label,
        topic_summary,
    ):
        # 默认走综合回答路径：不产生结果形态路由调用，避免污染既有断言
        from app.services.knowledge_agent.result_mode import ResultModeResolution

        return ResultModeResolution(mode="answer")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _resolve_result_mode,
    )


def run_id_counter() -> str:
    global _counter
    _counter += 1
    return str(_counter)


async def _evidence_for_run(db, ctx: RunToolContext, query: str = "闭水试验") -> list:
    """执行搜索/读取/证据步骤，预生成 Evidence（与 execute_run 共用去重）。"""
    search = await search_confirmed_knowledge(
        db,
        ctx,
        query,
        recall_limit=10,
        context_limit=5,
    )
    entries = await read_entries(
        db,
        ctx,
        [item.entry_id for item in search.items],
    )
    verified: list = []
    for item in entries.items:
        result = await read_source_evidence(
            db,
            ctx,
            item.entry_id,
            [source["source_id"] for source in item.sources],
        )
        verified.extend(row for row in result.items if row.citable)
    return verified


def _fake_answer_agent(draft: KnowledgeAnswerDraft, *, fallback: bool = False):
    """构造回答 Agent 的替身：返回固定草稿与阶段元数据。"""

    async def _fake(db, workspace_id, query, scope_label, entries):
        return (
            draft,
            StageMeta(
                purpose="answer",
                provider="offline" if fallback else "llm",
                model=None if fallback else "fake-answer",
                is_fallback=fallback,
                error="未配置文本模型密钥" if fallback else None,
                duration_ms=1,
            ),
        )

    return _fake


def _dynamic_answer_agent():
    """回答替身：引用回答上下文里实际提供的第一个 Evidence 句柄。"""

    async def _fake(db, workspace_id, query, scope_label, entries):
        handle = ""
        for item in entries:
            if item.get("evidences"):
                handle = item["evidences"][0]["handle"]
                break
        return (
            KnowledgeAnswerDraft(
                answer="基于已有证据的回答。",
                citations=[KnowledgeCitationDraft(evidence_handle=handle)] if handle else [],
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


def _offline_open_answer_agent():
    """离线兜底回答替身：接受开放参数，返回不可用元数据。"""

    async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
        return (
            KnowledgeAnswerDraft(
                answer="当前没有可用的文本模型，无法生成回答。",
                insufficient=True,
                insufficient_note="文本模型不可用",
            ),
            StageMeta(
                purpose="answer",
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=1,
            ),
        )

    return _fake


@pytest.mark.asyncio
async def test_runner_normal_completion_with_verified_citation(monkeypatch) -> None:
    """正常回答：原子提交结构化回答、引用与活动槽释放，各阶段可观测。"""
    async with async_session_factory() as db:
        user = await create_user(db, "执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "执行项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="验收手册",
            text_content="闭水试验通常持续 24 小时，验收前不得放水。",
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
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        # 预生成 Evidence，获取真实句柄后让回答模型引用
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        assert verified
        handle = verified[0].evidence_handle
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="闭水试验通常持续 24 小时。",
            citations=[KnowledgeCitationDraft(evidence_handle=handle)],
            conflicts=[],
            core_question_answered=True,
            coverage_complete=True,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(draft),
        )
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert run.active_slot is None
        assert run.current_step is None
        answer = json.loads(run.answer_json)
        assert answer["answer"] == "闭水试验通常持续 24 小时。"
        assert answer["status"] == "completed"
        assert answer["citations"][0]["evidence_handle"] == handle
        assert answer["citations"][0]["quote"] == "闭水试验通常持续 24 小时"
        assert answer["citations"][0]["entry_id"] == entry.id

        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant is not None
        assert assistant.content == "闭水试验通常持续 24 小时。"

        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalars().all()
        purposes = {item.purpose for item in invocations}
        assert {"embedding", "rerank", "answer"} <= purposes
        assert any(item.purpose == "answer" and item.model == "fake-answer" for item in invocations)
        tool_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalars().all()
        assert {item.tool_name for item in tool_calls} >= {
            "search_confirmed_knowledge",
            "read_entries",
            "read_source_evidence",
        }


@pytest.mark.asyncio
async def test_runner_all_stages_normal_has_no_fallback(monkeypatch) -> None:
    """全阶段真实模型成功时 Run 无降级摘要。"""
    from app.services.embedding import EmbeddingResult

    async with async_session_factory() as db:
        user = await create_user(db, "全正常")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "正常项目")
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
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

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

        async def _fake_encode(db, workspace_id, text, *, model=None, client=None):
            return EmbeddingResult(
                vector=[0.1] * 256,
                provider="doubao",
                model="test-embedding",
                is_fallback=False,
                error=None,
            )

        async def _fake_semantic(db, workspace_id, query, candidates):
            from app.agents.semantic import SemanticRankingDraft, SemanticRankResult

            return (
                SemanticRankingDraft(
                    results=[
                        SemanticRankResult(entry_id=item.id, reason="测试")
                        for item in candidates
                    ]
                ),
                "llm",
                "fake-rerank",
                False,
                None,
            )

        monkeypatch.setattr(
            "app.services.vector_search.encode_text",
            _fake_encode,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.tools.run_semantic_agent",
            _fake_semantic,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="正常回答。",
                    citations=[KnowledgeCitationDraft(evidence_handle=handle)],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is False
        assert run.status == RUN_COMPLETED


@pytest.mark.asyncio
async def test_runner_no_relevant_entries_is_insufficient() -> None:
    """无相关正式知识：回答明确知识不足，不调用回答模型。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无知识")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空项目")
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="完全不存在的主题",
        )
        await db.commit()
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        assert "没有召回相关正式 Entry" in answer["insufficient_note"]
        assert answer["citations"] == []
        # 正常空搜索不得被误报为模型 fallback
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is False
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant.content == answer["answer"]


@pytest.mark.asyncio
async def test_runner_no_verifiable_evidence_is_partial() -> None:
    """有 Entry 但无可核验证据：Run 标记 partial，回答标记知识不足。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无证据")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "证据项目")
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
            quote=None,
        )
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        assert "没有可核验的 Source 证据" in answer["insufficient_note"]


@pytest.mark.asyncio
async def test_runner_answer_model_unavailable_is_partial_failed(monkeypatch) -> None:
    """回答模型不可用：Run 为 partial 且回答状态 failed，不伪装成功。"""
    async with async_session_factory() as db:
        user = await create_user(db, "回答失败")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "失败项目")
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
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="没有可用的文本模型。",
                    insufficient=True,
                    insufficient_note="文本模型不可用",
                ),
                fallback=True,
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "failed"
        assert "文本模型不可用" in answer["insufficient_note"]
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is True


@pytest.mark.asyncio
async def test_runner_tool_budget_limits_evidence_reads(monkeypatch) -> None:
    """证据读取预算生效：达到上限后停止扩张并基于已有证据完成。"""
    async with async_session_factory() as db:
        user = await create_user(db, "预算")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "预算项目")
        node = await create_child_node(db, project, "施工")
        first_source, first_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="手册一",
            text_content="闭水试验通常持续 24 小时。",
        )
        second_source, second_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="手册二",
            text_content="闭水试验放水前应做标记。",
        )
        first_entry = await create_entry_with_evidence(
            db,
            project,
            node,
            first_source,
            first_attachment,
            title="闭水试验一",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        second_entry = await create_entry_with_evidence(
            db,
            project,
            node,
            second_source,
            second_attachment,
            title="闭水试验二",
            content="闭水试验放水前应做标记。",
            quote="闭水试验放水前应做标记",
        )
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        search = await search_confirmed_knowledge(
            db,
            ctx,
            "闭水试验",
            recall_limit=10,
            context_limit=5,
        )
        entries = await read_entries(
            db,
            ctx,
            [item.entry_id for item in search.items],
        )
        assert {item.entry_id for item in entries.items} == {
            first_entry.id,
            second_entry.id,
        }
        await db.commit()

        fake_settings = SimpleNamespace(
            knowledge_agent_recall_limit=10,
            knowledge_agent_context_limit=5,
            knowledge_agent_evidence_limit=1,
            knowledge_agent_history_limit=8,
            knowledge_agent_history_message_chars=500,
            knowledge_agent_working_set_limit=15,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.get_settings",
            lambda: fake_settings,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _dynamic_answer_agent(),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        tool_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id,
                    KnowledgeAgentToolCall.tool_name == "read_source_evidence",
                )
            )
        ).scalars().all()
        assert len(tool_calls) == 1
        answer = json.loads(run.answer_json)
        assert answer["status"] == "completed"
        assert len(answer["citations"]) == 1


@pytest.mark.asyncio
async def test_runner_conflicts_kept_with_both_evidence(monkeypatch) -> None:
    """冲突双方都有有效 Evidence 时并列展示。"""
    from app.agents.knowledge_agent import KnowledgeConflictDraft

    async with async_session_factory() as db:
        user = await create_user(db, "冲突")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "冲突项目")
        first_node = await create_child_node(db, project, "A")
        second_node = await create_child_node(db, project, "B")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            title="观点甲",
            text_content="闭水试验应持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            title="观点乙",
            text_content="闭水试验应持续 48 小时。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            first_node,
            source_a,
            attachment_a,
            title="观点甲",
            content="闭水试验应持续 24 小时。",
            quote="闭水试验应持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            second_node,
            source_b,
            attachment_b,
            title="观点乙",
            content="闭水试验应持续 48 小时。",
            quote="闭水试验应持续 48 小时",
        )
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        by_entry = {item.entry_id: item for item in verified}
        assert entry_a.id in by_entry and entry_b.id in by_entry
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="两方观点不一致。",
                    citations=[],
                    conflicts=[
                        KnowledgeConflictDraft(
                            evidence_handle_a=by_entry[entry_a.id].evidence_handle,
                            evidence_handle_b=by_entry[entry_b.id].evidence_handle,
                            summary="持续时间说法矛盾",
                        )
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        answer = json.loads(run.answer_json)
        assert len(answer["conflicts"]) == 1
        conflict = answer["conflicts"][0]
        assert conflict["entry_title_a"] == "观点甲"
        assert conflict["entry_title_b"] == "观点乙"


@pytest.mark.asyncio
async def test_runner_cancel_raises_at_step_boundary() -> None:
    """步骤边界检测取消：短会话读到已提交取消，RunCancelled 抛出。"""
    async with async_session_factory() as db:
        user = await create_user(db, "取消边界")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "取消项目")
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        run.status = RUN_PROCESSING
        run.cancel_requested = True
        await db.commit()
        with pytest.raises(RunCancelled):
            await execute_run(db, run)
        await db.rollback()


@pytest.mark.asyncio
async def test_run_step_short_session_visible_and_terminal_guard() -> None:
    """短会话步骤更新立即可见；终态后迟到步骤不得覆盖。"""
    async with async_session_factory() as db:
        user = await create_user(db, "短会话步骤")
        workspace = await create_workspace(db, user)
        conversation, run = await _conversation_and_run(db, user, workspace)
        run.status = RUN_PROCESSING
        await db.commit()
        run_id = run.id

        await update_run_step(run_id, STEP_SEARCH)
        async with async_session_factory() as fresh:
            row = await fresh.get(KnowledgeAgentRun, run_id)
            assert row.current_step == STEP_SEARCH

        # 另一会话直接提交取消，短会话读取可见
        async with async_session_factory() as other:
            other_run = await other.get(KnowledgeAgentRun, run_id)
            other_run.cancel_requested = True
            await other.commit()
        cancel_requested, status = await read_run_cancel_state(run_id)
        assert cancel_requested is True
        assert status == RUN_PROCESSING

        # 终态后迟到步骤更新被活动状态条件阻止
        async with async_session_factory() as final:
            final_run = await final.get(KnowledgeAgentRun, run_id)
            final_run.status = RUN_COMPLETED
            final_run.current_step = None
            final_run.active_slot = None
            await final.commit()
        await update_run_step(run_id, "late_step")
        async with async_session_factory() as verify:
            row = await verify.get(KnowledgeAgentRun, run_id)
            assert row.status == RUN_COMPLETED
            assert row.current_step is None


@pytest.mark.asyncio
async def test_tool_summary_empty_not_fallback_and_error_affected() -> None:
    """工具降级汇总：正常 empty 不算 fallback，error/partial 进入受影响阶段。"""
    async with async_session_factory() as db:
        user = await create_user(db, "工具汇总")
        workspace = await create_workspace(db, user)
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()
        db.add(
            KnowledgeAgentToolCall(
                run_id=run.id,
                sequence=1,
                tool_name="search_confirmed_knowledge",
                status=TOOL_EMPTY,
                duration_ms=1,
            )
        )
        db.add(
            KnowledgeAgentToolCall(
                run_id=run.id,
                sequence=2,
                tool_name="read_source_evidence",
                status=TOOL_ERROR,
                error="数据库读取失败",
                duration_ms=1,
            )
        )
        db.add(
            KnowledgeAgentToolCall(
                run_id=run.id,
                sequence=3,
                tool_name="read_entries",
                status=TOOL_PARTIAL,
                error="部分对象越权或不可用",
                duration_ms=1,
            )
        )
        await db.commit()

        summary = await run_fallback_summary(db, run.id)
        assert summary["has_fallback"] is True
        purposes = {stage["purpose"] for stage in summary["stages"]}
        assert "tool:search_confirmed_knowledge" not in purposes
        assert "tool:read_source_evidence" in purposes
        assert "tool:read_entries" in purposes
        error_stage = next(
            stage
            for stage in summary["stages"]
            if stage["purpose"] == "tool:read_source_evidence"
        )
        assert error_stage["is_fallback"] is True
        assert "数据库读取失败" in error_stage["error"]
        partial_stage = next(
            stage
            for stage in summary["stages"]
            if stage["purpose"] == "tool:read_entries"
        )
        assert partial_stage["is_fallback"] is True


@pytest.mark.asyncio
async def test_runner_all_references_invalid_marks_partial(monkeypatch) -> None:
    """事实性回答全部引用失效：回答 insufficient 且 Run 至少为 partial。"""
    async with async_session_factory() as db:
        user = await create_user(db, "引用全失效")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "失效项目")
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
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验通常持续 24 小时。",
                    citations=[
                        KnowledgeCitationDraft(evidence_handle="ev_other_run"),
                        KnowledgeCitationDraft(evidence_handle="ev_unknown"),
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        assert "全部引用被丢弃" in (answer["insufficient_note"] or "")
        assert answer["citations"] == []
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is True
        assert any(
            stage["purpose"] == "validate_refs" for stage in summary["stages"]
        )


@pytest.mark.asyncio
async def test_runner_partial_references_invalid_marks_partial(monkeypatch) -> None:
    """部分句柄失效：保留有效引用，回答与 Run 标记 partial。"""
    async with async_session_factory() as db:
        user = await create_user(db, "引用部分失效")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "部分失效项目")
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
        conversation, run = await _conversation_and_run(db, user, workspace)
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        assert verified
        handle = verified[0].evidence_handle
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验通常持续 24 小时。",
                    citations=[
                        KnowledgeCitationDraft(evidence_handle=handle),
                        KnowledgeCitationDraft(evidence_handle="ev_fake"),
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "partial"
        assert len(answer["citations"]) == 1
        assert answer["citations"][0]["evidence_handle"] == handle
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is True


def _fixed_decision(
    decision: str,
    standalone_query: str,
    *,
    topic_label: str | None = None,
    clarify_question: str | None = None,
):
    """构造固定决策替身。"""

    async def _fake(
        db,
        *,
        workspace_id,
        conversation_id,
        current_message,
        request_mode,
        active_topic_label,
        working_set_titles,
        history_limit,
        history_message_chars,
        user_message_id=None,
        exclude_run_id=None,
    ):
        return ContextDecisionResult(
            decision=decision,
            standalone_query=standalone_query,
            topic_label=topic_label or active_topic_label or current_message[:30],
            clarify_question=clarify_question,
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

    return _fake


async def _make_active_version(
    db,
    conversation,
    user,
    workspace,
    *,
    topic_label: str = "闭水试验",
    entry_ids=(),
    project_name: str | None = None,
) -> KnowledgeContextVersion:
    """直接创建活动工作集版本（用于 runner 连续追问测试）。"""
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
    for order, entry_id in enumerate(entry_ids):
        db.add(
            KnowledgeWorkingSetItem(
                context_version_id=version.id,
                entry_id=entry_id,
                entry_title=f"Entry{entry_id}",
                project_name=project_name,
                include_reason="cited",
                sort_order=order,
            )
        )
    await db.flush()
    return version


@pytest.mark.asyncio
async def test_runner_continue_merges_seed_and_new_discovery(monkeypatch) -> None:
    """省略追问：continue 合并复验种子与新发现 Entry，生成输出版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "省略追问")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "追问项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            title="手册甲",
            text_content="闭水试验通常持续 24 小时，验收前不得提前放水。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            title="手册乙",
            text_content="闭水试验放水前应做水位标记。",
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
            title="放水标记",
            content="闭水试验放水前应做水位标记。",
            quote="闭水试验放水前应做水位标记",
        )
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="为什么不能提前放水？",
        )
        version = await _make_active_version(
            db,
            conversation,
            user,
            workspace,
            entry_ids=[entry_a.id],
            project_name="追问项目",
        )
        run.input_context_version_id = version.id
        run.request_context_mode = "continue"
        await db.commit()

        # 本轮重新读取种子与新发现 Entry，生成本 Run Evidence
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        by_entry = {item.entry_id: item for item in verified}
        await db.commit()
        assert entry_a.id in by_entry and entry_b.id in by_entry

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.decide_context",
            _fixed_decision(
                CONTEXT_DECISION_CONTINUE,
                "闭水试验为什么不能提前放水？",
                topic_label="闭水试验",
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验验收前不得提前放水，放水前应做水位标记。",
                    citations=[
                        KnowledgeCitationDraft(
                            evidence_handle=by_entry[entry_b.id].evidence_handle
                        )
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert run.context_decision == CONTEXT_DECISION_CONTINUE
        assert run.standalone_query == "闭水试验为什么不能提前放水？"
        assert run.output_context_version_id is not None
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.id == run.output_context_version_id
        assert active.version_number == 2
        assert active.parent_version_id == version.id
        items = (
            await db.execute(
                select(KnowledgeWorkingSetItem)
                .where(KnowledgeWorkingSetItem.context_version_id == active.id)
                .order_by(KnowledgeWorkingSetItem.sort_order)
            )
        ).scalars().all()
        # 本轮引用优先，旧有效项按最近使用保留
        assert [item.entry_id for item in items] == [entry_b.id, entry_a.id]
        assert items[0].include_reason == "cited"
        assert items[0].source_run_id == run.id
        assert items[1].include_reason == "recent"
        seed_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id,
                    KnowledgeAgentToolCall.tool_name == "working_set_seed",
                )
            )
        ).scalars().all()
        assert len(seed_calls) == 1
        assert json.loads(seed_calls[0].result_summary)["valid"] == 1


@pytest.mark.asyncio
async def test_runner_new_topic_replaces_working_set(monkeypatch) -> None:
    """新话题：不使用旧工作集种子，输出版本替换旧主题。"""
    async with async_session_factory() as db:
        user = await create_user(db, "新话题替换")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "替换项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "庭院")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            title="旧手册",
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            title="庭院手册",
            text_content="庭院树木冬季需要防冻保护。",
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
            title="树木防冻",
            content="庭院树木冬季需要防冻保护。",
            quote="庭院树木冬季需要防冻保护",
        )
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="庭院树木冬季怎么养护？",
        )
        version = await _make_active_version(
            db,
            conversation,
            user,
            workspace,
            entry_ids=[entry_a.id],
            project_name="替换项目",
        )
        run.input_context_version_id = version.id
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx, query="庭院")
        by_entry = {item.entry_id: item for item in verified}
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.decide_context",
            _fixed_decision(
                CONTEXT_DECISION_NEW_TOPIC,
                "庭院树木冬季养护要点",
                topic_label="庭院养护",
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="庭院树木冬季需要防冻保护。",
                    citations=[
                        KnowledgeCitationDraft(
                            evidence_handle=by_entry[entry_b.id].evidence_handle
                        )
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert run.context_decision == CONTEXT_DECISION_NEW_TOPIC
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.topic_label == "庭院养护"
        assert active.parent_version_id == version.id
        items = (
            await db.execute(
                select(KnowledgeWorkingSetItem).where(
                    KnowledgeWorkingSetItem.context_version_id == active.id
                )
            )
        ).scalars().all()
        assert [item.entry_id for item in items] == [entry_b.id]
        await db.refresh(version)
        assert version.status == CONTEXT_STATUS_SUPERSEDED


@pytest.mark.asyncio
async def test_runner_clarify_replies_without_search_or_version(monkeypatch) -> None:
    """澄清分支：直接回复，不检索、不生成输出工作集版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "澄清分支")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "澄清项目")
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="它的验收标准是什么？",
        )
        version = await _make_active_version(
            db,
            conversation,
            user,
            workspace,
            topic_label="闭水试验",
        )
        run.input_context_version_id = version.id
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.decide_context",
            _fixed_decision(
                CONTEXT_DECISION_CLARIFY,
                "它的验收标准是什么？",
                clarify_question="你指的是哪个方案的验收标准？",
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert run.output_context_version_id is None
        answer = json.loads(run.answer_json)
        assert answer["status"] == "clarification"
        assert answer["answer"] == "你指的是哪个方案的验收标准？"
        assert answer["citations"] == []
        tool_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalars().all()
        assert tool_calls == []
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.id == version.id


@pytest.mark.asyncio
async def test_runner_continue_seed_deleted_records_unavailable(monkeypatch) -> None:
    """工作集种子失效：只记录不可用并继续新检索，不把删除项写入输出版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "种子失效")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "失效项目")
        node = await create_child_node(db, project, "施工")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            title="旧来源",
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            title="新来源",
            text_content="闭水试验验收前不得放水。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node,
            source_b,
            attachment_b,
            title="验收规则",
            content="闭水试验验收前不得放水。",
            quote="闭水试验验收前不得放水",
        )
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="验收前可以放水吗？",
        )
        version = await _make_active_version(
            db,
            conversation,
            user,
            workspace,
            entry_ids=[entry_a.id],
            project_name="失效项目",
        )
        run.input_context_version_id = version.id
        run.request_context_mode = "continue"
        await db.commit()
        await db.delete(entry_a)
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx, query="验收")
        by_entry = {item.entry_id: item for item in verified}
        await db.commit()

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.decide_context",
            _fixed_decision(
                CONTEXT_DECISION_CONTINUE,
                "闭水试验验收前可以放水吗？",
                topic_label="闭水试验",
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验验收前不得放水。",
                    citations=[
                        KnowledgeCitationDraft(
                            evidence_handle=by_entry[entry_b.id].evidence_handle
                        )
                    ],
                )
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        seed_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id,
                    KnowledgeAgentToolCall.tool_name == "working_set_seed",
                )
            )
        ).scalars().all()
        assert len(seed_calls) == 1
        seed_result = json.loads(seed_calls[0].result_summary)
        assert seed_result["valid"] == 0
        assert seed_result["unavailable"] == 1
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        items = (
            await db.execute(
                select(KnowledgeWorkingSetItem).where(
                    KnowledgeWorkingSetItem.context_version_id == active.id
                )
            )
        ).scalars().all()
        assert [item.entry_id for item in items] == [entry_b.id]


@pytest.mark.asyncio
async def test_runner_historical_evidence_rejected_and_context_kept(monkeypatch) -> None:
    """历史 Run Evidence 句柄拒绝复用；continue 无有效引用不推进工作集。"""
    async with async_session_factory() as db:
        user = await create_user(db, "历史证据")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "历史项目")
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
        conversation, first_run = await _conversation_and_run(
            db, user, workspace
        )
        ctx = RunToolContext(
            run_id=first_run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        old_handle = verified[0].evidence_handle
        await db.commit()
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验通常持续 24 小时。",
                    citations=[KnowledgeCitationDraft(evidence_handle=old_handle)],
                )
            ),
        )
        first_run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, first_run)
        await db.commit()
        assert first_run.status == RUN_COMPLETED
        version = await get_active_context_version(db, conversation.id)
        assert version is not None
        assert version.source_run_id == first_run.id

        # 第二轮继续：回答模型引用上一轮句柄 → 全部丢弃
        _message, second_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"second-{run_id_counter()}",
                message="为什么不能提前放水？",
                context_mode="continue",
            ),
        )
        second_run.input_context_version_id = version.id
        await db.commit()
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.decide_context",
            _fixed_decision(
                CONTEXT_DECISION_CONTINUE,
                "闭水试验为什么不能提前放水？",
                topic_label="闭水试验",
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _fake_answer_agent(
                KnowledgeAnswerDraft(
                    answer="闭水试验为什么不能提前放水？",
                    citations=[KnowledgeCitationDraft(evidence_handle=old_handle)],
                )
            ),
        )
        second_run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, second_run)
        await db.commit()

        assert second_run.status == RUN_PARTIAL
        answer = json.loads(second_run.answer_json)
        assert answer["status"] == "insufficient"
        assert answer["citations"] == []
        assert second_run.output_context_version_id is None
        active = await get_active_context_version(db, conversation.id)
        assert active is not None
        assert active.id == version.id


@pytest.mark.asyncio
async def test_answer_agent_offline_when_no_key(monkeypatch) -> None:
    """未配置密钥时回答 Agent 返回离线兜底与降级元数据。"""
    from app.agents.knowledge_agent import run_knowledge_answer_agent

    async with async_session_factory() as db:
        user = await create_user(db, "离线回答")
        workspace = await create_workspace(db, user)
        async def _fake_offline_model(db, workspace_id):
            return TestModel()

        monkeypatch.setattr(
            "app.agents.knowledge_agent.get_text_model",
            _fake_offline_model,
        )
        draft, meta = await run_knowledge_answer_agent(
            db,
            workspace.id,
            "问题",
            "全部知识",
            [],
        )
        assert draft.insufficient is True
        assert "没有可用的文本模型" in draft.answer
        assert meta.is_fallback is True
        assert meta.purpose == "answer"


@pytest.mark.asyncio
async def test_basis_explicit_knowledge_only_skips_planner_invocation(
    monkeypatch,
) -> None:
    """显式 knowledge_only（特性关闭默认）直接固化 Grove-only，不记录规划调用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "依据显式")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="依据显式测试",
        )
        db.add(conversation)
        await db.flush()
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"basis-explicit-{run_id_counter()}",
                message="只根据我的知识库回答",
                basis_mode="knowledge_only",
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.planned_basis_strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose == PURPOSE_BASIS_ROUTE,
                )
            )
        ).scalars().all()
        assert invocations == []
        summary = await run_fallback_summary(db, run.id)
        assert not any(
            stage["purpose"] == PURPOSE_BASIS_ROUTE for stage in summary["stages"]
        )


@pytest.mark.asyncio
async def test_basis_auto_planner_success_recorded(monkeypatch) -> None:
    """auto 规划成功：Run 保存策略并记录 basis_route 模型调用。"""
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
            strategy=BASIS_STRATEGY_HYBRID,
            needs_grove=True,
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
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _offline_open_answer_agent(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "依据自动")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="依据自动测试",
        )
        db.add(conversation)
        await db.flush()
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"basis-auto-{run_id_counter()}",
                message="结合我的预算与项目记录给建议",
                basis_mode="auto",
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.planned_basis_strategy == BASIS_STRATEGY_HYBRID
        invocation = (
            await db.execute(
                select(KnowledgeAgentModelInvocation)
                .where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose == PURPOSE_BASIS_ROUTE,
                )
                .order_by(KnowledgeAgentModelInvocation.id)
            )
        ).scalar_one_or_none()
        assert invocation is not None
        assert invocation.provider == "llm"
        assert invocation.model == "fake-basis"
        assert invocation.is_fallback is False
        assert invocation.prompt_version == "v2"


@pytest.mark.asyncio
async def test_basis_planning_fallback_visible_in_summary(monkeypatch) -> None:
    """规划失败显式回退 Grove-only，且回答即使成功也保留 basis fallback。"""
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
            strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY,
            needs_grove=True,
            candidate_statement_ids=[],
            degraded=True,
            meta=StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan",
        _plan,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "依据回退")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="依据回退测试",
        )
        db.add(conversation)
        await db.flush()
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"basis-fallback-{run_id_counter()}",
                message="解释概念",
                basis_mode="auto",
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.planned_basis_strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
        summary = await run_fallback_summary(db, run.id)
        assert summary["has_fallback"] is True
        basis_stages = [
            stage
            for stage in summary["stages"]
            if stage["purpose"] == PURPOSE_BASIS_ROUTE
        ]
        assert basis_stages
        assert basis_stages[0]["is_fallback"] is True
        assert "未配置文本模型密钥" in (basis_stages[0]["error"] or "")


@pytest.mark.asyncio
async def test_basis_unknown_statement_ids_dropped_with_anomaly(monkeypatch) -> None:
    """规划输出未知消息句柄：丢弃并在审计/降级摘要中可见。"""
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
            strategy=BASIS_STRATEGY_MODEL_FIRST,
            needs_grove=False,
            candidate_statement_ids=[11],
            degraded=True,
            meta=StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model="fake-basis",
                is_fallback=True,
                error="依据规划输出含非法句柄；丢弃 1 个不在允许集合内的用户消息 ID：999",
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan",
        _plan,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _offline_open_answer_agent(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "依据句柄")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="依据句柄测试",
        )
        db.add(conversation)
        await db.flush()
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"basis-handle-{run_id_counter()}",
                message="结合我的情况回答",
                basis_mode="auto",
            ),
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.planned_basis_strategy == BASIS_STRATEGY_MODEL_FIRST
        summary = await run_fallback_summary(db, run.id)
        errors = " | ".join(
            stage["error"] or "" for stage in summary["stages"]
        )
        assert "999" in errors


@pytest.mark.asyncio
async def test_model_first_quick_skips_grove_and_completes(monkeypatch) -> None:
    """model-first 自动模式：跳过 Grove 工具并完成无 Citation 开放回答。"""
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
            strategy=BASIS_STRATEGY_MODEL_FIRST,
            needs_grove=False,
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

    def _open_answer_agent():
        async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
            assert kwargs.get("allow_model_knowledge") is True
            return (
                KnowledgeAnswerDraft(
                    lead="通用解释。",
                    points=[
                        KnowledgeAnswerPointDraft(
                            text="闭水试验是防水验收的一种现场试验。",
                            evidence_handles=[],
                        )
                    ],
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

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _open_answer_agent(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "模型优先")
        workspace = await create_workspace(db, user)
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="什么是闭水试验？",
        )
        run.request_basis_mode = "auto"
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.actual_answer_mode == "quick"
        assert run.planned_basis_strategy == BASIS_STRATEGY_MODEL_FIRST
        answer = json.loads(run.answer_json)
        assert answer["status"] == "completed"
        assert answer["citations"] == []
        tool_names = [
            tool.tool_name
            for tool in (
                await db.execute(
                    select(KnowledgeAgentToolCall).where(
                        KnowledgeAgentToolCall.run_id == run.id
                    )
                )
            ).scalars().all()
        ]
        assert "search_confirmed_knowledge" not in tool_names
        assert "read_source_evidence" not in tool_names
        # 正常跳过 Grove 不是 fallback：降级摘要不含伪工具错误
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is False


@pytest.mark.asyncio
async def test_composite_quick_routes_before_plan_and_skips_legacy_basis(monkeypatch) -> None:
    """特性开启后 quick 按回答模式→计划→执行→综合，不再整题二选一。"""
    events: list[str] = []
    settings = Settings(knowledge_agent_composite_answer_enabled=True)
    monkeypatch.setattr("app.services.knowledge_agent.runner.get_settings", lambda: settings)

    async def _answer_mode(*args, **kwargs):
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        events.append("answer_mode")
        return AnswerModeResolution(mode="quick")

    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "definition",
                    "order": 0,
                    "summary": "解释甲醛是什么",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [],
            "reason": "通用解释",
        }
    )

    async def _plan(*args, **kwargs):
        events.append("plan")
        return plan

    async def _execute(*args, **kwargs):
        events.append("execute")
        return SimpleNamespace(snapshot=CompositeAnswerExecutionSnapshot())

    async def _build(*args, **kwargs):
        events.append("synthesize")
        answer = KnowledgeAnswerOut(
            answer="甲醛是一种挥发性有机化合物。",
            status="completed",
            points=[
                {
                    "section": "定义",
                    "text": "甲醛是一种挥发性有机化合物。",
                    "requirement_ids": ["r1"],
                }
            ],
        )
        return CompositeAnswerResult(
            answer=answer,
            coverage=CompositeAnswerCoverageSnapshot(
                requirements=[
                    {
                        "requirement_id": "r1",
                        "status": "answered",
                        "model_knowledge_used": True,
                    }
                ]
            ),
            answer_basis=build_answer_basis(
                answer=answer,
                user_statement_ids=[],
                model_knowledge_used=True,
                external_material_required=False,
            ),
            run_status=RUN_COMPLETED,
            answer_fallback=False,
        )

    async def _forbidden_basis(*args, **kwargs):  # pragma: no cover
        raise AssertionError("复合 quick 不应再执行旧 basis 规划")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode", _answer_mode
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.plan_and_persist_composite_answer", _plan
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.execute_composite_answer_plan",
        _execute,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.build_composite_answer", _build
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan", _forbidden_basis
    )

    async with async_session_factory() as db:
        user = await create_user(db, "复合顺序")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="甲醛是什么？",
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert events == ["answer_mode", "plan", "execute", "synthesize"]
        assert run.status == RUN_COMPLETED
        assert run.composite_answer_coverage_json is not None
        assert json.loads(run.answer_json)["points"][0]["requirement_ids"] == ["r1"]


@pytest.mark.asyncio
async def test_composite_quick_runs_one_bounded_coverage_repair(monkeypatch) -> None:
    """首次 partial 只补查新请求，再综合改善 coverage 并固化一次终态。"""
    from app.agents.coverage_repair import CoverageRepairPlanDraft

    settings = Settings(
        knowledge_agent_composite_answer_enabled=True,
        knowledge_agent_coverage_repair_enabled=True,
        knowledge_agent_shared_execution_graph_enabled=False,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.get_settings", lambda: settings)
    plan = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "source",
                    "order": 0,
                    "summary": "说明知识中的材料来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                }
            ],
            "retrieval_requests": [
                {
                    "id": "initial",
                    "query": "甲醛 来源",
                    "requirement_ids": ["source"],
                }
            ],
        }
    )
    events: list[str] = []

    async def answer_mode(*args, **kwargs):
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        return AnswerModeResolution(mode="quick")

    async def plan_answer(*args, **kwargs):
        return plan

    async def execute(db, run, ctx, current_plan, **kwargs):
        request = current_plan.retrieval_requests[0]
        events.append(f"execute:{request.id}")
        if request.id == "q1":
            return SimpleNamespace(
                snapshot=CompositeAnswerExecutionSnapshot(
                    inputs=[
                        CompositeExecutionInputSnapshot(
                            request_id="q1",
                            kind="retrieval",
                            requirement_ids=["r1"],
                            fingerprint="a" * 64,
                            status="limited",
                            completeness="limited",
                        )
                    ]
                )
            )
        return SimpleNamespace(
            snapshot=CompositeAnswerExecutionSnapshot(
                inputs=[
                    CompositeExecutionInputSnapshot(
                        request_id="q2",
                        kind="retrieval",
                        requirement_ids=["r1"],
                        fingerprint="b" * 64,
                        status="completed",
                        completeness="limited",
                        evidence_handles=["ev_repair"],
                    )
                ]
            )
        )

    async def planner(*args, **kwargs):
        events.append("repair_plan")
        return (
            CoverageRepairPlanDraft.model_validate(
                {
                    "target_requirement_ids": ["r1"],
                    "retrieval_requests": [
                        {
                            "id": "repair",
                            "query": "装修材料 释放源",
                            "requirement_ids": ["r1"],
                        }
                    ],
                }
            ),
            StageMeta(
                purpose="coverage_repair_plan",
                provider="test",
                model="test",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    build_count = 0

    async def build(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        improved = build_count == 2
        events.append("repair_synthesis" if improved else "baseline_synthesis")
        answer = KnowledgeAnswerOut(
            answer="已说明材料来源。" if improved else "暂缺材料来源。",
            status="completed" if improved else "partial",
        )
        return CompositeAnswerResult(
            answer=answer,
            coverage=CompositeAnswerCoverageSnapshot(
                requirements=[
                    {
                        "requirement_id": "r1",
                        "status": "answered" if improved else "partial",
                        "evidence_handles": ["ev_repair"] if improved else [],
                        "note": None if improved else "相关输入为部分结果或执行不完整",
                    }
                ]
            ),
            answer_basis=build_answer_basis(
                answer=answer,
                user_statement_ids=[],
                model_knowledge_used=False,
                external_material_required=False,
            ),
            run_status=RUN_COMPLETED if improved else RUN_PARTIAL,
            answer_fallback=False,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode", answer_mode
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.plan_and_persist_composite_answer",
        plan_answer,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "execute_composite_answer_plan",
        execute,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.coverage_repair.run_coverage_repair_planner",
        planner,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.build_composite_answer", build)

    async with async_session_factory() as db:
        user = await create_user(db, "覆盖补查")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(
            db, user, workspace, "甲醛可能来自哪些材料？"
        )
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert events == [
            "execute:q1",
            "baseline_synthesis",
            "repair_plan",
            "execute:q2",
            "repair_synthesis",
        ]
        assert run.status == RUN_COMPLETED
        assert json.loads(run.answer_json)["answer"] == "已说明材料来源。"
        control = json.loads(run.coverage_repair_json)
        assert control["stage"] == "completed"
        assert control["planner_attempted"] is True
        assert control["synthesis_attempted"] is True
        assert control["stop_reason"] == "completed"
        assert run.composite_answer_execution_json is None
        assert run.coverage_repair_execution_json is None


@pytest.mark.asyncio
async def test_composite_quick_skips_repair_when_coverage_is_complete(monkeypatch) -> None:
    """首次完整回答不调用补查 planner，并固化确定性 not_needed。"""
    settings = Settings(
        knowledge_agent_composite_answer_enabled=True,
        knowledge_agent_coverage_repair_enabled=True,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.get_settings", lambda: settings)
    plan = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "definition",
                    "order": 0,
                    "summary": "解释概念",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ]
        }
    )

    async def answer_mode(*args, **kwargs):
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        return AnswerModeResolution(mode="quick")

    async def execute(*args, **kwargs):
        return SimpleNamespace(snapshot=CompositeAnswerExecutionSnapshot())

    async def plan_answer(*args, **kwargs):
        return plan

    async def build(*args, **kwargs):
        answer = KnowledgeAnswerOut(answer="解释完整。", status="completed")
        return CompositeAnswerResult(
            answer=answer,
            coverage=CompositeAnswerCoverageSnapshot(
                requirements=[{"requirement_id": "r1", "status": "answered"}]
            ),
            answer_basis=build_answer_basis(
                answer=answer,
                user_statement_ids=[],
                model_knowledge_used=True,
                external_material_required=False,
            ),
            run_status=RUN_COMPLETED,
            answer_fallback=False,
        )

    async def forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("完整 coverage 不应调用补查 planner")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode", answer_mode
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.plan_and_persist_composite_answer",
        plan_answer,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "execute_composite_answer_plan",
        execute,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.build_composite_answer", build)
    monkeypatch.setattr(
        "app.services.knowledge_agent.coverage_repair.run_coverage_repair_planner",
        forbidden,
    )

    async with async_session_factory() as db:
        user = await create_user(db, "完整跳过")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "解释概念")
        run.status = RUN_PROCESSING
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert json.loads(run.coverage_repair_json)["stop_reason"] == "not_needed"
        assert run.status == RUN_COMPLETED


@pytest.mark.asyncio
async def test_runner_restores_completed_repair_when_feature_flags_are_disabled(
    monkeypatch,
) -> None:
    """部署关闭父开关和补查开关后，已有补查 Run 仍从冻结终态恢复。"""
    from app.services.knowledge_agent.coverage_repair import (
        CoverageRepairBudget,
        CoverageRepairSnapshot,
        coverage_repair_material_from_result,
        dump_coverage_repair_snapshot,
    )

    settings = Settings(
        knowledge_agent_composite_answer_enabled=False,
        knowledge_agent_coverage_repair_enabled=False,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.get_settings", lambda: settings)
    plan = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "definition",
                    "order": 0,
                    "summary": "解释概念",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ]
        }
    )
    answer = KnowledgeAnswerOut(answer="冻结补查终态", status="completed")
    final_result = CompositeAnswerResult(
        answer=answer,
        coverage=CompositeAnswerCoverageSnapshot(
            requirements=[{"requirement_id": "r1", "status": "answered"}]
        ),
        answer_basis=build_answer_basis(
            answer=answer,
            user_statement_ids=[],
            model_knowledge_used=True,
            external_material_required=False,
        ),
        run_status=RUN_COMPLETED,
        answer_fallback=False,
    )

    async def answer_mode(*args, **kwargs):
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        return AnswerModeResolution(mode="quick")

    async def plan_answer(*args, **kwargs):
        return plan

    async def execute(*args, **kwargs):
        return SimpleNamespace(snapshot=CompositeAnswerExecutionSnapshot())

    async def forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("已完成补查恢复不得重新综合")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode", answer_mode
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.plan_and_persist_composite_answer",
        plan_answer,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "execute_composite_answer_plan",
        execute,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.build_composite_answer", forbidden
    )

    async with async_session_factory() as db:
        user = await create_user(db, "补查开关恢复")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "解释概念")
        run.status = RUN_PROCESSING
        material = coverage_repair_material_from_result(final_result)
        run.coverage_repair_json = dump_coverage_repair_snapshot(
            CoverageRepairSnapshot(
                stage="completed",
                execution_mode="serial",
                frozen_budget=CoverageRepairBudget(),
                baseline=material,
                final_result=material,
                stop_reason="completed",
            ),
            settings=settings,
        )
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert json.loads(run.answer_json)["answer"] == "冻结补查终态"


@pytest.mark.asyncio
async def test_coverage_repair_regression_restores_baseline_and_records_fallback(
    monkeypatch,
) -> None:
    """再综合 coverage 退化时不覆盖首次答案，并留下显式 server fallback。"""
    from app.services.knowledge_agent.coverage_repair import (
        CoverageRepairBudget,
        CoverageRepairSnapshot,
        coverage_repair_material_from_result,
        dump_coverage_repair_plan,
        dump_coverage_repair_snapshot,
        normalize_coverage_repair_plan,
    )
    from app.services.knowledge_agent.runner import _run_bounded_coverage_repair

    settings = Settings(
        knowledge_agent_composite_answer_enabled=True,
        knowledge_agent_coverage_repair_enabled=True,
    )
    plan = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "source",
                    "order": 0,
                    "summary": "说明来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                }
            ],
            "retrieval_requests": [
                {
                    "id": "initial",
                    "query": "甲醛 来源",
                    "requirement_ids": ["source"],
                }
            ],
        }
    )
    original_execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r1"],
                fingerprint="a" * 64,
                status="limited",
                completeness="limited",
            )
        ]
    )
    baseline_answer = KnowledgeAnswerOut(answer="首次部分回答", status="partial")
    baseline = CompositeAnswerResult(
        answer=baseline_answer,
        coverage=CompositeAnswerCoverageSnapshot(
            requirements=[{"requirement_id": "r1", "status": "partial"}]
        ),
        answer_basis=build_answer_basis(
            answer=baseline_answer,
            user_statement_ids=[],
            model_knowledge_used=False,
            external_material_required=False,
        ),
        run_status=RUN_PARTIAL,
        answer_fallback=False,
    )
    budget = CoverageRepairBudget()
    repair_plan = normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r1"],
            "retrieval_requests": [
                {
                    "id": "repair",
                    "query": "装修材料 释放源",
                    "requirement_ids": ["r1"],
                }
            ],
        },
        original_plan=plan,
        eligible_requirement_ids={"r1"},
        scope_fingerprint="scope-a",
        budget=budget,
        settings=settings,
    )
    repair_execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q2",
                kind="retrieval",
                requirement_ids=["r1"],
                fingerprint="b" * 64,
                status="completed",
                completeness="limited",
                evidence_handles=["ev_repair"],
            )
        ]
    )

    async def regressive_build(*args, **kwargs):
        answer = KnowledgeAnswerOut(answer="退化候选", status="insufficient")
        return CompositeAnswerResult(
            answer=answer,
            coverage=CompositeAnswerCoverageSnapshot(
                requirements=[{"requirement_id": "r1", "status": "insufficient"}]
            ),
            answer_basis=build_answer_basis(
                answer=answer,
                user_statement_ids=[],
                model_knowledge_used=False,
                external_material_required=False,
            ),
            run_status=RUN_COMPLETED,
            answer_fallback=False,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.build_composite_answer",
        regressive_build,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "补查非退化")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "说明来源")
        run.status = RUN_PROCESSING
        snapshot = CoverageRepairSnapshot(
            stage="execution_ready",
            execution_mode="serial",
            frozen_budget=budget,
            eligible_requirement_ids=["r1"],
            baseline=coverage_repair_material_from_result(baseline),
            planner_attempted=True,
        )
        run.coverage_repair_json = dump_coverage_repair_snapshot(
            snapshot, settings=settings
        )
        run.coverage_repair_plan_json = dump_coverage_repair_plan(
            repair_plan, budget=budget, settings=settings
        )
        run.coverage_repair_execution_json = repair_execution.model_dump_json()
        await db.commit()
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )

        result = await _run_bounded_coverage_repair(
            db,
            run,
            ctx,
            plan,
            original_execution,
            snapshot,
            current_message="说明来源",
            standalone_query="说明来源",
            scope="全部知识",
            statement_context=[],
            settings=settings,
        )

        assert result.answer.answer == "首次部分回答"
        control = json.loads(run.coverage_repair_json)
        assert control["stage"] == "failed"
        assert control["stop_reason"] == "synthesis_failed"
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose
                    == "coverage_repair_synthesis",
                )
            )
        ).scalars().all()
        assert len(invocations) == 1
        assert invocations[0].is_fallback is True


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_empty_snapshot", [False, True])
async def test_runner_restores_persisted_graph_when_switch_is_disabled(
    monkeypatch, corrupt_empty_snapshot: bool
) -> None:
    """部署回滚开关后，已有图 Run 仍由共享图入口恢复，不整体串行重跑。"""
    settings = Settings(
        knowledge_agent_composite_answer_enabled=True,
        knowledge_agent_shared_execution_graph_enabled=False,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.get_settings", lambda: settings)
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计知识数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                }
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "s1",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["count"],
                }
            ],
        }
    )
    selected: list[str] = []

    async def _plan(*args, **kwargs):
        return plan

    async def _shared(db, run, ctx, current_plan, **kwargs):
        selected.append("shared")
        assert run.shared_execution_graph_json is not None
        return SimpleNamespace(snapshot=CompositeAnswerExecutionSnapshot())

    async def _serial(*args, **kwargs):
        selected.append("serial")
        raise AssertionError("已有固化图不得回退串行执行")

    async def _build(*args, **kwargs):
        answer = KnowledgeAnswerOut(answer="共 0 条", status="completed")
        return CompositeAnswerResult(
            answer=answer,
            coverage=CompositeAnswerCoverageSnapshot(
                requirements=[
                    {"requirement_id": "r1", "status": "answered", "model_knowledge_used": False}
                ]
            ),
            answer_basis=build_answer_basis(
                answer=answer,
                user_statement_ids=[],
                model_knowledge_used=False,
                external_material_required=False,
            ),
            run_status=RUN_COMPLETED,
            answer_fallback=False,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.plan_and_persist_composite_answer", _plan
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.shared_execution_graph.execute_shared_execution_graph_plan",
        _shared,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.execute_composite_answer_plan",
        _serial,
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.build_composite_answer", _build)
    async with async_session_factory() as db:
        user = await create_user(db, "固化图回滚")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "有多少知识？")
        run.status = RUN_PROCESSING
        run.shared_execution_graph_json = (
            ""
            if corrupt_empty_snapshot
            else dump_shared_execution_graph(
                compile_shared_execution_graph(
                    plan,
                    scope_fingerprint=run_scope_fingerprint(
                        run_id=run.id,
                        owner_user_id=user.id,
                        workspace_id=workspace.id,
                        project_id=None,
                        scope_type=SCOPE_WORKSPACE,
                    ),
                )
            )
        )
        await db.commit()
        await execute_run(db, run)
        assert selected == ["shared"]
        assert run.status == RUN_COMPLETED


@pytest.mark.asyncio
async def test_shared_graph_scheduler_failure_is_visible_in_fallback_summary(
    monkeypatch,
) -> None:
    """调度异常和受阻后继都由协调器提交 server fallback，不会静默消失。"""
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "source",
                    "order": 0,
                    "summary": "读取来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                }
            ],
            "statement_message_ids": [],
            "retrieval_requests": [
                {
                    "id": "q1",
                    "query": "甲醛来源",
                    "requirement_ids": ["source"],
                }
            ],
            "structured_requests": [],
        }
    )

    async def _fail_node(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("节点执行失败")

    async def _not_cancelled():
        return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.shared_execution_graph.execute_graph_node",
        _fail_node,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "共享图失败审计")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "甲醛来源？")
        run.status = RUN_PROCESSING
        await db.flush()
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        await execute_shared_execution_graph_plan(
            db,
            run,
            ctx,
            plan,
            cancel_check=_not_cancelled,
        )
        summary = await run_fallback_summary(db, run.id)
        invocations = list(
            (
                await db.execute(
                    select(KnowledgeAgentModelInvocation).where(
                        KnowledgeAgentModelInvocation.run_id == run.id,
                        KnowledgeAgentModelInvocation.purpose == "shared_execution_graph",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert summary["has_fallback"] is True
    assert len(invocations) == 3
    assert all(item.provider == "server" and item.is_fallback for item in invocations)
    assert all("node_fingerprint" in (item.error or "") for item in invocations)


@pytest.mark.asyncio
async def test_shared_graph_observability_records_actual_models_and_one_shared_tool(
    monkeypatch,
) -> None:
    """等价消费者只产生一次工具事实，模型 provider/usage 由协调器落库。"""
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "first",
                    "order": 0,
                    "summary": "读取来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                },
                {
                    "id": "second",
                    "order": 1,
                    "summary": "再次读取来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [
                {
                    "id": "q1",
                    "query": "甲醛来源",
                    "requirement_ids": ["first"],
                },
                {
                    "id": "q2",
                    "query": "甲醛来源",
                    "requirement_ids": ["second"],
                },
            ],
            "structured_requests": [],
        }
    )
    search_calls = 0

    async def _search(*args, **kwargs):
        nonlocal search_calls
        del args, kwargs
        search_calls += 1
        return SimpleNamespace(
            items=[],
            embedding_meta=StageMeta(
                purpose="embedding",
                provider="test-provider",
                model="embedding-test",
                is_fallback=False,
                error=None,
                duration_ms=3,
                usage={"input_tokens": 2},
            ).__dict__,
            rerank_meta=None,
        )

    async def _read(*args, **kwargs):
        del args, kwargs
        return SimpleNamespace(items=[], denied_entry_ids=[], unavailable_entry_ids=[])

    async def _not_cancelled():
        return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.tools.search_confirmed_knowledge", _search
    )
    monkeypatch.setattr("app.services.knowledge_agent.tools.read_entries", _read)
    async with async_session_factory() as db:
        user = await create_user(db, "共享图实际审计")
        workspace = await create_workspace(db, user)
        _conversation, run = await _conversation_and_run(db, user, workspace, "甲醛来源？")
        run.status = RUN_PROCESSING
        await db.flush()
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        await execute_shared_execution_graph_plan(
            db,
            run,
            ctx,
            plan,
            cancel_check=_not_cancelled,
        )
        invocations = list(
            (
                await db.execute(
                    select(KnowledgeAgentModelInvocation).where(
                        KnowledgeAgentModelInvocation.run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )
        search_audits = list(
            (
                await db.execute(
                    select(KnowledgeAgentToolCall).where(
                        KnowledgeAgentToolCall.run_id == run.id,
                        KnowledgeAgentToolCall.tool_name == "search_confirmed_knowledge",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert search_calls == 1
    assert len(search_audits) == 1
    params_summary = json.loads(search_audits[0].params_summary or "{}")
    assert params_summary["consumer_count"] == 2
    assert params_summary["reused"] is True
    assert len(params_summary["node_fingerprint"]) == 64
    assert len(invocations) == 1
    assert invocations[0].provider == "test-provider"
    assert invocations[0].model == "embedding-test"
    assert json.loads(invocations[0].usage_json or "{}") == {"input_tokens": 2}


@pytest.mark.asyncio
async def test_entries_result_skips_basis_planning(monkeypatch) -> None:
    """结构化 Entry 结果不执行依据规划，也不写 planned_basis_strategy。"""
    async def _fake_entry_search(db, run, decision, ctx):
        run.status = RUN_COMPLETED
        run.current_step = None
        run.active_slot = None
        run.actual_result_mode = RESULT_MODE_ENTRIES
        run.entry_result_json = '{"schema_version":"v1","query":"x","status":"completed"}'
        await db.flush()

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.execute_structured_entry_search",
        _fake_entry_search,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "条目跳过规划")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="条目跳过规划测试",
        )
        db.add(conversation)
        await db.flush()
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"entries-basis-{run_id_counter()}",
                message="列出相关条目",
                result_mode=RESULT_MODE_ENTRIES,
            ),
        )
        # 预置可恢复决策与实际结果形态，让执行器跳过路由直接进入 entries 图
        run.context_decision = "new_topic"
        run.standalone_query = "列出相关条目"
        run.topic_label = "列出相关条目"
        run.history_message_ids_json = "[]"
        run.context_meta_json = "{}"
        run.actual_result_mode = RESULT_MODE_ENTRIES
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.planned_basis_strategy is None
        assert run.request_basis_mode == "knowledge_only"
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose == PURPOSE_BASIS_ROUTE,
                )
            )
        ).scalars().all()
        assert invocations == []


@pytest.mark.asyncio
async def test_basis_open_empty_search_partial_with_statement_basis(
    monkeypatch,
) -> None:
    """hybrid 空 Grove 结果：保留一般分析并按缺口标记 partial，依据真实可见。"""
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
            strategy="hybrid",
            needs_grove=True,
            requires_external_material=False,
            candidate_statement_ids=[
                item.message_id for item in allowed_statements
            ],
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

    def _open_answer_agent():
        async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
            assert kwargs.get("user_statements")
            assert kwargs.get("allow_model_knowledge") is True
            return (
                KnowledgeAnswerDraft(
                    lead="先给出一般分析。",
                    points=[
                        KnowledgeAnswerPointDraft(
                            text="预算分配一般需要先明确上限与优先级。",
                            evidence_handles=[],
                        )
                    ],
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

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _open_answer_agent(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "开放空搜索")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "无内容项目")
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="预算上限 30 万，怎么分配？",
        )
        run.request_basis_mode = "auto"
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "partial"
        assert any("知识库" in gap for gap in answer["gaps"])
        basis = json.loads(run.answer_basis_json)
        assert basis["grove"]["used"] is False
        assert basis["model_knowledge"]["used"] is True
        assert basis["user_statements"]["message_ids"]
        assert basis["external_material"]["status"] == "not_used"


@pytest.mark.asyncio
async def test_knowledge_only_empty_search_keeps_strict_insufficient() -> None:
    """knowledge_only 空结果：严格依据不足，依据记录不标记模型知识。"""
    async with async_session_factory() as db:
        user = await create_user(db, "仅知识空搜索")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空项目")
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="完全不存在的主题",
        )
        run.request_basis_mode = "knowledge_only"
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        assert "没有召回相关正式 Entry" in answer["insufficient_note"]
        basis = json.loads(run.answer_basis_json)
        assert basis["grove"]["used"] is False
        assert basis["grove"]["citation_count"] == 0
        assert basis["model_knowledge"]["used"] is False
        assert basis["user_statements"]["message_ids"] == []


@pytest.mark.asyncio
async def test_basis_model_first_answer_fallback_fails_run(monkeypatch) -> None:
    """model-first 回答模型不可用且无工具结果：Run failed，不伪装正常回答。"""
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
            strategy=BASIS_STRATEGY_MODEL_FIRST,
            needs_grove=False,
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

    def _fallback_open_agent():
        async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
            return (
                KnowledgeAnswerDraft(
                    answer="当前没有可用的文本模型，无法生成回答。",
                    insufficient=True,
                    insufficient_note="文本模型不可用",
                ),
                StageMeta(
                    purpose="answer",
                    provider="offline",
                    model=None,
                    is_fallback=True,
                    error="未配置文本模型密钥",
                    duration_ms=1,
                ),
            )

        return _fake

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _fallback_open_agent(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "开放失败")
        workspace = await create_workspace(db, user)
        conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            message="解释一个通用概念",
        )
        run.request_basis_mode = "auto"
        run.status = RUN_PROCESSING
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_FAILED
        answer = json.loads(run.answer_json)
        assert answer["status"] == "failed"
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is True
        basis = json.loads(run.answer_basis_json)
        assert basis["model_knowledge"]["used"] is False
@pytest.mark.asyncio
async def test_structured_query_plan_reused_for_idempotent_message(
    monkeypatch,
) -> None:
    """同 client_message_id 重试复用首次 Run 与计划，不再次调用规划模型。"""
    calls = 0

    async def _planner(db, workspace_id, **kwargs):
        nonlocal calls
        del db, workspace_id, kwargs
        calls += 1
        return (
            StructuredQueryPlanDraft.model_validate(
                {
                    "entry_set": {"main_types": ["knowledge"]},
                    "outputs": [{"kind": "count"}],
                }
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

    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner",
        _planner,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "计划幂等")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="计划幂等",
        )
        db.add(conversation)
        await db.flush()
        payload = KnowledgeRunSubmitRequest(
            client_message_id=f"structured-plan-{run_id_counter()}",
            message="知识有多少条",
            result_mode="entries",
        )
        _message, run = await submit_message(db, conversation, payload)
        first = await plan_and_persist_structured_query(
            db,
            run,
            objective="知识有多少条",
            scope_label="全部知识",
        )
        raw = run.structured_query_plan_json

        _retry_message, retry_run = await submit_message(db, conversation, payload)
        second = await plan_and_persist_structured_query(
            db,
            retry_run,
            objective="这段不同文本不得改变计划",
            scope_label="全部知识",
        )

        assert retry_run.id == run.id
        assert calls == 1
        assert second == first
        assert retry_run.structured_query_plan_json == raw
