"""结果形态路由测试：显式覆盖、auto 路由、失败回退与 runner 接入边界。"""

import uuid
from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import select

from app.agents.result_mode import ResultModeRouteDraft
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    CONTEXT_DECISION_CLARIFY,
    CONTEXT_DECISION_NEW_TOPIC,
    PURPOSE_RESULT_MODE_ROUTE,
    RESULT_MODE_ANSWER,
    RESULT_MODE_AUTO,
    RESULT_MODE_ENTRIES,
    RUN_COMPLETED,
    RUN_PROCESSING,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.result_mode import (
    ResultModeResolution,
    resolve_result_mode,
)
from app.services.knowledge_agent.runner import RunCancelled, execute_run
from app.services.knowledge_agent.runs import submit_message
from tests._knowledge_agent_fixtures import create_user, create_workspace


def _stage(purpose: str = PURPOSE_RESULT_MODE_ROUTE, *, fallback: bool = False) -> StageMeta:
    return StageMeta(
        purpose=purpose,
        provider="llm" if not fallback else "offline",
        model="fake-router" if not fallback else None,
        is_fallback=fallback,
        error=None if not fallback else "未配置文本模型密钥",
        duration_ms=1,
    )


async def _user_workspace(db):
    user = await create_user(db, f"路由{uuid.uuid4().hex[:6]}")
    workspace = await create_workspace(db, user)
    return user, workspace


async def _conversation_and_run(db, user, workspace, *, result_mode: str | None = None):
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="路由测试对话",
    )
    db.add(conversation)
    await db.flush()
    payload = KnowledgeRunSubmitRequest(
        client_message_id=f"route-{uuid.uuid4().hex[:8]}",
        message="帮我找出和血压有关的知识",
    )
    if result_mode is not None:
        payload = KnowledgeRunSubmitRequest(
            client_message_id=payload.client_message_id,
            message=payload.message,
            result_mode=result_mode,
        )
    user_message, run = await submit_message(db, conversation, payload)
    del user_message
    return conversation, run


def _decision(decision: str = CONTEXT_DECISION_NEW_TOPIC) -> ContextDecisionResult:
    return ContextDecisionResult(
        decision=decision,
        standalone_query="帮我找出和血压有关的知识",
        topic_label="血压知识查找",
        clarify_question=None if decision != CONTEXT_DECISION_CLARIFY else "请补充主题",
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


async def _decide_fixed(decision: ContextDecisionResult):
    async def _decide(db, **kwargs):
        return decision

    return _decide


@pytest.mark.asyncio
async def test_resolve_explicit_modes_skip_router(monkeypatch) -> None:
    """显式 answer/entries 跳过路由模型，不产生阶段元数据。"""

    async def _fail_router(db, workspace_id, **kwargs):
        raise AssertionError("显式形态不应调用路由")

    monkeypatch.setattr(
        "app.services.knowledge_agent.result_mode.run_result_mode_router",
        _fail_router,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        answer = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_ANSWER,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert answer.mode == RESULT_MODE_ANSWER
        assert answer.meta is None
        entries = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_ENTRIES,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert entries.mode == RESULT_MODE_ENTRIES
        assert entries.meta is None
        del user


@pytest.mark.asyncio
async def test_resolve_auto_returns_entries_and_answer(monkeypatch) -> None:
    """auto 路由：模型返回 entries/answer 时直接采用，阶段元数据非 fallback。"""

    async def _router_entries(db, workspace_id, **kwargs):
        return ResultModeRouteDraft(mode="entries", reason="明确列出知识"), _stage()

    async def _router_answer(db, workspace_id, **kwargs):
        return ResultModeRouteDraft(mode="answer", reason="需要综合解释"), _stage()

    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        monkeypatch.setattr(
            "app.services.knowledge_agent.result_mode.run_result_mode_router",
            _router_entries,
        )
        entries = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="列出血压知识",
            scope_label="全部知识",
            topic_summary="血压",
        )
        assert entries.mode == RESULT_MODE_ENTRIES
        assert entries.meta is not None
        assert entries.meta.is_fallback is False
        assert entries.meta.purpose == PURPOSE_RESULT_MODE_ROUTE

        monkeypatch.setattr(
            "app.services.knowledge_agent.result_mode.run_result_mode_router",
            _router_answer,
        )
        answer = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="这些血压记录说明了什么",
            scope_label="全部知识",
            topic_summary="血压",
        )
        assert answer.mode == RESULT_MODE_ANSWER
        assert answer.meta is not None
        assert answer.meta.is_fallback is False
        del user


@pytest.mark.asyncio
async def test_resolve_router_disabled_fallback(monkeypatch) -> None:
    """路由禁用：显式回退 answer 并记录 server fallback。"""
    settings = SimpleNamespace(knowledge_agent_result_mode_router_enabled=False)
    monkeypatch.setattr(
        "app.services.knowledge_agent.result_mode.get_settings",
        lambda: settings,
    )

    async def _fail_router(db, workspace_id, **kwargs):
        raise AssertionError("禁用时不应调用路由")

    monkeypatch.setattr(
        "app.services.knowledge_agent.result_mode.run_result_mode_router",
        _fail_router,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        result = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert result.mode == RESULT_MODE_ANSWER
        assert result.fallback_reason == "router_disabled"
        assert result.meta is not None
        assert result.meta.is_fallback is True
        assert result.meta.provider == "server"
        del user


@pytest.mark.asyncio
async def test_resolve_router_exception_fallback(monkeypatch) -> None:
    """路由调用异常：回退 answer 且记录 provider/model/error。"""

    async def _explode(db, workspace_id, **kwargs):
        raise TimeoutError("路由超时")

    monkeypatch.setattr(
        "app.services.knowledge_agent.result_mode.run_result_mode_router",
        _explode,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        result = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert result.mode == RESULT_MODE_ANSWER
        assert result.fallback_reason == "router_error"
        assert result.meta is not None
        assert result.meta.is_fallback is True
        assert "路由超时" in (result.meta.error or "")
        del user


@pytest.mark.asyncio
async def test_resolve_router_invalid_output_fallback(monkeypatch) -> None:
    """路由非法输出（None 或越界模式）：回退 answer 并记录。"""

    async def _none_output(db, workspace_id, **kwargs):
        return None, _stage()

    async def _invalid_mode(db, workspace_id, **kwargs):
        return SimpleNamespace(mode="list", reason="x"), _stage()

    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        monkeypatch.setattr(
            "app.services.knowledge_agent.result_mode.run_result_mode_router",
            _none_output,
        )
        none_result = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert none_result.mode == RESULT_MODE_ANSWER
        assert none_result.fallback_reason == "路由结果非法"

        monkeypatch.setattr(
            "app.services.knowledge_agent.result_mode.run_result_mode_router",
            _invalid_mode,
        )
        invalid_result = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert invalid_result.mode == RESULT_MODE_ANSWER
        del user


@pytest.mark.asyncio
async def test_resolve_offline_model_fallback(monkeypatch) -> None:
    """未配置文本模型：路由离线回退 answer，provider=offline。"""

    async def _test_model(db, workspace_id):
        return TestModel()

    monkeypatch.setattr(
        "app.agents.result_mode.get_text_model",
        _test_model,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        result = await resolve_result_mode(
            db,
            workspace_id=workspace.id,
            request_mode=RESULT_MODE_AUTO,
            objective="问题",
            scope_label="全部知识",
            topic_summary=None,
        )
        assert result.mode == RESULT_MODE_ANSWER
        assert result.meta is not None
        assert result.meta.provider == "offline"
        assert result.meta.is_fallback is True
        del user


@pytest.mark.asyncio
async def test_runner_clarify_ends_before_result_route(monkeypatch) -> None:
    """clarify 决策直接结束，不调用结果形态路由。"""

    async def _decide(db, **kwargs):
        return _decision(CONTEXT_DECISION_CLARIFY)

    async def _fail_route(db, **kwargs):
        raise AssertionError("clarify 不应进入结果形态路由")

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _fail_route,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        _conversation, run = await _conversation_and_run(db, user, workspace)
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        assert run.status == RUN_COMPLETED
        assert run.actual_result_mode is None
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant is not None
        assert assistant.content == "请补充主题"


@pytest.mark.asyncio
async def test_runner_explicit_entries_skips_router_and_answer_route(monkeypatch) -> None:
    """显式 entries：跳过结果/回答路由，进入查找图，actual answer mode 为空。"""
    entered: list[str] = []

    async def _decide(db, **kwargs):
        return _decision()

    async def _route(db, **kwargs):
        entered.append("route")
        # 显式 entries：应用层直接采用，不产生模型调用元数据
        return ResultModeResolution(mode=RESULT_MODE_ENTRIES)

    async def _fail_answer_route(db, **kwargs):
        raise AssertionError("entries 不应调用回答模式路由")

    async def _search(db, run, decision, ctx):
        entered.append("search")
        run.actual_result_mode = RESULT_MODE_ENTRIES

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _route,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _fail_answer_route,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.execute_structured_entry_search",
        _search,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        _conversation, run = await _conversation_and_run(
            db,
            user,
            workspace,
            result_mode=RESULT_MODE_ENTRIES,
        )
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        assert entered == ["route", "search"]
        assert run.actual_result_mode == RESULT_MODE_ENTRIES
        # 请求回答模式仍可审计，实际回答模式为空
        assert run.request_answer_mode == RESULT_MODE_AUTO
        assert run.actual_answer_mode is None
        assert run.answer_json is None
        # 显式 entries 不伪造结果形态路由模型调用
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalars().all()
        assert not any(
            item.purpose == PURPOSE_RESULT_MODE_ROUTE for item in invocations
        )


@pytest.mark.asyncio
async def test_runner_auto_entries_records_route_invocation(monkeypatch) -> None:
    """auto 路由到 entries：记录 result_mode_route 模型调用，跳过回答模式。"""
    entered: list[str] = []

    async def _decide(db, **kwargs):
        return _decision()

    async def _route(db, **kwargs):
        return ResultModeResolution(
            mode=RESULT_MODE_ENTRIES,
            meta=StageMeta(
                purpose=PURPOSE_RESULT_MODE_ROUTE,
                provider="llm",
                model="fake-router",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    async def _fail_answer_route(db, **kwargs):
        raise AssertionError("entries 不应调用回答模式路由")

    async def _search(db, run, decision, ctx):
        entered.append("search")

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _route,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _fail_answer_route,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.execute_structured_entry_search",
        _search,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        _conversation, run = await _conversation_and_run(db, user, workspace)
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        assert entered == ["search"]
        assert run.actual_result_mode == RESULT_MODE_ENTRIES
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalars().all()
        assert any(
            item.purpose == PURPOSE_RESULT_MODE_ROUTE
            and item.model == "fake-router"
            and item.is_fallback is False
            for item in invocations
        )


@pytest.mark.asyncio
async def test_runner_auto_answer_fallback_records_route_fallback(monkeypatch) -> None:
    """auto 路由失败回退 answer：记录 fallback 且回答路径正常继续。"""
    routed: list[str] = []

    async def _decide(db, **kwargs):
        return _decision()

    async def _route(db, **kwargs):
        return ResultModeResolution(
            mode=RESULT_MODE_ANSWER,
            meta=StageMeta(
                purpose=PURPOSE_RESULT_MODE_ROUTE,
                provider="server",
                model=None,
                is_fallback=True,
                error="路由结果非法",
                duration_ms=0,
            ),
        )

    async def _answer_route(db, **kwargs):
        routed.append("answer_mode")
        from app.services.knowledge_agent.investigation import AnswerModeResolution

        return AnswerModeResolution(mode="quick")

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _route,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _answer_route,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        _conversation, run = await _conversation_and_run(db, user, workspace)
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        await db.commit()
        # 没有知识数据：回答路径走到无结果分支，正常完成知识不足
        await execute_run(db, run)
        await db.commit()
        assert run.actual_result_mode == RESULT_MODE_ANSWER
        assert run.actual_answer_mode == "quick"
        assert run.status == RUN_COMPLETED
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalars().all()
        assert any(
            item.purpose == PURPOSE_RESULT_MODE_ROUTE and item.is_fallback is True
            for item in invocations
        )


@pytest.mark.asyncio
async def test_runner_cancel_before_result_route_aborts(monkeypatch) -> None:
    """结果形态路由前命中取消：抛 RunCancelled，不进入任何查找/回答分支。"""
    entered: list[str] = []

    async def _decide(db, **kwargs):
        return _decision()

    async def _route(db, **kwargs):
        entered.append("route")
        return ResultModeResolution(mode=RESULT_MODE_ANSWER)

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _route,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        _conversation, run = await _conversation_and_run(db, user, workspace)
        run.status = RUN_PROCESSING
        run.current_step = "claim"
        run.cancel_requested = True
        await db.commit()
        with pytest.raises(RunCancelled):
            await execute_run(db, run)
        # 取消发生在上下文决策之后、结果路由之前的安全边界
        assert entered == []
        assert run.actual_result_mode is None
