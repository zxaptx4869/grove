"""知识 Agent 调查路由与控制器测试：显式覆盖、auto 路由、安全降级与输出校验。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai.models.test import TestModel

from app.agents.investigation import (
    AnswerModeRouteDraft,
    InvestigationControllerDraft,
    _format_controller_context,
    run_answer_mode_router,
    run_investigation_controller,
)
from app.db.session import async_session_factory
from app.models.knowledge_agent import (
    ANSWER_MODE_AUTO,
    ANSWER_MODE_INVESTIGATE,
    ANSWER_MODE_QUICK,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
    INVESTIGATION_ACTION_SEARCH,
    PURPOSE_ANSWER_MODE_ROUTE,
    PURPOSE_INVESTIGATION_CONTROLLER,
)
from app.services.knowledge_agent.investigation import (
    controller_plan_defaults,
    resolve_answer_mode,
    validate_controller_output,
)
from app.services.knowledge_agent.observability import StageMeta
from tests._knowledge_agent_fixtures import create_user, create_workspace


def _router_meta(*, is_fallback: bool = False, error: str | None = None) -> StageMeta:
    return StageMeta(
        purpose=PURPOSE_ANSWER_MODE_ROUTE,
        provider="llm" if not is_fallback else "offline",
        model=None if is_fallback else "fake-router",
        is_fallback=is_fallback,
        error=error,
        duration_ms=1,
    )


def _fake_router(draft: AnswerModeRouteDraft, *, fallback: bool = False):
    async def _fake(db, workspace_id, *, objective, topic_summary):
        return draft, _router_meta(is_fallback=fallback, error="模型不可用" if fallback else None)

    return _fake


@pytest.mark.asyncio
async def test_explicit_quick_skips_router(monkeypatch) -> None:
    """显式 quick：不调用路由模型，直接返回 quick。"""

    async def _should_not_call(*args, **kwargs):
        raise AssertionError("显式 quick 不应调用路由模型")

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation.run_answer_mode_router",
        _should_not_call,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "显式快速")
        workspace = await create_workspace(db, user)
        result = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_QUICK,
            objective="闭水试验持续多久？",
            topic_summary=None,
        )
        assert result.mode == ANSWER_MODE_QUICK
        assert result.meta is None
        assert result.fallback_reason is None


@pytest.mark.asyncio
async def test_explicit_investigate_skips_router(monkeypatch) -> None:
    """显式 investigate：不调用路由模型，直接进入调查。"""

    async def _should_not_call(*args, **kwargs):
        raise AssertionError("显式 investigate 不应调用路由模型")

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation.run_answer_mode_router",
        _should_not_call,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "显式调查")
        workspace = await create_workspace(db, user)
        result = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_INVESTIGATE,
            objective="对比两个方案的验收差异",
            topic_summary="验收规则",
        )
        assert result.mode == ANSWER_MODE_INVESTIGATE
        assert result.meta is None


@pytest.mark.asyncio
async def test_auto_router_quick_and_investigate(monkeypatch) -> None:
    """auto 路由成功：按路由结果选择 quick 或 investigate 并记录元数据。"""
    async with async_session_factory() as db:
        user = await create_user(db, "自动路由")
        workspace = await create_workspace(db, user)
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation.run_answer_mode_router",
            _fake_router(AnswerModeRouteDraft(mode="quick", reason="简单问题")),
        )
        quick = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_AUTO,
            objective="闭水试验持续多久？",
            topic_summary=None,
        )
        assert quick.mode == ANSWER_MODE_QUICK
        assert quick.meta is not None
        assert quick.meta.is_fallback is False
        assert quick.meta.model == "fake-router"

        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation.run_answer_mode_router",
            _fake_router(AnswerModeRouteDraft(mode="investigate", reason="需核对冲突")),
        )
        investigate = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_AUTO,
            objective="对比两个方案的验收差异",
            topic_summary="验收规则",
        )
        assert investigate.mode == ANSWER_MODE_INVESTIGATE
        assert investigate.meta is not None
        assert investigate.meta.is_fallback is False


@pytest.mark.asyncio
async def test_auto_router_failure_falls_back_to_quick(monkeypatch) -> None:
    """auto 路由失败/异常：固定选择 quick 并记录 fallback 原因。"""
    async with async_session_factory() as db:
        user = await create_user(db, "路由降级")
        workspace = await create_workspace(db, user)

        async def _boom(*args, **kwargs):
            raise RuntimeError("路由进程崩溃")

        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation.run_answer_mode_router",
            _boom,
        )
        result = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_AUTO,
            objective="复杂问题",
            topic_summary=None,
        )
        assert result.mode == ANSWER_MODE_QUICK
        assert result.fallback_reason == "router_error"
        assert result.meta is not None
        assert result.meta.is_fallback is True


@pytest.mark.asyncio
async def test_auto_router_invalid_structure_falls_back_to_quick(monkeypatch) -> None:
    """auto 路由返回非法结构（草稿为空）：降级 quick 且不伪装成正常路由。"""
    async with async_session_factory() as db:
        user = await create_user(db, "非法路由")
        workspace = await create_workspace(db, user)
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation.run_answer_mode_router",
            _fake_router(None, fallback=True),
        )
        result = await resolve_answer_mode(
            db,
            workspace_id=workspace.id,
            request_mode=ANSWER_MODE_AUTO,
            objective="复杂问题",
            topic_summary=None,
        )
        assert result.mode == ANSWER_MODE_QUICK
        assert result.meta is not None
        assert result.meta.is_fallback is True
        assert result.fallback_reason == "模型不可用"


@pytest.mark.asyncio
async def test_router_offline_model_records_fallback_meta(monkeypatch) -> None:
    """未配置文本模型：路由记录 provider=offline 与 error，不伪装成正常。"""
    async def _fake_offline_model(db, workspace_id):
        return TestModel()

    monkeypatch.setattr(
        "app.agents.investigation.get_text_model",
        _fake_offline_model,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "离线路由")
        workspace = await create_workspace(db, user)
        draft, meta = await run_answer_mode_router(
            db,
            workspace.id,
            objective="问题",
            topic_summary=None,
        )
        assert meta.purpose == PURPOSE_ANSWER_MODE_ROUTE
        assert meta.provider == "offline"
        assert meta.is_fallback is True
        assert meta.error == "未配置文本模型密钥"
        assert draft.mode == ANSWER_MODE_QUICK


def test_controller_draft_rejects_out_of_schema_fields() -> None:
    """越权字段（范围/对象/预算/工具名）不属于 schema，pydantic 直接丢弃。"""
    draft = InvestigationControllerDraft(
        action="search",
        queries=["闭水试验放水时机"],
        workspace_id=999,
        budget=999,
        tool_name="delete_entry",
    )
    assert draft.action == "search"
    assert not hasattr(draft, "workspace_id")
    assert not hasattr(draft, "budget")
    assert not hasattr(draft, "tool_name")
    with pytest.raises(ValidationError):
        InvestigationControllerDraft.model_validate({"action": "hack"})


def test_controller_three_actions_validated() -> None:
    """控制器三种动作均通过校验，动作保持稳定。"""
    defaults = controller_plan_defaults()
    search = validate_controller_output(
        InvestigationControllerDraft(
            action="search",
            queries=["  闭水试验  放水时机  ", "  "],
            coverage=["已覆盖时长"],
            gaps=["放水时机未覆盖"],
        ),
        **defaults,
    )
    assert search.action == INVESTIGATION_ACTION_SEARCH
    assert search.queries == ["闭水试验 放水时机"]
    assert search.invalid is False

    answer = validate_controller_output(
        InvestigationControllerDraft(action="answer", reason="证据足够"),
        **defaults,
    )
    assert answer.action == INVESTIGATION_ACTION_ANSWER

    insufficient = validate_controller_output(
        InvestigationControllerDraft(action="insufficient"),
        **defaults,
    )
    assert insufficient.action == INVESTIGATION_ACTION_INSUFFICIENT


def test_controller_queries_capped_deduplicated_and_summaries_truncated() -> None:
    """查询最多 3 条、去除空白重复；摘要条目与 reason 确定性截断。"""
    defaults = controller_plan_defaults()
    plan = validate_controller_output(
        InvestigationControllerDraft(
            action="search",
            queries=[
                "闭水试验",
                "  闭水试验  ",
                "放水时机",
                "验收标准",
                "第五个查询",
            ],
            coverage=["覆盖项 " + "长" * 500 for _ in range(30)],
            gaps=["缺口项" for _ in range(30)],
            conflicts=[],
            reason="理由" + "长" * 2000,
        ),
        **defaults,
    )
    assert plan.queries == ["闭水试验", "放水时机", "验收标准"]
    assert len(plan.coverage) == defaults["summary_items"]
    assert all(len(item) <= defaults["summary_item_chars"] for item in plan.coverage)
    assert len(plan.gaps) == defaults["summary_items"]
    assert len(plan.reason) <= defaults["reason_chars"]


def test_controller_invalid_output_plan() -> None:
    """控制器无输出/动作非法：应用层返回安全停止计划，不执行任何查询。"""
    defaults = controller_plan_defaults()
    plan = validate_controller_output(None, **defaults)
    assert plan.invalid is True
    assert plan.action == INVESTIGATION_ACTION_INSUFFICIENT
    assert plan.queries == []
    assert plan.rejection_note is not None


def test_controller_input_builder_is_compact() -> None:
    """控制器输入只含独立问题、范围、短摘要与预算，不携带完整 Attachment/历史。"""
    context = _format_controller_context(
        objective="对比验收差异",
        scope_label="项目：施工",
        working_set_summary="闭水试验；验收规则",
        executed_queries=["闭水试验时长", "放水时机"],
        ledger_summary="Entry 2 条；Evidence 3 条；缺口：放水时机",
        remaining_budget={"rounds": 2, "queries": 4, "entries": 22, "evidence": 9},
    )
    assert "对比验收差异" in context
    assert "项目：施工" in context
    assert "闭水试验；验收规则" in context
    assert "放水时机" in context
    assert "rounds=2" in context
    assert "queries=4" in context
    assert "entries=22" in context
    assert "evidence=9" in context
    assert "Attachment" not in context
    assert "history" not in context.lower()


class _FakeAgent:
    """替换 pydantic_ai Agent 的替身：捕获配置并返回固定草稿。"""

    def __init__(self, model, *, output_type, system_prompt, retries, model_settings):
        self.output_type = output_type
        self.model_settings = model_settings
        self.draft = _CURRENT_FAKE_DRAFT[0]
        _FAKE_MODEL_SETTINGS[0] = model_settings

    async def run(self, context):
        return SimpleNamespace(output=self.draft)


_CURRENT_FAKE_DRAFT: list = [None]
_FAKE_MODEL_SETTINGS: list = [None]


async def _fake_configured_model(db, workspace_id):
    return SimpleNamespace(model_name="fake-controller-model")


@pytest.mark.asyncio
async def test_controller_real_path_records_observability(monkeypatch) -> None:
    """控制器真实模型路径：三种动作草稿透传并记录 provider/model/耗时。"""
    monkeypatch.setattr(
        "app.agents.investigation.get_text_model",
        _fake_configured_model,
    )
    monkeypatch.setattr("app.agents.investigation.Agent", _FakeAgent)
    async with async_session_factory() as db:
        user = await create_user(db, "控制器真实路径")
        workspace = await create_workspace(db, user)
        for action, queries in [
            (INVESTIGATION_ACTION_SEARCH, ["新查询一"]),
            (INVESTIGATION_ACTION_ANSWER, []),
            (INVESTIGATION_ACTION_INSUFFICIENT, []),
        ]:
            _CURRENT_FAKE_DRAFT[0] = InvestigationControllerDraft(
                action=action, queries=queries
            )
            draft, meta = await run_investigation_controller(
                db,
                workspace.id,
                objective="问题",
                scope_label="全部知识",
                working_set_summary="",
                executed_queries=[],
                ledger_summary="",
                remaining_budget={"rounds": 3},
            )
            assert draft.action == action
            assert meta.purpose == PURPOSE_INVESTIGATION_CONTROLLER
            assert meta.provider == "llm"
            assert meta.model == "fake-controller-model"
            assert meta.is_fallback is False
            assert meta.duration_ms >= 0
            # 超时配置透传到模型设置
            assert _FAKE_MODEL_SETTINGS[0]["timeout"] > 0


@pytest.mark.asyncio
async def test_controller_offline_model_stops_with_insufficient(monkeypatch) -> None:
    """控制器模型不可用：停止动作 insufficient 并记录 fallback，不编造新查询。"""
    async def _fake_offline_model(db, workspace_id):
        return TestModel()

    monkeypatch.setattr(
        "app.agents.investigation.get_text_model",
        _fake_offline_model,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "离线控制器")
        workspace = await create_workspace(db, user)
        draft, meta = await run_investigation_controller(
            db,
            workspace.id,
            objective="问题",
            scope_label="全部知识",
            working_set_summary="",
            executed_queries=[],
            ledger_summary="",
            remaining_budget={"rounds": 3},
        )
        assert draft.action == INVESTIGATION_ACTION_INSUFFICIENT
        assert meta.is_fallback is True
        assert meta.provider == "offline"
        assert meta.error == "未配置文本模型密钥"
