"""统一对话循环实验的无模型边界与停止条件测试。"""

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from math import ceil
from pathlib import Path

import pytest
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from pydantic_core import to_jsonable_python

from app.services.secret_store import MemorySecretStore
from evals.dialogue_loop import cli as cli_module
from evals.dialogue_loop import loop as loop_module
from evals.dialogue_loop.__main__ import _write
from evals.dialogue_loop.cli import (
    InfrastructureFailure,
    _conclusion,
    _input_estimation_by_scope,
    _resource_by_arm,
    parser,
)
from evals.dialogue_loop.core import (
    BATCH_EMBEDDING_REQUESTS,
    BATCH_TEXT_REQUESTS,
    HISTORY_ANSWER_CHARS_PER_TURN,
    HISTORY_INPUT_TOKENS_TARGET,
    INPUT_ESTIMATE_SOFT_LIMIT,
    INPUT_ESTIMATE_VERSION,
    MODEL_INPUT_TOKENS_LIMIT,
    PER_TURN_EMBEDDING_REQUESTS,
    PER_TURN_ENTRY_READS,
    PER_TURN_EVIDENCE_READS,
    PER_TURN_SECONDS,
    PER_TURN_TEXT_REQUESTS,
    PER_TURN_TOOL_CALLS,
    VARIANT_SCENARIOS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
    StopState,
)
from evals.dialogue_loop.credentials import (
    DEMO_PASSWORD_PROVIDER,
    delete_demo_password,
    load_demo_password,
    password_for_run,
    save_demo_password,
)
from evals.dialogue_loop.execution import _rehearsal_scenario, _v2_control_preflight
from evals.dialogue_loop.instrumentation import (
    FINALIZE_INSTRUCTION,
    BudgetedModel,
    Instrumentation,
)
from evals.dialogue_loop.isolation import assert_isolated, backup_database
from evals.dialogue_loop.loop import (
    SYSTEM_PROMPT,
    LoopDeps,
    LoopState,
    _candidate_revision_requested,
    _count_params,
    _create_finalize_continuation,
    _current_material_history,
    _entry_set,
    _group_params,
    _mark_budget_stop,
    _model_payload,
    _stop_from_events,
    _validate_finalize_continuation,
    _verified_failure_output,
    build_agent,
    build_compact_history,
    build_finalizer_agent,
    directory_reference_item,
    list_directory_position_node_id,
    list_position_entry_id,
    output_errors,
    render_answer,
    render_directory_not_found,
    run_turn,
)
from evals.dialogue_loop.report import _visible_answer, evaluate, evaluation_plan, sanitize


def _state() -> LoopState:
    ledger = BudgetLedger()
    instrumentation = Instrumentation(ledger)
    state = LoopState(
        workspace_id=1,
        user_id=2,
        conversation_id=3,
        ledger=ledger,
        instrumentation=instrumentation,
    )
    state.begin_turn(4, "测试")
    return state


class BrokenSecretStore(MemorySecretStore):
    def get(self, key: str) -> str | None:
        raise RuntimeError("不得进入输出的敏感异常详情")


def test_demo_password_uses_workspace_keychain_without_prompt() -> None:
    store = MemorySecretStore()
    save_demo_password(79, "demo-secret", store=store)

    password, from_keychain, error = password_for_run(
        79,
        store=store,
        prompt=lambda _message: pytest.fail("已有钥匙串密码时不应询问"),
    )

    assert password == "demo-secret"
    assert from_keychain is True
    assert error is None
    assert store.get(f"79:{DEMO_PASSWORD_PROVIDER}") == "demo-secret"


def test_demo_password_missing_falls_back_to_hidden_prompt() -> None:
    password, from_keychain, error = password_for_run(
        79,
        store=MemorySecretStore(),
        prompt=lambda message: "prompt-secret" if "不写入报告" in message else "",
    )

    assert password == "prompt-secret"
    assert from_keychain is False
    assert error is None


def test_demo_password_keychain_error_is_safe_and_falls_back() -> None:
    password, from_keychain, error = password_for_run(
        79,
        store=BrokenSecretStore(),
        prompt=lambda _message: "prompt-secret",
    )

    assert password == "prompt-secret"
    assert from_keychain is False
    assert error == "系统钥匙串读取失败（RuntimeError）"
    assert "敏感异常详情" not in error


def test_demo_password_can_be_deleted_and_empty_value_is_rejected() -> None:
    store = MemorySecretStore()
    save_demo_password(79, "demo-secret", store=store)
    delete_demo_password(79, store=store)
    password, error = load_demo_password(79, store=store)

    assert password is None
    assert error is None
    with pytest.raises(ValueError, match="不能为空"):
        save_demo_password(79, "", store=store)


def test_password_management_modes_are_mutually_exclusive() -> None:
    args = parser().parse_args(["--save-demo-password"])
    assert args.save_demo_password is True
    with pytest.raises(SystemExit):
        parser().parse_args(["--save-demo-password", "--preflight"])


def test_save_mode_does_not_write_keychain_before_isolated_authentication(monkeypatch) -> None:
    identity = {"user_id": 79, "workspace_id": 79, "role": "owner"}
    monkeypatch.setattr(cli_module, "_source_database", lambda _backend: Path("original.db"))
    monkeypatch.setattr(cli_module, "identity_snapshot", lambda _path: identity)
    monkeypatch.setattr(cli_module, "backup_database", lambda _source, _target: None)
    monkeypatch.setattr(cli_module.getpass, "getpass", lambda _message: "demo-secret")
    monkeypatch.setattr(
        cli_module,
        "_child",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            InfrastructureFailure("ValueError: demo 账号或密码错误", 1)
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "save_demo_password",
        lambda *_args, **_kwargs: pytest.fail("认证失败时不得写入钥匙串"),
    )

    with pytest.raises(InfrastructureFailure, match="demo 账号或密码错误"):
        cli_module.run_parent(parser().parse_args(["--save-demo-password"]))


@pytest.mark.asyncio
async def test_text_and_embedding_budget_reserve_before_dispatch() -> None:
    ledger = BudgetLedger()
    ledger.start_turn()
    for _ in range(PER_TURN_TEXT_REQUESTS):
        await ledger.reserve_text()
    with pytest.raises(BudgetExceeded, match="本轮文本"):
        await ledger.reserve_text()

    ledger.start_turn()
    for _ in range(PER_TURN_EMBEDDING_REQUESTS):
        await ledger.reserve_embedding()
    with pytest.raises(BudgetExceeded, match="本轮向量"):
        await ledger.reserve_embedding()
    assert ledger.batch_text_requests <= BATCH_TEXT_REQUESTS
    assert ledger.batch_embedding_requests <= BATCH_EMBEDDING_REQUESTS


@pytest.mark.asyncio
async def test_parallel_reservations_cannot_exceed_turn_budget() -> None:
    import asyncio

    ledger = BudgetLedger()
    ledger.start_turn()
    results = await asyncio.gather(
        *(ledger.reserve_text() for _ in range(PER_TURN_TEXT_REQUESTS + 3)),
        return_exceptions=True,
    )
    assert sum(item is None for item in results) == PER_TURN_TEXT_REQUESTS
    assert sum(isinstance(item, BudgetExceeded) for item in results) == 3


def test_explicit_project_filter_can_be_replaced_and_cleared() -> None:
    project = _entry_set("project", "房子装修", None, [])
    all_projects = _entry_set("all", None, None, [])
    all_projects_from_empty = _entry_set("all", "  ", None, [])
    assert project["project_name"] == "房子装修"
    assert all_projects["project_name"] is None
    assert all_projects_from_empty["project_name"] is None
    with pytest.raises(ModelRetry):
        _entry_set("project", None, None, [])
    with pytest.raises(ModelRetry):
        _entry_set("all", "房子装修", None, [])


def test_main_types_default_to_all_and_explicit_filter_is_preserved() -> None:
    assert _entry_set("all", None, None, None)["main_types"] == []
    assert _entry_set("all", None, None, ["method"])["main_types"] == ["method"]


def test_statistic_adapters_build_unambiguous_shared_tool_params() -> None:
    count = _count_params("all", None, None)
    assert count["operation"] == "count"
    assert count["group_by"] is None
    assert count["entry_set"]["main_types"] == []

    grouped = _group_params("project", "房子装修", "project", ["knowledge"])
    assert grouped["operation"] == "group_count"
    assert grouped["group_by"] == "project"
    assert grouped["entry_set"]["main_types"] == ["knowledge"]


def test_project_validation_names_the_invalid_field() -> None:
    with pytest.raises(ModelRetry, match="字段 project_name"):
        _entry_set("project", None, None, None)


@pytest.mark.parametrize(
    "message",
    [
        "帮我补充一下这条知识",
        "帮我完善一下",
        "按你的分析改写一版",
        "给我一版更新后的内容",
        "把修改后的内容输出给我，我自己更新",
        "帮我整理成可以更新的版本",
        "帮我更新一下，把内容输出给我，我去更新",
    ],
)
def test_candidate_revision_wording_is_not_treated_as_direct_write(message: str) -> None:
    assert _candidate_revision_requested(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "直接帮我更新知识库",
        "保存到这条记录",
        "把原记录改掉",
        "覆盖原来的内容",
        "写入 Entry",
        "替我保存修改",
        "把修改后的内容保存到原记录并覆盖旧内容",
    ],
)
def test_direct_write_wording_is_not_treated_as_candidate_revision(message: str) -> None:
    assert _candidate_revision_requested(message) is False


def test_list_position_uses_actual_order_and_rejects_forgery() -> None:
    state = _state()
    handle = state.store_result(
        "list",
        {"items": [{"entry_id": 91}, {"entry_id": 17}, {"entry_id": 42}]},
        "completed",
        "complete",
    )
    assert list_position_entry_id(state, handle, 3) == 42
    with pytest.raises(ValueError):
        list_position_entry_id(state, "forged", 1)
    with pytest.raises(ValueError):
        list_position_entry_id(state, handle, 4)


def test_deterministic_fallback_isolated_to_current_turn_material() -> None:
    state = _state()
    historical = state.store_result("statistic", {"value": 99}, "completed", "complete")
    state.begin_turn(5, "当前查询")
    current = state.store_result("statistic", {"value": 4}, "completed", "complete")
    state.stop(
        StopState(
            status="partial_completed",
            reason_code="budget_boundary",
            reason="工具动作预算已耗尽",
            incomplete_steps=["未核验叶子节点的子节点"],
            can_continue=True,
        )
    )

    text, blocks = _verified_failure_output(state)

    handles = {block.get("handle") for block in blocks if block.get("kind") == "statistic"}
    assert current in handles
    assert historical not in handles
    assert any(block["kind"] == "insufficient" for block in blocks)
    assert "未核验叶子节点" in text


def test_deterministic_fallback_keeps_current_read_entry_content() -> None:
    state = _state()
    state.store_result(
        "entries",
        {
            "items": [
                {
                    "entry_id": 90,
                    "title": "墙面材料建议",
                    "content": "真实正文",
                    "project_name": "房子装修",
                }
            ]
        },
        "completed",
        "limited",
    )
    state.stop(
        StopState(
            status="partial_completed",
            reason_code="budget_boundary",
            reason="文本预算已耗尽",
            incomplete_steps=["未生成完整回答"],
            can_continue=True,
        )
    )

    text, blocks = _verified_failure_output(state)

    assert "真实正文" in text
    assert any(block["kind"] == "entry" for block in blocks)


def test_budget_stop_keeps_directory_continuation_without_fake_leaf_total() -> None:
    state = _state()
    _mark_budget_stop(
        state,
        BudgetExceeded("本轮工具动作预算已耗尽"),
        tool_name="list_project_directories",
        params={"project_id": 26, "parent_node_id": 12, "operation": "children"},
    )

    assert state.stop_state is not None
    assert state.stop_state.status == "partial_completed"
    assert state.stop_state.continuation is not None
    assert state.stop_state.continuation.pending_steps == [{"parent_node_id": 12}]
    assert state.stop_state.continuation.scope["project_id"] == 26

    state.begin_turn(6, "继续核验刚才没查完的目录")
    assert state.active_continuation is not None
    assert state.active_continuation.pending_steps == [{"parent_node_id": 12}]


def test_find_budget_stop_is_partial_and_never_an_empty_match() -> None:
    """定位未派发时保留部分完成原因，不能伪装成目录不存在。"""

    state = _state()
    _mark_budget_stop(
        state,
        BudgetExceeded("本轮工具动作预算已耗尽"),
        tool_name="list_project_directories",
        params={
            "project_name": "房子装修",
            "operation": "find",
            "name": "瓷砖地材",
        },
    )

    assert state.stop_state is not None
    assert state.stop_state.status == "partial_completed"
    assert state.stop_state.reason_code == "tool_action_budget"
    assert not state.current_handles


def test_tool_capability_stop_does_not_relabel_other_statistics() -> None:
    state = _state()
    events = [
        {
            "tool": "report_unsupported",
            "status": "unsupported",
            "reason_code": "tool_capability_missing",
            "error": "当前没有整树聚合能力",
            "turn_index": state.turn_index,
        }
    ]

    stop = _stop_from_events(state, events)

    assert stop is not None
    assert stop.status == "unsupported"
    assert stop.reason_code == "tool_capability_missing"
    assert "整树聚合" in stop.reason


def test_finalize_tool_shape_error_is_not_executed_and_not_a_system_failure() -> None:
    from evals.dialogue_loop.loop import _stop_from_failure

    state = _state()
    stop = _stop_from_failure(
        state,
        RuntimeError("Tool 'count_entries' exceeded max retries count of 0"),
        {"category": "unknown"},
    )

    assert stop.status == "not_executed"
    assert stop.reason_code == "invalid_tool_params"
    assert stop.can_continue is True


@pytest.mark.asyncio
async def test_invalid_query_params_retry_once_then_report_not_executed() -> None:
    """非法工具参数最多纠正一次，且未执行查询时不得标成部分完成。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(_messages, info):
        calls.append(info)
        if info.function_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_entries",
                        {
                            "project_scope": "all",
                            "project_name": "null",
                            "semantic_query": "测试主题",
                            "sort": {
                                "field": "created_at",
                                "direction": "sideways",
                            },
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "查询参数未通过校验。"}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    turn, _ = await run_turn(build_agent(model), state, "请查测试主题", [])

    assert turn["status"] == "not_executed"
    assert turn["completion"]["reason_code"] == "invalid_tool_params"
    assert turn["tool_calls"] == []
    assert sum(bool(info.function_tools) for info in calls) == 2
    assert len(calls) == 2


def test_invalid_tool_params_are_not_reported_as_access_denied() -> None:
    """没有确认材料时，模型参数错误属于未执行且不得伪装成权限问题。"""

    state = _state()
    stop = _stop_from_events(
        state,
        [
            {
                "tool": "list_project_directories",
                "status": "denied",
                "reason_code": "invalid_tool_params",
                "error": "工具参数非法：1 项",
            }
        ],
    )

    assert stop is not None
    assert stop.status == "not_executed"
    assert stop.reason_code == "invalid_tool_params"
    assert stop.can_continue is True


def test_complete_directory_not_found_has_deterministic_rendering() -> None:
    """完整空结果可在收尾预算不足时直接渲染，不依赖第二次模型请求。"""

    state = _state()
    payload = {
        "project": {"id": 26, "name": "房子装修"},
        "operation": "find",
        "query": {
            "name": "墙纸设计",
            "path": None,
            "requested_match": "exact",
            "applied_match": "exact",
        },
        "match_status": "not_found",
        "items": [],
        "total_count": 0,
        "returned_count": 0,
        "has_more": False,
    }
    state.store_result(
        "directories",
        payload,
        "empty",
        "complete",
        semantics=loop_module._result_semantics(
            "list_project_directories",
            {"operation": "find"},
            payload,
        ),
    )

    rendered = render_directory_not_found(state)

    assert rendered is not None
    assert rendered[0] == "房子装修 · 未找到名为「墙纸设计」的目录。"


def test_compact_history_keeps_order_and_protocol_without_large_body() -> None:
    state = _state()
    handle = state.store_result(
        "list",
        {
            "items": [
                {"entry_id": 91, "title": "甲", "project_name": "装修", "content": "正文" * 3000},
                {"entry_id": 17, "title": "乙", "project_name": "装修", "content": "原文" * 3000},
            ]
        },
        "completed",
        "complete",
    )
    state.remember_turn(
        "列出两条",
        "概括说明\n1. 甲\n2. 乙\n如需来源可以继续查询",
        [
            {
                "tool": "query_entries",
                "shared_tool": "query_entries",
                "result_handle": handle,
                "params": {"entry_set": _entry_set("all", None, None, None)},
                "status": "completed",
                "completeness": "complete",
                "error": None,
            }
        ],
        blocks=[
            {"kind": "text", "text": "概括说明"},
            {
                "kind": "entry",
                "entry_id": 91,
                "title": "甲",
                "content": "正文" * 3_000,
                "text": "正文" * 3_000,
            },
            {
                "kind": "evidence",
                "entry_id": 91,
                "source_id": 66,
                "text": "Evidence 原文" * 2_000,
            },
            {"kind": "text", "text": "如需来源可以继续查询"},
        ],
    )
    history = build_compact_history(state)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert history[0].parts[0].content == "列出两条"
    call = history[1].parts[0]
    returned = history[2].parts[0]
    assert isinstance(call, ToolCallPart)
    assert isinstance(returned, ToolReturnPart)
    assert call.tool_call_id == returned.tool_call_id
    assert [item["entry_id"] for item in returned.content["ordered_items"]] == [91, 17]
    assert "正文正文" not in str(returned.content)
    assert "Evidence 原文" not in str(history)
    assert "概括说明" in str(history)
    assert "如需来源可以继续查询" in str(history)
    assert list_position_entry_id(state, handle, 2) == 17


def test_current_material_is_bounded_but_full_body_stays_program_side() -> None:
    content = "甲" * 4_000
    payload = {
        "items": [
            {
                "entry_id": 1,
                "title": "标题",
                "content": content,
                "sources": [{"source_id": 2, "source_title": "来源", "quote": "原文" * 2_000}],
            }
        ]
    }
    model_payload = _model_payload("entries", payload)
    assert "实验材料已缩减" in model_payload["items"][0]["content"]
    assert "quote" not in model_payload["items"][0]["sources"][0]
    assert payload["items"][0]["content"] == content


@pytest.mark.asyncio
async def test_pydantic_ai_accepts_rebuilt_paired_history() -> None:
    state = _state()
    handle = state.store_result(
        "list",
        {"items": [{"entry_id": 7, "title": "七", "project_name": "装修"}]},
        "completed",
        "complete",
    )
    state.remember_turn(
        "列一条",
        "1. 七",
        [
            {
                "tool": "query_entries",
                "shared_tool": "query_entries",
                "result_handle": handle,
                "params": {"project_scope": "all"},
                "shared_params": {"entry_set": _entry_set("all", None, None, None)},
                "status": "completed",
                "completeness": "complete",
                "error": None,
            }
        ],
    )
    history = build_compact_history(state)
    history.insert(0, ModelRequest(parts=[SystemPromptPart(content="过期 Grove 规则")]))
    state.begin_turn(5, "继续")
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "已接续"}]},
                )
            ]
        )

    turn, _ = await run_turn(build_agent(FunctionModel(respond)), state, "继续", history)
    assert turn["status"] == "completed"
    assert calls
    messages, info = calls[0]
    assert info.instructions.startswith(SYSTEM_PROMPT)
    assert "select_relevant_entries" in info.instructions
    assert "过期 Grove 规则" not in str(messages)
    assert SYSTEM_PROMPT not in str(messages)
    assert any(
        isinstance(part, ToolReturnPart)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )


def test_output_rejects_old_or_forged_handles_and_renders_real_values() -> None:
    state = _state()
    statistic = state.store_result("statistic", {"value": 102}, "completed", "complete")
    state.evidence["ev-old"] = {"quote": "旧片段"}
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": "实际统计如下。"},
                {"kind": "statistic", "result_handle": statistic, "label": "总数"},
            ]
        }
    )
    assert output_errors(answer, state) == []
    text, blocks = render_answer(answer, state)
    assert "总数：102" in text
    assert blocks[1]["completeness"] == "complete"

    forged = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "statistic", "result_handle": "fake", "label": "总数"}]}
    )
    assert output_errors(forged, state)
    old_evidence = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "evidence", "evidence_handle": "ev-old"}]}
    )
    assert output_errors(old_evidence, state)


def test_entry_block_renders_read_content_and_rejects_unread_or_forged_results() -> None:
    state = _state()
    entries = state.store_result(
        "entries",
        {
            "items": [
                {
                    "entry_id": 90,
                    "title": "墙面材料建议",
                    "content": "Entry 正文：乳胶漆维护更简单。",
                    "project_name": "房子装修",
                    "node_path": "材质选择/饰面涂料",
                }
            ]
        },
        "completed",
        "limited",
    )
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": f"[[entry:{entries}:1]]",
                }
            ]
        }
    )

    assert output_errors(answer, state) == []
    text, blocks = render_answer(answer, state)
    assert "Entry 正文：乳胶漆维护更简单。" in text
    assert blocks[0]["entry_id"] == 90
    assert blocks[0]["content"] == "Entry 正文：乳胶漆维护更简单。"

    legacy_answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": f"[[{entries}:1]]"}]}
    )
    assert output_errors(legacy_answer, state) == []
    legacy_text, legacy_blocks = render_answer(legacy_answer, state)
    assert "Entry 正文：乳胶漆维护更简单。" in legacy_text
    assert legacy_blocks[0]["entry_id"] == 90

    forged = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": "[[entry:fake:1]]",
                }
            ]
        }
    )
    assert output_errors(forged, state)

    unread = state.store_result(
        "entries",
        {"items": [{"entry_id": 91, "title": "只有标题"}]},
        "completed",
        "limited",
    )
    unread_answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": f"[[entry:{unread}:1]]",
                }
            ]
        }
    )
    assert any("正文未成功读取" in error for error in output_errors(unread_answer, state))


def test_content_request_requires_entry_block_when_read_result_is_available() -> None:
    state = _state()
    state.begin_turn(5, "这条知识的具体内容是什么")
    entries = state.store_result(
        "entries",
        {"items": [{"entry_id": 90, "title": "标题", "content": "真实正文"}]},
        "completed",
        "limited",
    )
    missing = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "具体内容如下。"}]}
    )
    assert any("必须提供正文引用" in error for error in output_errors(missing, state))
    complete = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": "具体内容如下。"},
                {
                    "kind": "text",
                    "text": f"[[entry:{entries}:1]]",
                },
            ]
        }
    )
    assert output_errors(complete, state) == []


def test_no_knowledge_instruction_is_programmatically_recorded() -> None:
    state = _state()
    state.begin_turn(5, "先不查知识库，聊聊怎样记笔记")
    assert state.tools_allowed is False
    state.begin_turn(6, "先别查库，聊聊怎样安排间隔复习")
    assert state.tools_allowed is False
    state.begin_turn(7, "抛开知识库，你觉得这条说法可信吗")
    assert state.tools_allowed is False


@pytest.mark.asyncio
async def test_model_only_opinion_corrects_false_unsupported_without_knowledge_tools() -> None:
    """明确抛开知识库时，通用判断可回答，模型误报不支持不会覆盖正确结果。"""

    state = _state()
    state.remember_turn(
        "第二条主要讲了什么，可信吗",
        "第二条是日本 F4 星级，来源是个人整理，具体标准建议核验原文。",
        [],
    )
    message = "抛开知识库，你觉得可信吗"
    state.begin_turn(3, message)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "report_unsupported",
                        {
                            "target": "对知识库外通用知识可信度的主观评价",
                            "reason": (
                                "当前白名单只支持知识库只读查询，无法核验外部标准原文"
                                "或给出权威可信度结论"
                            ),
                        },
                    )
                ]
            )
        assert info.function_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": (
                                    "抛开知识库，从通用知识看，这条说法方向基本合理，"
                                    "但具体限值和认证条件仍应以标准原文为准。"
                                    "这是模型通用分析，不是外部实时核验。"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(build_agent(FunctionModel(respond)), state, message, [])

    assert calls == 2
    assert turn["status"] == "completed"
    assert turn["completion"]["reason_code"] == "completed"
    assert turn["tool_calls"] == []
    assert state.current_evidence == set()
    assert "方向基本合理" in turn["answer"]
    assert "不是外部实时核验" in turn["answer"]
    assert "tool_capability_missing" not in json.dumps(turn, ensure_ascii=False)


@pytest.mark.asyncio
async def test_no_knowledge_external_verification_remains_unsupported() -> None:
    """禁用知识库不等于获得联网能力，外部官方原文核验仍必须明确不支持。"""

    state = _state()
    message = "抛开知识库，帮我联网核验最新 JAS 官方标准原文"
    state.begin_turn(3, message)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "report_unsupported",
                        {
                            "target": "联网读取并核验最新 JAS 官方标准原文",
                            "reason": "当前没有联网或外部标准原文读取能力",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "insufficient",
                                "text": "当前不能联网读取或核验最新官方标准原文。",
                            }
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(build_agent(FunctionModel(respond)), state, message, [])

    assert turn["status"] == "unsupported"
    assert turn["completion"]["reason_code"] == "tool_capability_missing"
    assert calls == 2
    assert [event["tool"] for event in turn["tool_calls"]] == ["report_unsupported"]
    assert "没有联网或外部标准原文读取能力" in turn["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "帮我补充一下这条知识",
        "把修改后的内容输出给我，我自己更新",
    ],
)
async def test_candidate_revision_corrects_unsupported_and_outputs_review_draft(
    message: str,
) -> None:
    """候选文本生成可完成；模型误报不支持时由程序纠正且不产生写入事件。"""

    state = _state()
    state.begin_turn(5, message)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "report_unsupported",
                        {
                            "target": "更新正式记录",
                            "reason": "当前只有只读工具",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": (
                                    "可以。下面是一版供你审核的候选修改稿，尚未写入知识库。\n\n"
                                    "原记录要点：乳胶漆更省心，壁纸胶可能带来环保风险。\n\n"
                                    "建议补充：环保与寿命取决于产品、胶黏剂和施工条件。\n\n"
                                    "修改后候选版本：墙面材料应结合环保等级、维护成本与装饰需求选择。\n\n"
                                    "说明：以上新增内容基于当前对话的分析和建议，不属于原始来源原文。"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(build_agent(FunctionModel(respond)), state, message, [])

    assert turn["status"] == "completed"
    assert calls == 2
    assert turn["tool_calls"] == []
    assert state.current_evidence == set()
    assert "尚未写入知识库" in turn["answer"]
    assert "原记录要点" in turn["answer"]
    assert "建议补充" in turn["answer"]
    assert "修改后候选版本" in turn["answer"]
    assert "不属于原始来源原文" in turn["answer"]
    assert "unsupported" not in json.dumps(turn, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "直接帮我更新知识库里的这条记录",
        "覆盖原记录并保存",
    ],
)
async def test_direct_entry_write_request_remains_unsupported(message: str) -> None:
    """明确写入或覆盖正式 Entry 时仍停在只读能力边界。"""

    state = _state()
    state.begin_turn(5, message)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "report_unsupported",
                        {
                            "target": "直接修改并保存正式 Entry",
                            "reason": "当前只读白名单不支持写入或覆盖正式记录",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "当前不支持直接写入。"}]},
                )
            ]
        )

    turn, _ = await run_turn(build_agent(FunctionModel(respond)), state, message, [])

    assert turn["status"] == "unsupported"
    assert [event["tool"] for event in turn["tool_calls"]] == ["report_unsupported"]
    assert state.current_evidence == set()
    assert "不支持写入或覆盖正式记录" in turn["answer"]


def test_agent_exposes_split_statistics_without_composite_arguments() -> None:
    agent = build_agent(FunctionModel(lambda _messages, _info: None))
    tools = agent._function_toolset.tools
    assert "count_entries" in tools
    assert "group_entries" in tools
    assert "aggregate_entries" not in tools
    assert not {
        "update_entry",
        "save_entry",
        "write_entry",
        "create_evidence",
    } & set(tools)
    count_schema = tools["count_entries"].function_schema.json_schema
    group_schema = tools["group_entries"].function_schema.json_schema
    assert "operation" not in count_schema["properties"]
    assert "group_by" not in count_schema["properties"]
    assert group_schema["required"] == ["project_scope", "project_name", "group_by"]


def test_candidate_revision_output_requires_sections_and_source_boundary() -> None:
    """候选稿缺少未写入声明或内容分区时，输出校验必须拒绝。"""

    state = _state()
    state.begin_turn(5, "帮我完善一下这条知识")
    incomplete = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "已经帮你更新好了。"}]}
    )

    errors = output_errors(incomplete, state)

    assert errors
    assert "未写入状态" in errors[0]
    assert "原记录内容" in errors[0]
    assert "新增建议" in errors[0]
    assert "修改后版本" in errors[0]
    assert "来源边界" in errors[0]


def test_candidate_revision_accepts_equivalent_source_boundary_wording() -> None:
    """“并非来自该来源原文”等等价说明不能被固定文案校验误拒绝。"""

    state = _state()
    state.begin_turn(5, "帮我补充这条知识，把内容输出给我")
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": (
                        "以下是候选修改稿，尚未写入知识库。\n"
                        "原记录要点：乳胶漆是默认建议。\n"
                        "建议补充：结合产品和施工判断。\n"
                        "修改后候选版本：按实际条件选择墙面材料。\n"
                        "来源边界说明：补充分析并非来自该来源原文。"
                    ),
                }
            ]
        }
    )

    assert output_errors(answer, state) == []


def test_agent_exposes_real_directory_tool_and_separate_position_handles() -> None:
    agent = build_agent(FunctionModel(lambda _messages, _info: None))
    tools = agent._function_toolset.tools
    assert "list_project_directories" in tools
    schema = tools["list_project_directories"].function_schema.json_schema
    assert "parent_result_handle" in schema["properties"]
    assert "parent_position" in schema["properties"]
    assert {"name", "path", "match", "operation"} <= set(schema["properties"])
    assert "find" in schema["properties"]["operation"]["enum"]
    assert "directory_result_handle" in tools["count_entries"].function_schema.json_schema[
        "properties"
    ]

    state = _state()
    handle = state.store_result(
        "directories",
        {
            "project": {"id": 12, "name": "装修"},
            "items": [
                {"node_id": 90, "name": "空目录", "path": "空目录"},
                {"node_id": 91, "name": "材料", "path": "材料"},
            ],
        },
        "completed",
        "complete",
    )
    assert list_directory_position_node_id(state, handle, 2) == 91
    with pytest.raises(ValueError, match="不唯一"):
        directory_reference_item(state, handle)
    with pytest.raises(ValueError):
        list_directory_position_node_id(state, "rs-forged", 1)

    unique = state.store_result(
        "directories",
        {
            "project": {"id": 12, "name": "装修"},
            "items": [{"node_id": 92, "name": "瓷砖地材", "path": "材料 / 瓷砖地材"}],
        },
        "completed",
        "complete",
    )
    assert directory_reference_item(state, unique)["node_id"] == 92


@pytest.mark.asyncio
async def test_known_directory_name_uses_find_without_root_walk(monkeypatch) -> None:
    """已知名称由一次 find 定位，不先调用根级 children 遍历。"""

    state = _state()
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **_kwargs):
        dispatched.append((tool_name, params, kind))
        payload = {
            "project": {"id": 8, "name": "房子装修"},
            "operation": "find",
            "match_status": "unique",
            "items": [
                {
                    "node_id": 81,
                    "name": "瓷砖地材",
                    "project_id": 8,
                    "project_name": "房子装修",
                    "parent_node_id": 80,
                    "path": "设计规划 / 风格设计 / 材质选择 / 瓷砖地材",
                    "depth": 3,
                    "is_leaf": True,
                }
            ],
            "total_count": 1,
            "returned_count": 1,
            "has_more": False,
        }
        handle = ctx.deps.state.store_result(kind, payload, "completed", "complete")
        event = {
            "tool": "list_project_directories",
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "completed",
            "completeness": "complete",
            "params": params,
            "result_summary": {"returned_count": 1, "has_more": False},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_project_directories",
                        {
                            "project_name": "房子装修",
                            "operation": "find",
                            "name": "瓷砖地材",
                            "match": "exact",
                        },
                    )
                ]
            )
        handle = next(iter(state.current_handles))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "list", "result_handle": handle, "label": "定位"}]},
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "瓷砖地材的完整路径是什么？", []
    )

    assert turn["status"] == "completed"
    assert len(dispatched) == 1
    assert dispatched[0][1]["operation"] == "find"
    assert dispatched[0][1]["parent_node_id"] is None
    assert "设计规划 / 风格设计 / 材质选择 / 瓷砖地材" in turn["answer"]


@pytest.mark.asyncio
async def test_project_search_routes_to_strict_project_query(monkeypatch) -> None:
    """明确项目的知识搜索收紧到该项目的结构化语义查询。"""

    state = _state()
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatched.append((tool_name, params, kind, kwargs))
        payload = {
            "items": [
                {
                    "entry_id": 90,
                    "title": "墙面材料选乳胶漆优于壁纸/墙布",
                    "project_name": "房子装修",
                    "node_path": "墙面工程",
                }
            ],
            "returned_count": 1,
            "has_more": False,
        }
        handle = ctx.deps.state.store_result(
            "list", payload, "limited", "limited",
            semantics=loop_module._result_semantics(tool_name, params, payload),
        )
        event = {
            "tool": "search_knowledge",
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "limited",
            "completeness": "limited",
            "params": params,
            "result_summary": {"returned_count": 1, "has_more": False},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)

    def respond(_messages, info):
        if not dispatched:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_knowledge",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "query": "墙纸",
                        },
                    )
                ]
            )
        handle = next(iter(state.current_handles))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "list", "result_handle": handle, "label": "墙纸知识"}
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "房子装修项目中，有关于墙纸的知识吗", []
    )

    assert turn["status"] == "completed", turn
    assert len(dispatched) == 1
    tool_name, params, _kind, kwargs = dispatched[0]
    assert tool_name == "query_entries"
    assert params["entry_set"]["project_name"] == "房子装修"
    assert params["entry_set"]["semantic_query"] == "墙纸"
    assert params["sort"] == {"field": "relevance", "direction": "desc"}
    assert kwargs["surface_tool"] == "search_knowledge"


@pytest.mark.asyncio
async def test_semantic_selection_aligns_search_read_and_rendered_direct_set(
    monkeypatch,
) -> None:
    """原始候选不可展示，选择、读取和前端块只使用同一 direct 集合。"""

    state = _state()
    dispatched = []
    candidates = [
        {
            "entry_id": 11,
            "title": "甲醛的定义与特征",
            "project_name": "房子装修",
            "excerpt": "甲醛是一种挥发性有机物。",
        },
        {
            "entry_id": 22,
            "title": "窗帘清洗注意事项",
            "project_name": "房子装修",
            "excerpt": "装修后清洗窗帘。",
        },
        {
            "entry_id": 33,
            "title": "客厅灯光搭配",
            "project_name": "房子装修",
            "excerpt": "色温与照度。",
        },
    ]

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatched.append((tool_name, params, kwargs))
        if tool_name == "query_entries":
            payload = {"items": candidates, "returned_count": 3, "has_more": False}
            semantics = loop_module._result_semantics(tool_name, params, payload)
            semantics["result_role"] = "candidate"
            handle = ctx.deps.state.store_result(
                "list",
                payload,
                "limited",
                "limited",
                semantics=semantics,
                displayable=False,
            )
            event = {
                "tool": kwargs.get("surface_tool") or tool_name,
                "shared_tool": tool_name,
                "result_handle": handle,
                "status": "limited",
                "completeness": "limited",
                "params": kwargs.get("audit_params") or params,
                "result_summary": {"returned_count": 3, "has_more": False},
                "error": None,
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return {**event, "result_role": "candidate", "payload": payload}
        assert tool_name == "read_entries"
        assert params == {"entry_ids": [11]}
        payload = {
            "items": [
                {
                    "entry_id": 11,
                    "title": "甲醛的定义与特征",
                    "content": "甲醛是一种挥发性有机物。",
                    "project_name": "房子装修",
                    "node_path": "材料 / 环保",
                    "sources": [],
                }
            ],
            "denied_entry_ids": [],
            "unavailable_entry_ids": [],
        }
        handle = ctx.deps.state.store_result("entries", payload, "completed", "limited")
        event = {
            "tool": tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "completed",
            "completeness": "limited",
            "params": params,
            "result_summary": {"returned_count": 1},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_knowledge",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "query": "甲醛",
                        },
                    )
                ]
            )
        candidate = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("result_role") == "candidate"
        )
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "select_relevant_entries",
                        {
                            "candidate_result_handle": candidate,
                            "classifications": [
                                {"entry_id": 11, "relevance": "direct", "reason": "正文定义"},
                                {"entry_id": 22, "relevance": "indirect", "reason": "相关场景"},
                                {"entry_id": 33, "relevance": "unrelated", "reason": "弱相似"},
                            ],
                        },
                    )
                ]
            )
        selected = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("relevance_scope") == "direct"
        )
        if calls == 3:
            return ModelResponse(
                parts=[ToolCallPart("read_entries", {"entry_ids": [11]})]
            )
        read_handle = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].kind == "entries"
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "text", "text": "模型通用知识：甲醛是一种挥发性有机物。"},
                            {"kind": "list", "result_handle": selected, "label": "直接相关"},
                            {"kind": "text", "text": f"[[entry:{read_handle}:1]]"},
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "甲醛是什么？", []
    )

    assert turn["status"] == "completed", turn
    list_block = next(block for block in turn["blocks"] if block["kind"] == "list")
    assert [item["entry_id"] for item in list_block["items"]] == [11]
    assert list_block["semantics"]["classification_counts"] == {
        "direct": 1,
        "indirect": 1,
        "unrelated": 1,
    }
    assert [item[1] for item in dispatched if item[0] == "read_entries"] == [
        {"entry_ids": [11]}
    ]
    assert "窗帘清洗" not in turn["answer"]
    assert "客厅灯光" not in turn["answer"]
    assert turn["blocks"][0]["kind"] == "text"


def test_candidate_handle_cannot_render_or_resolve_position() -> None:
    state = _state()
    candidate = state.store_result(
        "list",
        {"items": [{"entry_id": 8, "title": "弱相关"}]},
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "list", "result_handle": candidate, "label": "候选"}]}
    )

    assert any("内部候选" in error for error in output_errors(answer, state))
    with pytest.raises(ValueError):
        list_position_entry_id(state, candidate, 1)
    state.stop(
        StopState(
            status="partial_completed",
            reason_code="output_validation_failed",
            reason="相关性选择未完成",
            incomplete_steps=["未形成直接相关授权集合"],
            can_continue=True,
        )
    )
    text, blocks = _verified_failure_output(state)
    assert "弱相关" not in text
    assert not any(block["kind"] == "list" for block in blocks)


def test_rejected_candidate_title_cannot_leak_into_answer_text() -> None:
    state = _state()
    candidate = state.store_result(
        "list",
        {
            "items": [
                {"entry_id": 1, "title": "直接主题"},
                {"entry_id": 2, "title": "间接材料"},
            ]
        },
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    state.store_result(
        "list",
        {
            "items": [{"entry_id": 1, "title": "直接主题"}],
            "internal_classifications": [
                {"entry_id": 1, "relevance": "direct"},
                {"entry_id": 2, "relevance": "indirect"},
            ],
        },
        "completed",
        "limited",
        semantics={
            "result_role": "authorized",
            "candidate_result_handle": candidate,
        },
    )
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "还可以参考间接材料。"}]}
    )

    assert "主答案包含间接相关或不相关候选的标题" in output_errors(
        answer, state
    )


def test_definition_with_no_direct_records_requires_explicit_insufficient_block() -> None:
    state = _state()
    state.current_message = "某种材料是什么？"
    candidate = state.store_result(
        "list",
        {"items": [{"entry_id": 2, "title": "相关场景"}]},
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    state.store_result(
        "list",
        {
            "items": [],
            "internal_classifications": [
                {"entry_id": 2, "relevance": "indirect"}
            ],
        },
        "empty",
        "limited",
        semantics={
            "result_role": "authorized",
            "relevance_scope": "direct",
            "candidate_result_handle": candidate,
        },
    )
    incomplete = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "模型通用知识：这是一个概念。"}]}
    )
    complete = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": "模型通用知识：这是一个概念。"},
                {"kind": "insufficient", "text": "没有找到直接相关正式记录。"},
            ]
        }
    )

    assert any("必须明确说明结果不足" in error for error in output_errors(incomplete, state))
    assert output_errors(complete, state) == []


@pytest.mark.asyncio
async def test_equivalent_semantic_tools_dispatch_only_one_search(monkeypatch) -> None:
    state = _state()
    dispatches = []

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatches.append((tool_name, params))
        payload = {
            "items": [{"entry_id": 7, "title": "直接结果", "project_name": "房子装修"}],
            "returned_count": 1,
            "has_more": False,
        }
        semantics = loop_module._result_semantics(tool_name, params, payload)
        semantics["result_role"] = "candidate"
        handle = ctx.deps.state.store_result(
            kind,
            payload,
            "limited",
            "limited",
            semantics=semantics,
            displayable=False,
        )
        event = {
            "tool": kwargs.get("surface_tool") or tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "limited",
            "completeness": "limited",
            "params": kwargs.get("audit_params") or params,
            "result_summary": {"returned_count": 1, "has_more": False},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "result_role": "candidate", "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_knowledge",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "query": "墙面材料",
                        },
                    ),
                    ToolCallPart(
                        "query_entries",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "semantic_query": "墙面材料",
                            "limit": 10,
                            "sort_field": "relevance",
                            "sort_direction": "desc",
                        },
                    ),
                ]
            )
        candidate = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("result_role") == "candidate"
        )
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "select_relevant_entries",
                        {
                            "candidate_result_handle": candidate,
                            "classifications": [
                                {"entry_id": 7, "relevance": "direct", "reason": "直接回答"}
                            ],
                        },
                    )
                ]
            )
        selected = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("relevance_scope") == "direct"
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "list", "result_handle": selected, "label": "结果"}]},
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "帮我查墙面材料", []
    )

    assert turn["status"] == "completed", turn
    assert len(dispatches) == 1
    assert sum(
        event.get("reason_code") == "duplicate_semantic_query"
        for event in turn["tool_calls"]
    ) == 1


@pytest.mark.asyncio
async def test_legacy_sort_and_string_null_are_normalized_once(monkeypatch) -> None:
    state = _state()
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatched.append((tool_name, params, kwargs))
        payload = {"items": [], "returned_count": 0, "has_more": False}
        handle = ctx.deps.state.store_result(kind, payload, "empty", "complete")
        event = {
            "tool": tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "empty",
            "completeness": "complete",
            "params": kwargs.get("audit_params") or params,
            "result_summary": {"returned_count": 0, "has_more": False},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_entries",
                        {
                            "project_scope": "all",
                            "project_name": "null",
                            "semantic_query": "null",
                            "main_types": "null",
                            "directory_result_handle": "null",
                            "directory_position": "null",
                            "directory_scope": "null",
                            "limit": 5,
                            "sort": {"field": "updated_at", "direction": "desc"},
                        },
                    )
                ]
            )
        handle = next(iter(state.current_handles))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "list", "result_handle": handle, "label": "最近"}]},
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "列出最近五条记录", []
    )

    assert turn["status"] == "completed", turn
    assert len(dispatched) == 1
    _, params, kwargs = dispatched[0]
    assert params["entry_set"]["project_name"] is None
    assert params["entry_set"]["semantic_query"] is None
    assert params["entry_set"]["main_types"] == []
    assert params["sort"] == {"field": "updated_at", "direction": "desc"}
    assert "sort" in kwargs["audit_params"]


@pytest.mark.asyncio
async def test_contextual_search_follow_up_reuses_prior_topic_and_scope(monkeypatch) -> None:
    state = _state()
    state.remember_turn(
        "房子装修项目里甲醛可能来自哪里？",
        "我可以继续查询知识库中的直接相关记录。",
        [],
    )
    history = build_compact_history(state)
    state.begin_turn(5, "好的，你帮我查一下")
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatched.append((tool_name, params, kwargs))
        payload = {"items": [], "returned_count": 0, "has_more": False}
        semantics = loop_module._result_semantics(tool_name, params, payload)
        semantics["result_role"] = "candidate"
        handle = ctx.deps.state.store_result(
            kind,
            payload,
            "empty",
            "limited",
            semantics=semantics,
            displayable=False,
        )
        event = {
            "tool": kwargs.get("surface_tool") or tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "empty",
            "completeness": "limited",
            "params": kwargs.get("audit_params") or params,
            "result_summary": {"returned_count": 0, "has_more": False},
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "result_role": "candidate", "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert "当前消息是对上一轮建议的承接查询" in info.instructions
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_knowledge",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "query": "甲醛来源",
                        },
                    )
                ]
            )
        candidate = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("result_role") == "candidate"
        )
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "select_relevant_entries",
                        {"candidate_result_handle": candidate, "classifications": []},
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "text", "text": "查询已执行。"},
                            {"kind": "insufficient", "text": "没有找到直接相关正式记录。"},
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "好的，你帮我查一下", history
    )

    assert turn["status"] == "completed", turn
    assert len(dispatched) == 1
    assert dispatched[0][1]["entry_set"]["project_name"] == "房子装修"
    assert dispatched[0][1]["entry_set"]["semantic_query"] == "甲醛来源"


@pytest.mark.asyncio
async def test_search_success_read_failure_continues_without_repeating_search(
    monkeypatch,
) -> None:
    state = _state()
    dispatches = []
    read_attempts = 0

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        nonlocal read_attempts
        dispatches.append((tool_name, params))
        if tool_name == "query_entries":
            payload = {
                "items": [{"entry_id": 9, "title": "甲醛来源", "project_name": "房子装修"}],
                "returned_count": 1,
                "has_more": False,
            }
            semantics = loop_module._result_semantics(tool_name, params, payload)
            semantics["result_role"] = "candidate"
            handle = ctx.deps.state.store_result(
                kind,
                payload,
                "limited",
                "limited",
                semantics=semantics,
                displayable=False,
            )
            status = "limited"
            error = None
        else:
            read_attempts += 1
            if read_attempts == 1:
                payload = {
                    "items": [],
                    "denied_entry_ids": [],
                    "unavailable_entry_ids": [9],
                }
                status = "error"
                error = "Entry 正文暂时不可用"
            else:
                payload = {
                    "items": [
                        {
                            "entry_id": 9,
                            "title": "甲醛来源",
                            "content": "来源包括部分装修材料。",
                            "project_name": "房子装修",
                            "node_path": "环保",
                            "sources": [],
                        }
                    ],
                    "denied_entry_ids": [],
                    "unavailable_entry_ids": [],
                }
                status = "completed"
                error = None
            handle = ctx.deps.state.store_result(kind, payload, status, "limited")
        event = {
            "tool": kwargs.get("surface_tool") or tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": status,
            "completeness": "limited",
            "params": kwargs.get("audit_params") or params,
            "result_summary": {
                "returned_count": len(payload.get("items", [])),
                "has_more": False,
            },
            "error": error,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {
            **event,
            "result_role": (
                "candidate" if tool_name == "query_entries" else "authorized"
            ),
            "payload": payload,
        }

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def first_respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "search_knowledge",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "query": "甲醛来源",
                        },
                    )
                ]
            )
        candidate = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("result_role") == "candidate"
        )
        if calls == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "select_relevant_entries",
                        {
                            "candidate_result_handle": candidate,
                            "classifications": [
                                {"entry_id": 9, "relevance": "direct", "reason": "直接回答"}
                            ],
                        },
                    )
                ]
            )
        selected = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].semantics.get("relevance_scope") == "direct"
        )
        if calls == 3:
            return ModelResponse(parts=[ToolCallPart("read_entries", {"entry_ids": [9]})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "list", "result_handle": selected, "label": "已找到"},
                            {"kind": "insufficient", "text": "正文尚未读取。"},
                        ]
                    },
                )
            ]
        )

    first, history = await run_turn(
        build_agent(FunctionModel(first_respond)), state, "查甲醛来源", []
    )
    assert first["status"] == "partial_completed", first
    assert first["completion"]["reason_code"] == "search_succeeded_read_failed"
    assert state.continuation is not None
    assert sum(tool == "query_entries" for tool, _params in dispatches) == 1

    state.begin_turn(5, "继续")
    second_calls = 0

    def second_respond(_messages, info):
        nonlocal second_calls
        second_calls += 1
        if second_calls == 1:
            assert "read_entries" in info.instructions
            return ModelResponse(parts=[ToolCallPart("read_entries", {"entry_ids": [9]})])
        read_handle = next(
            handle
            for handle in state.current_handles
            if state.result_sets[handle].kind == "entries"
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": f"[[entry:{read_handle}:1]]"}]},
                )
            ]
        )

    second, _ = await run_turn(
        build_agent(FunctionModel(second_respond)), state, "继续", history
    )
    assert second["status"] == "completed", second
    assert sum(tool == "query_entries" for tool, _params in dispatches) == 1
    assert read_attempts == 2
    assert "来源包括部分装修材料" in second["answer"]


def test_limited_result_without_more_is_not_an_incomplete_step() -> None:
    """语义结果可保持 limited 完整性，但没有后续页时不显示未完成警告。"""

    state = _state()
    assert _stop_from_events(
        state,
        [
            {
                "tool": "search_knowledge",
                "status": "limited",
                "completeness": "limited",
                "result_summary": {"returned_count": 1, "has_more": False},
            }
        ],
    ) is None

    stop = _stop_from_events(
        state,
        [
            {
                "tool": "query_entries",
                "status": "limited",
                "completeness": "limited",
                "result_summary": {"returned_count": 10, "has_more": True},
            }
        ],
    )
    assert stop is not None
    assert stop.status == "failed"


@pytest.mark.asyncio
async def test_missing_directory_does_not_fall_back_to_root_walk(monkeypatch) -> None:
    """完整未命中后即使模型请求根级 children，也复用结果并明确回答不存在。"""

    state = _state()
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **_kwargs):
        dispatched.append((tool_name, params, kind))
        assert params["operation"] == "find"
        payload = {
            "project": {"id": 8, "name": "房子装修"},
            "operation": "find",
            "query": {
                "name": "墙纸施工",
                "path": None,
                "requested_match": "exact",
                "applied_match": "exact",
            },
            "match_status": "not_found",
            "items": [],
            "total_count": 0,
            "returned_count": 0,
            "has_more": False,
        }
        handle = ctx.deps.state.store_result(
            kind,
            payload,
            "empty",
            "complete",
            semantics=loop_module._result_semantics(tool_name, params, payload),
        )
        event = {
            "tool": "list_project_directories",
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "empty",
            "completeness": "complete",
            "params": params,
            "reason_code": "directory_not_found",
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_project_directories",
                        {
                            "project_name": "房子装修",
                            "operation": "find",
                            "name": "墙纸施工",
                            "match": "exact",
                        },
                    )
                ]
            )
        if calls in {2, 3, 4}:
            parent_node_id = {2: None, 3: 0, 4: -1}[calls]
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_project_directories",
                        {
                            "project_name": "房子装修",
                            "operation": "children",
                            "parent_node_id": parent_node_id,
                        },
                    )
                ]
            )
        handle = next(iter(state.current_handles))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "list", "result_handle": handle, "label": "定位"}]},
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "墙纸施工目录在哪里？", []
    )

    assert turn["status"] == "completed"
    assert len(dispatched) == 1
    assert [item["status"] for item in turn["tool_calls"]] == [
        "empty",
        "not_executed",
        "not_executed",
        "not_executed",
    ]
    assert {
        item["params"]["parent_node_id"] for item in turn["tool_calls"][1:]
    } == {None, 0, -1}
    assert {
        item["reason_code"] for item in turn["tool_calls"][1:]
    } == {"directory_lookup_already_resolved"}
    assert turn["answer"] == "房子装修 · 未找到名为「墙纸施工」的目录。"
    assert "权限" not in turn["answer"]


@pytest.mark.asyncio
async def test_follow_up_reuses_unique_directory_handle_for_node_scope(monkeypatch) -> None:
    """后续计数从历史定位句柄解析 Node，不重复按名称查找。"""

    state = _state()
    directory_handle = state.store_result(
        "directories",
        {
            "project": {"id": 8, "name": "房子装修"},
            "operation": "find",
            "match_status": "unique",
            "items": [
                {
                    "node_id": 81,
                    "name": "瓷砖地材",
                    "project_id": 8,
                    "project_name": "房子装修",
                    "path": "材质选择 / 瓷砖地材",
                }
            ],
        },
        "completed",
        "complete",
    )
    state.begin_turn(5, "这个目录下有多少条知识？")
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **_kwargs):
        dispatched.append((tool_name, params, kind))
        payload = {"value": 6, "node_scope": {"node_id": 81, "scope": "subtree"}}
        handle = ctx.deps.state.store_result(kind, payload, "completed", "complete")
        event = {
            "tool": "count_entries",
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "completed",
            "completeness": "complete",
            "params": params,
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "count_entries",
                        {
                            "project_scope": "project",
                            "project_name": "房子装修",
                            "directory_result_handle": directory_handle,
                            "directory_scope": "subtree",
                        },
                    )
                ]
            )
        statistic = next(iter(state.current_handles))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "statistic", "result_handle": statistic, "label": "总数"}
                        ]
                    },
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "这个目录下有多少条知识？", []
    )

    assert turn["status"] == "completed"
    assert [item[0] for item in dispatched] == ["aggregate_entries"]
    assert dispatched[0][1]["project_id"] == 8
    assert dispatched[0][1]["node_id"] == 81
    assert dispatched[0][1]["node_scope"] == "subtree"
    assert turn["answer"] == "总数：6"


@pytest.mark.asyncio
async def test_leaf_follow_up_reuses_handle_and_confirms_empty_children(monkeypatch) -> None:
    """询问叶子或子目录时复用唯一定位句柄，并实际查询该 Node 的 children。"""

    state = _state()
    directory_handle = state.store_result(
        "directories",
        {
            "project": {"id": 8, "name": "房子装修"},
            "operation": "find",
            "match_status": "unique",
            "items": [
                {
                    "node_id": 81,
                    "name": "瓷砖地材",
                    "project_id": 8,
                    "project_name": "房子装修",
                    "path": "材质选择 / 瓷砖地材",
                    "is_leaf": True,
                }
            ],
        },
        "completed",
        "complete",
    )
    state.begin_turn(6, "这个目录下面还有哪些子目录？")
    dispatched = []

    async def fake_dispatch(ctx, tool_name, params, kind, **_kwargs):
        dispatched.append((tool_name, params, kind))
        payload = {
            "project": {"id": 8, "name": "房子装修"},
            "parent": {
                "node_id": 81,
                "name": "瓷砖地材",
                "path": "材质选择 / 瓷砖地材",
            },
            "items": [],
            "total_count": 0,
            "returned_count": 0,
            "has_more": False,
        }
        handle = ctx.deps.state.store_result(kind, payload, "empty", "complete")
        event = {
            "tool": "list_project_directories",
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "empty",
            "completeness": "complete",
            "params": params,
            "error": None,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "list_project_directories",
                        {
                            "project_name": "房子装修",
                            "parent_result_handle": directory_handle,
                            "operation": "children",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "这个目录没有直接子目录。"}]},
                )
            ]
        )

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)), state, "这个目录下面还有哪些子目录？", []
    )

    assert turn["status"] == "completed"
    assert len(dispatched) == 1
    assert dispatched[0][1]["operation"] == "children"
    assert dispatched[0][1]["parent_node_id"] == 81
    assert dispatched[0][1]["name"] is None
    assert turn["answer"] == "这个目录没有直接子目录。"


def test_structured_rendering_uses_authoritative_dimension_and_directory_titles() -> None:
    state = _state()
    statistic = state.store_result(
        "statistic",
        {"buckets": [{"key": "method", "count": 2}]},
        "completed",
        "complete",
        semantics={
            "project_name": "装修",
            "group_by": "main_type",
            "group_by_display_name": "知识类型",
            "subject": "entries",
        },
    )
    directories = state.store_result(
        "directories",
        {
            "project": {"id": 1, "name": "装修"},
            "items": [{"node_id": 3, "name": "水电", "path": "水电"}],
            "total_count": 1,
            "returned_count": 1,
            "has_more": False,
        },
        "completed",
        "complete",
        semantics={
            "subject": "directories",
            "project_name": "装修",
            "display_name": "一级目录",
        },
    )
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "statistic", "result_handle": statistic, "label": "一级目录"},
                {"kind": "list", "result_handle": directories, "label": "知识列表"},
            ]
        }
    )
    text, blocks = render_answer(answer, state)
    assert "按知识类型统计" in text
    assert "一级目录" in text
    assert "方法：2" in text
    assert blocks[0]["semantics"]["subject"] == "entries"
    assert blocks[1]["items"][0]["node_id"] == 3


def test_directory_history_keeps_only_ordered_node_metadata() -> None:
    state = _state()
    handle = state.store_result(
        "directories",
        {
            "project": {"id": 8, "name": "装修"},
            "parent": None,
            "items": [
                {"node_id": 11, "name": "水电", "parent_node_id": None, "path": "水电"},
                {"node_id": 12, "name": "木工", "parent_node_id": None, "path": "木工"},
            ],
            "total_count": 2,
            "returned_count": 2,
            "has_more": False,
        },
        "completed",
        "complete",
        semantics={
            "subject": "directories",
            "project_id": 8,
            "project_name": "装修",
            "display_name": "一级目录",
            "total_count": 2,
            "returned_count": 2,
            "completeness": "complete",
        },
    )
    state.remember_turn(
        "列出一级目录",
        "1. 水电\n2. 木工",
        [
            {
                "tool": "list_project_directories",
                "shared_tool": "list_project_directories",
                "result_handle": handle,
                "params": {"project_id": 8, "parent_node_id": None},
                "status": "completed",
                "completeness": "complete",
                "error": None,
            }
        ],
    )
    history = build_compact_history(state)
    returned = history[2].parts[0].content
    assert returned["directory_items"][1]["node_id"] == 12
    assert returned["directory_total_count"] == 2
    assert "content" not in str(returned)


def test_snapshot_rejects_original_target_and_uses_private_file(tmp_path: Path) -> None:
    import sqlite3

    original = tmp_path / "original.db"
    with sqlite3.connect(original) as db:
        db.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO demo(value) VALUES ('只读快照')")
    with pytest.raises(ValueError, match="不能等于原业务库"):
        backup_database(original, original)
    copied = tmp_path / "copy.db"
    backup_database(original, copied)
    assert copied.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(copied) as db:
        assert db.execute("SELECT value FROM demo").fetchone()[0] == "只读快照"


def test_worker_or_database_misconfiguration_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "original.db"
    copy = tmp_path / "copy.db"
    original.touch()
    copy.touch()
    for key in (
        "PROCESSING_WORKER_ENABLED",
        "CONTEXT_WORKER_ENABLED",
        "DIRECTORY_DRAFT_WORKER_ENABLED",
        "EMBEDDING_WORKER_ENABLED",
        "KNOWLEDGE_AGENT_WORKER_ENABLED",
    ):
        monkeypatch.setenv(key, "false")
    assert_isolated(copy, original)
    with pytest.raises(ValueError, match="不能等于原业务库"):
        assert_isolated(original, original)
    monkeypatch.setenv("KNOWLEDGE_AGENT_WORKER_ENABLED", "true")
    with pytest.raises(ValueError, match="后台任务未隔离"):
        assert_isolated(copy, original)


def test_report_redacts_credentials_and_keeps_unknown_usage() -> None:
    value = sanitize(
        {
            "password": "bad",
            "api_key": "also-bad",
            "usage": None,
            "nested": {"authorization": "Bearer bad"},
            "error": (
                "Authorization: Bearer abcdefghijklmnopqrst and "
                "sk-abcdefghijklmnopqrst"
            ),
        }
    )
    assert value["password"] == "<redacted>"
    assert value["api_key"] == "<redacted>"
    assert value["nested"]["authorization"] == "<redacted>"
    assert value["error"] == "Authorization: <redacted> and <redacted>"
    assert value["usage"] is None


def test_report_normalizes_decimal_and_collections_for_checkpoints() -> None:
    import json

    value = sanitize(
        {
            "usage": {"cost": Decimal("0.0000123")},
            "entry_reads": {9, 3},
            "history": ("a", "b"),
        }
    )
    assert value["usage"]["cost"] == "0.0000123"
    assert value["entry_reads"] == [3, 9]
    assert value["history"] == ["a", "b"]
    json.dumps(value)


def test_infrastructure_signature_uses_root_exception_on_python_314() -> None:
    failure = InfrastructureFailure(
        "TypeError: Object of type Decimal is not JSON serializable\n"
        "when serializing dict item 'cost'\n"
        "when serializing dict item 'turns'",
        1,
    )
    assert failure.signature == "TypeError: Object of type Decimal is not JSON serializable"


def test_child_result_writer_serializes_decimal(tmp_path: Path) -> None:
    import json

    result_path = tmp_path / "result.json"
    _write(result_path, {"usage": {"cost": Decimal("0.25")}})
    assert json.loads(result_path.read_text())["usage"]["cost"] == "0.25"
    assert result_path.stat().st_mode & 0o777 == 0o600


def test_rehearsal_mode_is_separate_from_live_comparison() -> None:
    assert parser().parse_args(["--rehearsal"]).rehearsal is True
    with pytest.raises(SystemExit):
        parser().parse_args(["--rehearsal", "--compare", "--live"])


def test_old_structured_results_are_evaluated_as_public_output() -> None:
    oracle = {
        "projects": [
            {"id": 1, "name": "项目甲", "entry_count": 2},
            {"id": 2, "name": "项目乙", "entry_count": 0},
        ],
        "entries": [],
    }
    count = {
        "answer": "",
        "status": "completed",
        "public_run": {"entry_result": {"count": {"value": 2}}},
    }
    groups = {
        "answer": "",
        "status": "completed",
        "public_run": {
            "entry_result": {
                "group_counts": [
                    {
                        "group_by": "project",
                        "buckets": [
                            {"label": "项目甲", "count": 2},
                            {"label": "项目乙", "count": 0},
                        ],
                    }
                ]
            }
        },
    }
    result = evaluate(
        [{"arm": "old", "scenario": "A", "turns": [count, groups, count, groups]}],
        oracle,
    )
    assert [item["status"] for item in result["turns"]] == ["pass"] * 4


def test_new_total_cannot_pass_by_summing_category_buckets() -> None:
    oracle = {"projects": [{"id": 1, "name": "项目甲", "entry_count": 5}], "entries": []}
    grouped_only = {
        "answer": "knowledge：2；method：3",
        "status": "completed",
        "blocks": [
            {
                "kind": "statistic",
                "group_by": "main_type",
                "buckets": [
                    {"key": "knowledge", "count": 2},
                    {"key": "method", "count": 3},
                ],
                "text": "knowledge：2；method：3",
            }
        ],
    }
    turns = [grouped_only, grouped_only, grouped_only, grouped_only]
    result = evaluate([{"arm": "new", "scenario": "A", "turns": turns}], oracle)
    assert result["turns"][0]["status"] == "fail"
    assert result["turns"][0]["reasons"] == ["公开结果未展示期望精确值 5"]
    assert result["dialogues"][0]["status"] == "fail"


def test_not_executed_turn_is_not_sent_to_manual_content_review() -> None:
    oracle = {"projects": [], "entries": []}
    turn = {
        "answer": "查询参数未通过校验。",
        "error": None,
        "status": "not_executed",
    }

    result = evaluate(
        [{"arm": "new", "scenario": "A", "turns": [turn]}],
        oracle,
    )

    assert result["turns"][0]["status"] == "fail"
    assert result["turns"][0]["reasons"] == ["not_executed"]


def test_project_bucket_scoring_checks_name_count_pairs() -> None:
    oracle = {
        "projects": [
            {"id": 1, "name": "甲", "entry_count": 2},
            {"id": 2, "name": "乙", "entry_count": 3},
        ],
        "entries": [],
    }
    count = {
        "answer": "总数：5",
        "status": "completed",
        "blocks": [{"kind": "statistic", "value": 5, "text": "总数：5"}],
    }
    swapped = {
        "answer": "甲：3；乙：2",
        "status": "completed",
        "blocks": [
            {
                "kind": "statistic",
                "group_by": "project",
                "buckets": [{"label": "甲", "count": 3}, {"label": "乙", "count": 2}],
            }
        ],
    }
    result = evaluate(
        [{"arm": "new", "scenario": "A", "turns": [count, swapped, count, swapped]}],
        oracle,
    )
    assert result["turns"][1]["status"] == "fail"
    assert set(result["turns"][1]["reasons"][0]) >= {"甲", "乙"}


def test_old_record_list_does_not_require_evidence_before_grove_only_turn() -> None:
    oracle = {"projects": [], "entries": []}
    visible_list = {
        "answer": "",
        "status": "completed",
        "public_run": {"entry_result": {"items": [{"entry_id": 1}]}},
    }
    result = evaluate(
        [{"arm": "old", "scenario": "B", "turns": [visible_list] * 4}],
        oracle,
    )
    assert result["turns"][2]["status"] == "review"
    assert result["turns"][3]["status"] == "fail"


def test_old_structured_result_is_rendered_as_public_answer() -> None:
    turn = {
        "answer": "",
        "public_run": {"entry_result": {"count": {"value": 102}}},
    }
    rendered = _visible_answer(turn, "old")
    assert "公开结构化结果" in rendered
    assert '"value": 102' in rendered


def test_list_reference_uses_each_arm_actual_displayed_third_item() -> None:
    oracle = {
        "projects": [{"id": 1, "name": "房子装修", "entry_count": 5}],
        "entries": [
            {"id": entry_id, "project_id": 1} for entry_id in (14, 64, 7, 92, 91)
        ],
    }
    turns = [
        {
            "answer": "",
            "status": "completed",
            "blocks": [
                {
                    "kind": "list",
                    "items": [{"entry_id": value} for value in (14, 7, 92, 91, 90)],
                }
            ],
        },
        {"answer": "已复验 Entry 92", "status": "completed", "blocks": []},
        {"answer": "通用回答", "status": "completed", "blocks": [], "tool_calls": []},
        {
            "answer": "再次核对 Entry 92",
            "status": "completed",
            "blocks": [{"kind": "evidence", "items": [{"entry_id": 92}]}],
        },
    ]
    result = evaluate([{"arm": "new", "scenario": "C", "turns": turns}], oracle)
    assert result["turns"][0]["status"] == "fail"
    assert result["turns"][1]["status"] == "review"
    assert result["turns"][3]["status"] == "review"


def test_denied_tool_request_is_not_reported_as_shared_tool_failure() -> None:
    results = [
        {
            "arm": "new",
            "scenario": "A",
            "turns": [
                {
                    "error": None,
                    "tool_calls": [
                        {"tool": "aggregate_entries", "status": "denied", "error": "参数非法"}
                    ],
                }
            ],
        }
    ]
    conclusion = _conclusion(
        results,
        {"turns": [{"arm": "new", "scenario": "A", "status": "pass"}]},
        None,
    )
    assert "未识别到" in conclusion["shared_tools"]
    assert "边界拒绝 1 次" in conclusion["architecture"]


def test_resource_summary_separates_arms_and_keeps_unknown_cost() -> None:
    results = [
        {
            "arm": "new",
            "scenario": "A",
            "turns": [
                {
                    "duration_ms": 25,
                    "budget": {"turn": {"text_requests": 1, "embedding_requests": 0}},
                    "model_calls": [
                        {
                            "kind": "text",
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 2,
                                "cache_read_tokens": 4,
                                "cost": None,
                            },
                        }
                    ],
                }
            ],
        }
    ]
    summary = _resource_by_arm(results)
    assert summary["new"]["text_requests"] == 1
    assert summary["new"]["input_tokens"] == 10
    assert summary["new"]["cost_available"] is False
    assert summary["old"]["user_messages"] == 0


def test_estimate_summary_separates_dispatched_usage_from_unknown_blocked_request() -> None:
    summary = _input_estimation_by_scope(
        [
            {
                "kind": "text",
                "request_scope": "dialogue_agent",
                "estimated_input_tokens": 1_200,
                "actual_input_tokens": 1_000,
            },
            {
                "kind": "text_not_dispatched",
                "request_scope": "dialogue_agent",
                "estimated_input_tokens": 9_500,
                "actual_input_tokens": None,
            },
        ]
    )["dialogue_agent"]
    assert summary["dispatched_with_usage"] == 1
    assert summary["not_dispatched"] == 1
    assert summary["actual_unknown"] == 1
    assert summary["estimated_tokens"] == 10_700
    assert summary["estimated_tokens_with_usage"] == 1_200
    assert summary["aggregate_ratio"] == 1.2


def test_rehearsal_writes_four_json_safe_checkpoints() -> None:
    import json

    checkpoints = []

    def checkpoint(value: dict) -> None:
        checkpoints.append(json.loads(json.dumps(sanitize(value))))

    result = _rehearsal_scenario("new", "A", checkpoint)
    assert len(checkpoints) == 4
    assert [len(item["turns"]) for item in checkpoints] == [1, 2, 3, 4]
    assert result["turns"][0]["model_calls"][0]["kind"] == "pipeline_fixture"
    assert checkpoints[0]["turns"][0]["usage"]["cost"] == "0.000000"
    assert checkpoints[0]["turns"][0]["budget"]["turn"]["entry_reads"] == [1]
    assert checkpoints[0]["turns"][0]["context"]["experiment_version"] == "prototype-v3"


def test_v2_control_preflight_is_entirely_deterministic_and_passes() -> None:
    assert all(_v2_control_preflight().values())


def test_next_batch_variants_are_frozen_outside_system_prompt() -> None:
    plan = evaluation_plan()
    assert [item.id for item in VARIANT_SCENARIOS] == ["D", "E"]
    assert plan["maximum_user_messages"] == 40
    assert plan["status"] == "awaiting_user_approval"
    assert all(
        turn not in SYSTEM_PROMPT for scenario in VARIANT_SCENARIOS for turn in scenario.turns
    )
    assert parser().parse_args(["--rehearsal", "--suite", "v2"]).suite == "v2"


def test_budget_snapshot_is_json_serializable() -> None:
    import json

    state = _state()
    state.ledger.reserve_entries([9, 3])
    raw = json.dumps(state.ledger.snapshot())
    assert '"entry_reads": [3, 9]' in raw


def test_timeout_finalize_history_pairs_all_current_verified_materials() -> None:
    state = _state()
    handle = state.store_result("statistic", {"value": 6}, "completed", "complete")
    state.tool_events.append(
        {
            "tool": "count_entries",
            "result_handle": handle,
            "status": "completed",
            "completeness": "complete",
            "params": {"project_scope": "all"},
        }
    )

    messages = _current_material_history(state, "一共多少条", [], state.tool_events)
    call = messages[1].parts[0]
    returned = messages[2].parts[0]

    assert isinstance(call, ToolCallPart)
    assert isinstance(returned, ToolReturnPart)
    assert call.tool_call_id == returned.tool_call_id
    assert returned.content["payload"]["value"] == 6


@pytest.mark.asyncio
async def test_structured_output_gets_only_one_bounded_correction() -> None:
    state = _state()
    handle = state.store_result("statistic", {"value": 7}, "completed", "complete")
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        selected = "forged" if len(calls) == 1 else handle
        output = {"blocks": [{"kind": "statistic", "result_handle": selected, "label": "总数"}]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent = build_agent(FunctionModel(respond))
    turn, _ = await run_turn(agent, state, "统计总数", [])
    assert turn["status"] == "completed"
    assert turn["answer"] == "总数：7"
    assert len(calls) == 2
    assert all(info.instructions.startswith(SYSTEM_PROMPT) for _, info in calls)
    assert all(SYSTEM_PROMPT not in str(messages) for messages, _ in calls)


@pytest.mark.asyncio
async def test_context_over_limit_stops_without_model_call() -> None:
    state = _state()
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "不应调用"}]},
                )
            ]
        )

    agent = build_agent(FunctionModel(respond))
    turn, _ = await run_turn(agent, state, "继续", ["x" * 50_000])
    assert turn["status"] == "not_executed"
    assert turn["completion"]["reason_code"] == "input_hard_limit"
    assert turn["error"] is None
    assert calls == []


@pytest.mark.asyncio
async def test_first_request_between_soft_and_hard_limits_is_dispatched() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "在预算内收尾"}]},
                )
            ]
        )

    wrapped = BudgetedModel(FunctionModel(respond), state.instrumentation)
    agent = build_agent(wrapped)
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(agent, state, "请总结", history, build_finalizer_agent(wrapped))
    assert turn["status"] == "completed"
    assert len(calls) == 1
    assert calls[0][1].function_tools
    assert calls[0][1].instructions.startswith(SYSTEM_PROMPT)
    assert SYSTEM_PROMPT not in str(calls[0][0])
    assert FINALIZE_INSTRUCTION not in str(calls[0][0])
    assert turn["budget"]["turn"]["text_requests"] == 1
    estimate = turn["context"]["input_estimates"][0]["estimated_input_tokens"]
    assert INPUT_ESTIMATE_SOFT_LIMIT <= estimate <= MODEL_INPUT_TOKENS_LIMIT
    assert turn["context"]["input_estimates"][0]["finalize_only"] is False
    assert turn["finalization"]["status"] == "not_needed"


@pytest.mark.asyncio
async def test_solve_timeout_uses_at_most_one_separate_finalize_request(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(loop_module, "PER_TURN_SECONDS", 0.01)
    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    async def respond(messages, info):
        calls.append((messages, info))
        if len(calls) == 1:
            await asyncio.sleep(1)
        await asyncio.sleep(0.03)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "使用已有材料完成收尾"}]},
                )
            ]
        )

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    turn, _ = await run_turn(agent, state, "请查询后回答", [])

    assert turn["status"] == "partial_completed"
    assert turn["solve_error"] == "TimeoutError: 求解超过 0.01 秒"
    assert turn["finalization"]["reason"] == "solve_timeout"
    assert turn["finalization"]["status"] == "completed"
    assert turn["budget"]["turn"]["text_requests"] == 2
    assert len(calls) == 2
    assert calls[1][1].function_tools == []


@pytest.mark.asyncio
async def test_last_batch_text_request_is_reserved_for_finalize() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    state.ledger.batch_text_requests = BATCH_TEXT_REQUESTS - 1
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "最后一次请求用于收尾"}]},
                )
            ]
        )

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    turn, _ = await run_turn(agent, state, "请回答", [])

    assert turn["status"] == "completed"
    assert turn["finalization"]["reason"] == "text_request_budget"
    assert turn["finalization"]["attempted"] is True
    assert turn["budget"]["batch_text_requests"] == BATCH_TEXT_REQUESTS
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_tool_action_budget_stop_uses_one_tool_free_finalize() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    for _ in range(PER_TURN_TOOL_CALLS):
        await state.ledger.reserve_tool()
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("list_projects", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "工具额度已用完。"}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    turn, _ = await run_turn(build_agent(model), state, "继续查询", [])

    assert turn["status"] == "not_executed"
    assert turn["solve_error"] == "BudgetExceeded: 本轮工具动作预算已耗尽"
    assert turn["finalization"]["reason"] == "tool_action_budget"
    assert turn["finalization"]["attempted"] is True
    assert len(calls) == 2
    assert calls[1][1].function_tools == []
    assert turn["budget"]["turn"]["tool_calls"] == PER_TURN_TOOL_CALLS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("本轮向量请求预算已耗尽", "embedding_request_budget"),
        ("整批向量请求预算已耗尽", "embedding_request_budget"),
        ("本轮不同 Entry 读取预算已耗尽", "entry_read_budget"),
        ("本轮 Evidence 读取预算已耗尽", "evidence_read_budget"),
    ],
)
async def test_material_budget_stops_share_the_single_finalize_path(
    message: str, reason: str
) -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(_messages, info):
        calls.append(info)
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("stop_for_budget", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "已按现有材料收尾。"}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        instructions=SYSTEM_PROMPT,
        retries=0,
    )

    @agent.tool
    async def stop_for_budget(_ctx: RunContext[LoopDeps]) -> dict:
        raise BudgetExceeded(message)

    turn, _ = await run_turn(agent, state, "继续", [])

    assert turn["status"] == "not_executed"
    assert turn["solve_error"] == f"BudgetExceeded: {message}"
    assert turn["finalization"]["reason"] == reason
    assert turn["finalization"]["attempted"] is True
    assert len(calls) == 2
    assert calls[1].function_tools == []


@pytest.mark.asyncio
async def test_hard_input_limit_does_not_dispatch_finalize_when_input_still_cannot_fit() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(_messages, _info):
        calls.append(True)
        raise AssertionError("输入无法容纳时不应派发")

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 50_000)])]
    turn, _ = await run_turn(build_agent(model), state, "继续", history)

    assert turn["status"] == "not_executed"
    assert turn["solve_error"].startswith("BudgetExceeded: 压缩后对话上下文")
    assert turn["finalization"]["reason"] == "input_hard_limit"
    assert turn["finalization"]["status"] == "not_dispatched"
    assert turn["finalization"]["attempted"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_finalize_provider_failure_is_not_retried_and_keeps_verified_results() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    handle = state.store_result("statistic", {"value": 7}, "completed", "complete")
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        try:
            raise ConnectionError("provider connection refused")
        except ConnectionError as exc:
            raise RuntimeError("provider unavailable") from exc

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    await state.ledger.reserve_text()
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "partial_completed"
    assert turn["finalization"]["status"] == "failed"
    assert turn["finalization"]["attempted"] is True
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 2
    assert turn["usage"]["requests"] == 2
    assert turn["usage"]["input_tokens"] is None
    assert turn["usage"]["usage_complete"] is False
    assert any(block.get("handle") == handle for block in turn["blocks"])
    assert turn["error"] is None
    assert "provider unavailable" in turn["answer"]
    assert turn["error_details"]["category"] == "provider"
    assert turn["error_details"]["exception_chain"][0] == {
        "type": "RuntimeError",
        "message": "provider unavailable",
    }
    assert turn["error_details"]["exception_chain"][1] == {
        "type": "ConnectionError",
        "message": "provider connection refused",
    }


@pytest.mark.asyncio
async def test_finalize_timeout_is_not_retried_and_has_real_deadline(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr(loop_module, "FINALIZE_SECONDS", 0.01)
    state = _state()
    state.instrumentation.context_policy_enabled = True
    state.store_result("statistic", {"value": 5}, "completed", "complete")
    calls = []

    async def respond(messages, info):
        calls.append((messages, info))
        await asyncio.sleep(1)

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    await state.ledger.reserve_text()
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "partial_completed"
    assert turn["solve_error"] is None
    assert turn["finalization"]["status"] == "timed_out"
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 2
    assert turn["duration_ms"] < 500
    assert "总数：5" in turn["answer"]
    assert turn["error_details"]["category"] == "timeout"


@pytest.mark.asyncio
async def test_invalid_finalize_output_does_not_trigger_model_retry() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    handle = state.store_result("statistic", {"value": 9}, "completed", "complete")
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "statistic", "result_handle": "forged", "label": "总数"}
                        ]
                    },
                )
            ]
        )

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    await state.ledger.reserve_text()
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "partial_completed"
    assert turn["finalization"]["status"] == "invalid_output"
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 2
    assert any(block.get("handle") == handle for block in turn["blocks"])
    assert turn["error"] is None
    assert "模型收尾状态：invalid_output" in turn["answer"]
    assert turn["error_details"]["category"] == "reference_validation"
    assert "forged 不是当前轮结果" in turn["error_details"]["message"]
    assert turn["finalization"]["failure"]["category"] == "reference_validation"
    text_call = next(item for item in turn["model_calls"] if item["kind"] == "text")
    output_call = text_call["public_response"]["parts"][0]
    assert output_call["arguments"]["blocks"][0]["result_handle"] == "forged"


@pytest.mark.asyncio
async def test_missing_required_output_field_keeps_schema_diagnostic() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"needs_clarification": False})]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    await state.ledger.reserve_text()
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(build_agent(model), state, "请总结", history)

    assert turn["status"] == "partial_completed"
    assert len(calls) == 1
    assert turn["error_details"]["category"] == "schema_validation"
    assert turn["error"] is None
    errors = turn["error_details"]["validation"]["errors"]
    assert any(item["location"] == ["blocks"] and item["type"] == "missing" for item in errors)
    assert turn["finalization"]["failure"]["category"] == "schema_validation"
    assert turn["model_calls"][-1]["public_response"]["parts"][0]["arguments"] == {
        "needs_clarification": False
    }


@pytest.mark.asyncio
async def test_length_finish_reason_is_distinct_from_schema_failure() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True

    def respond(_messages, info):
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"needs_clarification": False})],
            finish_reason="length",
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    await state.ledger.reserve_text()
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(build_agent(model), state, "请总结", history)

    assert turn["status"] == "partial_completed"
    assert turn["error_details"]["category"] == "truncated"
    assert turn["error"] is None
    assert turn["model_calls"][-1]["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_public_response_diagnostic_excludes_hidden_thinking() -> None:
    state = _state()

    def respond(_messages, info):
        return ModelResponse(
            parts=[
                ThinkingPart("不得进入报告的隐藏推理"),
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "公开回答"}]},
                ),
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    turn, _ = await run_turn(build_agent(model), state, "回答", [])

    assert turn["status"] == "completed"
    recorded = json.dumps(turn["model_calls"], ensure_ascii=False)
    assert "公开回答" in recorded
    assert "不得进入报告的隐藏推理" not in recorded


@pytest.mark.asyncio
async def test_provider_shaped_estimate_records_components_scope_and_usage_error() -> None:
    state = _state()
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "完成"}]},
                )
            ],
            usage=RequestUsage(input_tokens=1_000, output_tokens=10),
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    turn, _ = await run_turn(build_agent(model), state, "统计一下", [])

    log = next(item for item in turn["model_calls"] if item["kind"] == "text")
    messages, info = calls[0]
    legacy_raw = json.dumps(
        to_jsonable_python(
            {"messages": messages, "request_parameters": info.model_request_parameters}
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    legacy_estimate = ceil(len(legacy_raw.encode("utf-8")) / 3)
    assert log["estimated_input_tokens"] < legacy_estimate
    assert log["estimate_components"]["version"] == INPUT_ESTIMATE_VERSION
    assert abs(
        log["estimate_components"]["instruction_utf8_bytes"]
        - len(info.instructions.encode("utf-8"))
    ) <= 2
    assert log["estimate_components"]["instruction_count"] == 2
    assert log["estimate_components"]["historical_system_count"] == 0
    instruction_payload = "\n".join(
        part.content for part in info.model_request_parameters.instruction_parts
    )
    assert log["estimate_components"]["instruction_sha256"] == hashlib.sha256(
        instruction_payload.encode("utf-8")
    ).hexdigest()
    assert log["request_scope"] == "dialogue_agent"
    assert log["actual_input_tokens"] == 1_000
    assert log["estimate_ratio"] == round(log["estimated_input_tokens"] / 1_000, 6)


@pytest.mark.asyncio
async def test_no_remaining_budget_does_not_dispatch_or_claim_finalize() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    state.ledger.batch_text_requests = BATCH_TEXT_REQUESTS
    state.store_result("statistic", {"value": 3}, "completed", "complete")
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        raise AssertionError("没有预算时不应派发")

    agent = build_agent(BudgetedModel(FunctionModel(respond), state.instrumentation))
    turn, _ = await run_turn(agent, state, "请总结", [])

    assert turn["status"] == "partial_completed"
    assert turn["finalization"]["status"] == "not_dispatched"
    assert turn["finalization"]["attempted"] is False
    assert turn["budget"]["batch_text_requests"] == BATCH_TEXT_REQUESTS
    assert calls == []
    assert "模型收尾状态：not_dispatched" in turn["answer"]
    assert any(item["kind"] == "text_not_dispatched" for item in turn["model_calls"])
    assert turn["error_details"]["category"] == "budget"


@pytest.mark.asyncio
async def test_cancellation_does_not_turn_into_normal_answer() -> None:
    import asyncio

    state = _state()
    state.instrumentation.context_policy_enabled = True
    calls = 0

    async def respond(messages, info):
        nonlocal calls
        del messages, info
        calls += 1
        await asyncio.sleep(10)

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    task = asyncio.create_task(run_turn(build_agent(model), state, "等待", []))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls <= 1
    assert state.instrumentation.finalize_attempted is False
    assert state.instrumentation.finalize_reason is None


async def _seed_finalize_material(state: LoopState) -> dict:
    from app.db.session import async_session_factory
    from app.models import (
        Attachment,
        Entry,
        EntrySourceEvidence,
        Node,
        Project,
        Source,
        User,
        Workspace,
        WorkspaceMember,
    )

    async with async_session_factory() as db:
        user = User(username=f"finalize-{id(state)}", password_hash="test")
        workspace = Workspace(name="收尾测试空间")
        db.add_all([user, workspace])
        await db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        project = Project(workspace_id=workspace.id, name="房子装修")
        db.add(project)
        await db.flush()
        node = Node(project_id=project.id, name="环保标准", position=0)
        source = Source(workspace_id=workspace.id, project_id=project.id, title="国标说明")
        db.add_all([node, source])
        await db.flush()
        attachment = Attachment(
            source_id=source.id,
            kind="text",
            position=0,
            text_content="ENF 是国标甲醛释放限量等级，检测条件仍需查阅标准原文。",
        )
        entry = Entry(
            project_id=project.id,
            node_id=node.id,
            title="甲醛环保等级：国标ENF级",
            content="ENF 正文：该记录概括了甲醛释放限量等级。",
            main_type="knowledge",
        )
        db.add_all([attachment, entry])
        await db.flush()
        relation = EntrySourceEvidence(
            entry_id=entry.id,
            source_id=source.id,
            attachment_id=attachment.id,
            quote="ENF 是国标甲醛释放限量等级",
        )
        db.add(relation)
        await db.commit()
        for row in (user, workspace, project, node, source, attachment, entry, relation):
            await db.refresh(row)
        seeded = {
            "user_id": int(user.id),
            "workspace_id": int(workspace.id),
            "entry_id": int(entry.id),
            "source_id": int(source.id),
            "attachment_id": int(attachment.id),
            "relation_id": int(relation.id),
            "title": entry.title,
            "content": entry.content,
            "source_title": source.title,
            "quote": relation.quote,
        }

    state.user_id = seeded["user_id"]
    state.workspace_id = seeded["workspace_id"]
    entry_id = seeded["entry_id"]
    source_id = seeded["source_id"]
    list_handle = state.store_result(
        "list",
        {
            "items": [
                {
                    "entry_id": entry_id,
                    "title": seeded["title"],
                    "project_name": "房子装修",
                    "relevance_level": "direct",
                }
            ]
        },
        "completed",
        "limited",
        semantics={"relevance_scope": "direct", "project_scope": "all"},
    )
    entry_handle = state.store_result(
        "entries",
        {
            "items": [
                {
                    "entry_id": entry_id,
                    "title": seeded["title"],
                    "content": seeded["content"],
                    "project_name": "房子装修",
                    "sources": [
                        {
                            "source_id": source_id,
                            "source_title": seeded["source_title"],
                            "attachment_id": seeded["attachment_id"],
                            "quote": seeded["quote"],
                        }
                    ],
                }
            ]
        },
        "completed",
        "limited",
    )
    evidence_handle = "ev-finalize-enf"
    evidence_item = {
        "entry_id": entry_id,
        "source_id": source_id,
        "source_title": seeded["source_title"],
        "attachment_id": seeded["attachment_id"],
        "evidence_handle": evidence_handle,
        "quote": "ENF 是国标甲醛释放限量等级",
        "citable": True,
        "status": "ok",
    }
    evidence_result = state.store_result(
        "evidence", {"items": [evidence_item]}, "completed", "limited"
    )
    state.authorized_entry_ids.add(entry_id)
    state.read_entry_ids.add(entry_id)
    state.evidence[evidence_handle] = evidence_item
    state.current_evidence.add(evidence_handle)
    for tool, handle in (
        ("select_relevant_entries", list_handle),
        ("read_entries", entry_handle),
        ("read_evidence", evidence_result),
    ):
        state.tool_events.append(
            {
                "tool": tool,
                "result_handle": handle,
                "status": "completed",
                "completeness": "limited",
                "params": {},
                "turn_index": state.turn_index,
            }
        )
    return {**seeded, "evidence_handle": evidence_handle, "list_handle": list_handle}


def test_history_uses_bounded_structured_summaries_and_keeps_all_user_messages() -> None:
    state = _state()
    for index in range(8):
        state.turn_index = index + 1
        state.remember_turn(
            f"用户原话 {index}",
            "不应使用的渲染答案" * 1_000,
            [],
            blocks=[
                {"kind": "text", "text": f"结论 {index}" + "甲" * 3_000},
                {"kind": "entry", "entry_id": index + 1, "content": "正文" * 3_000},
                {"kind": "evidence", "source_id": index + 1, "text": "来源" * 3_000},
                {"kind": "text", "text": f"后续建议 {index}"},
            ],
        )

    history = build_compact_history(state)
    serialized = str(history)

    assert all(f"用户原话 {index}" in serialized for index in range(8))
    assert "正文正文" not in serialized
    assert "来源来源" not in serialized
    assert "后续建议 7" in serialized
    assert loop_module.estimate_input_tokens(history) <= HISTORY_INPUT_TOKENS_TARGET
    assert all(
        len(turn["answer_summary"]["narrative"]) <= HISTORY_ANSWER_CHARS_PER_TURN + 50
        for turn in state.history_turns
    )


def test_four_turn_ordinal_context_keeps_enf_as_first_authorized_entry() -> None:
    state = _state()
    handle = state.store_result(
        "list",
        {
            "items": [
                {"entry_id": 7, "title": "甲醛环保等级：国标ENF级"},
                {"entry_id": 8, "title": "甲醛环保等级：美标NAF级"},
            ]
        },
        "completed",
        "limited",
        semantics={"relevance_scope": "direct"},
    )
    for index, message in enumerate(
        (
            "甲醛是什么",
            "好的，帮我解释这些等级标准的具体内容",
            "第二个等级信息可信吗",
            "那第一条呢，可信吗",
        ),
        1,
    ):
        state.turn_index = index
        state.remember_turn(message, f"第 {index} 轮结论", [])

    assert list_position_entry_id(state, handle, 1) == 7
    assert list_position_entry_id(state, handle, 2) == 8
    assert all(message in str(build_compact_history(state)) for message in (
        "甲醛是什么",
        "好的，帮我解释这些等级标准的具体内容",
        "第二个等级信息可信吗",
        "那第一条呢，可信吗",
    ))


@pytest.mark.asyncio
async def test_subsequent_soft_limit_finalizes_even_without_successful_material() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    await state.ledger.reserve_text()
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "没有已确认材料。"}]},
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(
        build_agent(model), state, "继续查询", history, build_finalizer_agent(model)
    )

    assert len(calls) == 1
    assert calls[0][1].function_tools == []
    assert turn["finalization"]["reason"] == "input_soft_limit"
    assert turn["status"] == "completed"
    assert turn["completion"]["continuation"] is None


@pytest.mark.asyncio
async def test_finalize_tool_attempt_is_blocked_and_resume_only_retries_answer() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await _seed_finalize_material(state)
    await state.ledger.reserve_text()
    provider_calls = []

    def respond(messages, info):
        provider_calls.append((messages, info))
        if len(provider_calls) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "read_evidence",
                        {"entry_id": seeded["entry_id"], "source_ids": [seeded["source_id"]]},
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": (
                                    "这两条来源能支持该记录来自现有材料，但不足以证明已经完成"
                                    "官方交叉验证。"
                                ),
                            },
                            {
                                "kind": "evidence",
                                "evidence_handle": seeded["evidence_handle"],
                                "note": "已取得来源",
                            },
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    agent = build_agent(model)
    finalizer = build_finalizer_agent(model)
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    events_before = len(state.tool_events)

    failed, history = await run_turn(
        agent, state, "那第一条呢，可信吗", history, finalizer
    )

    assert failed["status"] == "partial_completed"
    assert failed["finalization"]["status"] == "tool_attempted"
    assert failed["completion"]["reason_code"] == "finalize_tool_attempted"
    assert failed["completion"]["continuation"]["task_type"] == "finalize_answer"
    assert "content" not in json.dumps(
        failed["completion"]["continuation"], ensure_ascii=False
    )
    assert "来源已取得，可信度分析尚未完成" in failed["answer"]
    assert len(state.tool_events) == events_before
    assert len(provider_calls) == 1
    assert provider_calls[0][1].function_tools == []

    state.begin_turn(999, "继续")
    completed, _ = await run_turn(agent, state, "继续", history, finalizer)

    assert completed["status"] == "completed"
    assert completed["tool_calls"] == []
    assert completed["context"]["continuation_mode"] == "finalize_only"
    assert "不足以证明已经完成官方交叉验证" in completed["answer"]
    assert state.continuation is None
    assert len(state.tool_events) == events_before
    assert len(provider_calls) == 2


@pytest.mark.asyncio
async def test_finalize_continuation_rejects_forgery_permission_and_material_changes() -> None:
    from sqlalchemy import delete, update

    from app.db.session import async_session_factory
    from app.models import Entry, EntrySourceEvidence, WorkspaceMember

    forged_state = _state()
    forged = await _seed_finalize_material(forged_state)
    continuation = await _create_finalize_continuation(
        forged_state, "那第一条呢，可信吗", []
    )
    valid, reason = await _validate_finalize_continuation(forged_state, continuation)
    assert valid is True and reason is None
    public_snapshot = json.dumps(continuation.snapshot(), ensure_ascii=False)
    assert forged["content"] not in public_snapshot
    assert forged["quote"] not in public_snapshot

    fake_handle = deepcopy(continuation)
    fake_handle.recoverable_material["record_fingerprints"]["forged"] = "bad"
    valid, reason = await _validate_finalize_continuation(forged_state, fake_handle)
    assert valid is False and "句柄" in reason

    changed_state = _state()
    changed = await _seed_finalize_material(changed_state)
    changed_continuation = await _create_finalize_continuation(
        changed_state, "那第一条呢，可信吗", []
    )
    async with async_session_factory() as db:
        await db.execute(
            update(Entry)
            .where(Entry.id == changed["entry_id"])
            .values(content="正文版本已经变化")
        )
        await db.commit()
    valid, reason = await _validate_finalize_continuation(
        changed_state, changed_continuation
    )
    assert valid is False and "版本" in reason

    revoked_state = _state()
    revoked = await _seed_finalize_material(revoked_state)
    revoked_continuation = await _create_finalize_continuation(
        revoked_state, "那第一条呢，可信吗", []
    )
    async with async_session_factory() as db:
        await db.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == revoked["workspace_id"],
                WorkspaceMember.user_id == revoked["user_id"],
            )
        )
        await db.commit()
    valid, reason = await _validate_finalize_continuation(
        revoked_state, revoked_continuation
    )
    assert valid is False and "Workspace" in reason

    relation_state = _state()
    relation = await _seed_finalize_material(relation_state)
    relation_continuation = await _create_finalize_continuation(
        relation_state, "那第一条呢，可信吗", []
    )
    async with async_session_factory() as db:
        await db.execute(
            delete(EntrySourceEvidence).where(
                EntrySourceEvidence.id == relation["relation_id"]
            )
        )
        await db.commit()
    valid, reason = await _validate_finalize_continuation(
        relation_state, relation_continuation
    )
    assert valid is False and "来源关系" in reason


@pytest.mark.asyncio
async def test_invalid_continuation_does_not_call_model_and_topic_switch_clears_it() -> None:
    from sqlalchemy import delete

    from app.db.session import async_session_factory
    from app.models import Entry

    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await _seed_finalize_material(state)
    continuation = await _create_finalize_continuation(
        state, "那第一条呢，可信吗", []
    )
    state.continuation = continuation
    state.begin_turn(1_001, "换个话题，聊聊复习方法")
    assert state.active_continuation is None
    assert state.continuation is None

    state.continuation = continuation
    async with async_session_factory() as db:
        await db.execute(delete(Entry).where(Entry.id == seeded["entry_id"]))
        await db.commit()
    state.begin_turn(1_002, "继续")
    calls = []

    def respond(_messages, _info):
        calls.append(True)
        raise AssertionError("材料失效时不得派发模型")

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    turn, _ = await run_turn(
        build_agent(model), state, "继续", [], build_finalizer_agent(model)
    )

    assert turn["status"] == "not_executed"
    assert turn["completion"]["reason_code"] == "continuation_material_invalid"
    assert "重新核验" in turn["answer"]
    assert calls == []
    assert state.continuation is None


def test_fourth_batch_keeps_all_frozen_budget_values() -> None:
    assert INPUT_ESTIMATE_SOFT_LIMIT == 9_000
    assert MODEL_INPUT_TOKENS_LIMIT == 12_000
    assert PER_TURN_TEXT_REQUESTS == 12
    assert PER_TURN_TOOL_CALLS == 8
    assert PER_TURN_ENTRY_READS == 30
    assert PER_TURN_EVIDENCE_READS == 20
    assert PER_TURN_SECONDS == 120.0
    assert BATCH_TEXT_REQUESTS == 192
    assert BATCH_EMBEDDING_REQUESTS == 64
