"""知识 Agent 固定执行图与分阶段可观测性测试。"""

import json
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from app.agents.knowledge_agent import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
)
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    RUN_COMPLETED,
    RUN_PARTIAL,
    RUN_PROCESSING,
    SCOPE_WORKSPACE,
    STEP_SEARCH,
    TOOL_EMPTY,
    TOOL_ERROR,
    TOOL_PARTIAL,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.observability import StageMeta, run_fallback_summary
from app.services.knowledge_agent.runner import RunCancelled, execute_run
from app.services.knowledge_agent.runs import (
    read_run_cancel_state,
    submit_message,
    update_run_step,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    search_confirmed_knowledge,
)
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
