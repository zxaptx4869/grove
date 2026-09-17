"""统一对话循环实验的无模型边界与停止条件测试。"""

import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from math import ceil
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
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
    _resource_summary,
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
    ContinuationState,
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
    InputEstimate,
    Instrumentation,
    InvocationLog,
    _normalize_legacy_answer_response,
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
    _evidence_requested,
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
    select_editing_context,
)
from evals.dialogue_loop.report import evaluate, evaluation_plan, sanitize


def test_evidence_is_requested_only_for_source_or_conflict_questions() -> None:
    assert _evidence_requested("第二个等级信息可信吗") is True
    assert _evidence_requested("请给出第一条的来源原文") is True
    assert _evidence_requested("第二个 Entry 的具体内容是什么") is False
    assert _evidence_requested("好的，帮我解释这个记录") is False


def test_invalid_json_wrapper_only_accepts_strict_dialogue_answer() -> None:
    valid = json.dumps(
        {"blocks": [{"kind": "text", "text": "可严格解析的回答。"}]},
        ensure_ascii=False,
    )
    response = ModelResponse(
        parts=[ToolCallPart("final_result", {"INVALID_JSON": valid})]
    )

    normalized, compatibility, _ = _normalize_legacy_answer_response(
        response, ["final_result"]
    )

    assert normalized.parts[0].args_as_dict() == {
        "blocks": [{"kind": "text", "text": "可严格解析的回答。"}],
        "needs_clarification": False,
    }
    assert compatibility == {
        "kind": "strict_invalid_json_envelope",
        "status": "normalized",
    }


def test_real_damaged_invalid_json_is_not_repaired_or_extracted() -> None:
    raw = (
        Path(__file__).parent / "fixtures" / "dialogue-invalid-json-six-point.txt"
    ).read_text(encoding="utf-8").rstrip("\n")
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)
    response = ModelResponse(
        parts=[ToolCallPart("final_result", {"INVALID_JSON": raw})]
    )

    normalized, compatibility, claims = _normalize_legacy_answer_response(
        response, ["final_result"]
    )

    assert normalized is response
    assert compatibility is None
    assert claims == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"answer_summary": {"narrative": "未知旧结构"}},
        {"blocks": [{"kind": "unknown", "text": "未知块"}]},
        {"blocks": [{"kind": "text", "text": "多余字段"}], "extra": True},
    ],
)
def test_invalid_json_wrapper_rejects_unknown_contracts(payload: dict) -> None:
    response = ModelResponse(
        parts=[
            ToolCallPart(
                "final_result",
                {"INVALID_JSON": json.dumps(payload, ensure_ascii=False)},
            )
        ]
    )

    normalized, compatibility, claims = _normalize_legacy_answer_response(
        response, ["final_result"]
    )

    assert normalized is response
    assert compatibility is None
    assert claims == {}


def test_strict_invalid_json_wrapper_does_not_authorize_unknown_reference() -> None:
    response = ModelResponse(
        parts=[
            ToolCallPart(
                "final_result",
                {
                    "INVALID_JSON": json.dumps(
                        {
                            "blocks": [
                                {
                                    "kind": "evidence",
                                    "evidence_handle": "ev-forged",
                                }
                            ]
                        }
                    )
                },
            )
        ]
    )

    normalized, compatibility, _ = _normalize_legacy_answer_response(
        response, ["final_result"]
    )
    answer = DialogueAnswer.model_validate(normalized.parts[0].args_as_dict())

    assert compatibility is not None
    assert output_errors(answer, _state()) == ["ev-forged 不是当前轮核验 Evidence"]


def test_skipped_evidence_event_does_not_make_turn_incomplete() -> None:
    state = _state()
    event = {
        "tool": "read_evidence",
        "status": "not_executed",
        "reason_code": "evidence_not_required",
        "error": "普通回答无需来源核验，已跳过 Evidence 读取",
    }
    assert _stop_from_events(state, [event]) is None


def test_projects_result_handle_is_rendered_as_project_list() -> None:
    state = _state()
    handle = state.store_result(
        "projects",
        {"projects": [{"id": 1, "name": "项目甲", "status": "active"}]},
        "completed",
        "complete",
    )
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "list", "result_handle": handle, "label": "项目"}]}
    )
    assert output_errors(answer, state) == []
    text, blocks = render_answer(answer, state)
    assert "项目甲" in text
    assert blocks[0]["items"][0]["name"] == "项目甲"


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
        "按你的分析，帮我把第一条的知识补充一下，发给我",
        "请把第二条完善一下，给我看看",
        "结合前面的结论优化这个知识，给我一版",
        "就输出你补充后的知识内容就行，其他的都不用",
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
        "直接帮我更新知识库，然后发给我",
        "直接更新知识库并把结果输出给我审核",
    ],
)
def test_direct_write_wording_is_not_treated_as_candidate_revision(message: str) -> None:
    assert _candidate_revision_requested(message) is False


def test_deepseek_v4_dialogue_agents_disable_default_thinking() -> None:
    """V4 求解与收尾显式关闭默认思考，其他模型不接收专用请求体。"""

    v4_model = FunctionModel(lambda _messages, _info: None, model_name="deepseek-v4-flash")
    for agent in (build_agent(v4_model), build_finalizer_agent(v4_model)):
        assert agent.model_settings["extra_body"] == {
            "thinking": {"type": "disabled"}
        }

    other_model = FunctionModel(lambda _messages, _info: None, model_name="other-model")
    assert "extra_body" not in build_agent(other_model).model_settings
    assert "extra_body" not in build_finalizer_agent(other_model).model_settings


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


def test_deterministic_fallback_never_exceeds_answer_block_contract() -> None:
    """Run 794 同类材料超过展示容量时，失败兜底自身仍必须可校验。"""
    state = _state()
    for index in range(11):
        state.store_result(
            "statistic",
            {"value": index + 1},
            "completed",
            "complete",
        )
    state.stop(
        StopState(
            status="failed",
            reason_code="output_validation_failed",
            reason="模型输出未通过结构校验",
            incomplete_steps=["候选整理尚未完成"],
            can_continue=False,
        )
    )

    text, blocks = _verified_failure_output(state)

    assert len(blocks) == 12
    assert blocks[0]["kind"] == "text"
    assert blocks[-1]["kind"] == "insufficient"
    assert "候选整理尚未完成" in text


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
    assert "列出两条" in str(history)
    returned = next(iter(json.loads(history[0].parts[0].content).values()))[0]
    assert [item["entry_id"] for item in returned["ordered_items"]] == [91, 17]
    assert "正文正文" not in str(returned)
    assert not any(isinstance(part, ToolCallPart) for m in history for part in m.parts)
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
    assert "ordered_items" in str(messages)
    assert not any(isinstance(part, ToolReturnPart) for m in messages for part in m.parts)


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
        "按你的分析，帮我把第一条的知识补充一下，发给我",
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
async def test_normal_agent_normalizes_legacy_candidate_envelope_without_retry() -> None:
    """普通 Agent 首次收到旧式候选稿外壳时不再触发格式重试或 finalize。"""

    message = "按你的分析，帮我把第一条的知识补充一下，发给我"
    state = _state()
    state.instrumentation.context_policy_enabled = True
    state.begin_turn(5, message)
    calls = 0

    def respond(_messages, _info):
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[
                TextPart(
                    json.dumps(
                        {
                            "answer_summary": {
                                "narrative": (
                                    "以下为候选修改稿，尚未写入知识库。\n\n"
                                    "原记录要点：第一条记录讲的是甲醛环保等级。\n\n"
                                    "建议补充：补充测试方法和认证核验边界。\n\n"
                                    "修改后候选版本：应同时核对检测方法、认证证书和检测报告。\n\n"
                                    "来源边界说明：新增内容没有对应的知识库来源原文。"
                                ),
                                "references": [],
                            },
                            "completion": {
                                "status": "completed",
                                "reason_code": "completed",
                                "reason": "任务已完整完成",
                                "incomplete_steps": [],
                                "can_continue": False,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    turn, _ = await run_turn(build_agent(model), state, message, [])

    assert turn["status"] == "completed"
    assert calls == 1
    assert turn["finalization"]["attempted"] is False
    assert turn["tool_calls"] == []
    assert "尚未写入知识库" in turn["answer"]
    assert state.instrumentation.finalize_compatibility is None


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


def test_candidate_revision_output_keeps_hard_boundaries_without_fixed_headings() -> None:
    """候选稿只校验写入、内容区分和来源边界，不强制固定章节标题。"""

    state = _state()
    state.begin_turn(5, "帮我完善一下这条知识")
    incomplete = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "已经帮你更新好了。"}]}
    )

    errors = output_errors(incomplete, state)

    assert errors
    assert any("未写入状态" in error for error in errors)
    assert any("原记录与现有内容" in error for error in errors)
    assert any("新增建议" in error for error in errors)
    assert any("来源边界" in error for error in errors)

    natural = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": (
                        "现有内容主要说明墙面材料的选择原则。\n"
                        "在此基础上，可以增加环保等级和维护成本的判断。\n"
                        "这只是候选修改稿，尚未写入正式记录；新增分析不等于来源原文。"
                    ),
                }
            ]
        }
    )
    assert output_errors(natural, state) == []

    written = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "已经帮你更新好了，尚未写入正式记录。"}]}
    )
    assert any("不得声称已经写入" in error for error in output_errors(written, state))


def test_run_801_tone_only_candidate_preserves_measurement_dimension() -> None:
    """真实 Run 801 候选结构合法，仍不能改变 20cm 的尺寸含义。"""

    state = _state()
    state.begin_turn(801, "把这条记录改得更加口语化一些")
    state.editing_active = True
    state.editing_purpose = "candidate"
    state.editing_context = loop_module.EditingContext(
        entry={
            "entry_id": 35,
            "title": "洗碗机安装",
            "content": (
                "洗碗机安装要求：1)紧挨水槽安装；2)水电提前留到旁边柜子的"
                "侧面或后面；3)走线走管整齐方便检修。需预留20cm防倒灌空间和角阀。"
                "补充：单独拉一根10A电线；进水口装角阀方便关水；排水管要比洗碗机"
                "底部高20cm防止脏水倒灌。"
            ),
            "sources": [],
        },
        validation_refs={},
    )
    drifted_text = (
        Path(__file__).parent
        / "fixtures"
        / "dialogue-run-801-drifted-candidate.txt"
    ).read_text(encoding="utf-8")
    drifted = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": drifted_text,
                }
            ]
        }
    )

    errors = output_errors(drifted, state)

    assert any("数量所属的尺寸含义" in error for error in errors)


def test_tone_only_candidate_preserves_original_uncertainty() -> None:
    state = _state()
    state.begin_turn(801, "只改语气，换个更口语的说法")
    state.editing_active = True
    state.editing_purpose = "candidate"
    state.editing_context = loop_module.EditingContext(
        entry={
            "entry_id": 36,
            "title": "安装建议",
            "content": "建议预留约20cm空间，具体以现场条件为准。",
            "sources": [],
        },
        validation_refs={},
    )
    strengthened = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": (
                        "现有记录改成口语说法：必须预留20公分空间。\n"
                        "这是模型整理的候选稿，尚未写入正式 Entry；"
                        "没有新增 Source 原文。"
                    ),
                }
            ]
        }
    )

    errors = output_errors(strengthened, state)

    assert any("程度或不确定性" in error for error in errors)


def test_candidate_failure_summary_omits_historical_results_and_duplicate_entry() -> None:
    """候选失败只展示当前草稿与缺口，历史恢复材料不进入摘要。"""

    state = _state()
    state.begin_turn(801, "把这条记录改得更加口语化一些")
    state.editing_active = True
    state.editing_purpose = "candidate"
    state.editing_context = loop_module.EditingContext(
        entry={"entry_id": 35, "title": "当前记录", "content": "原正文"},
        validation_refs={},
    )
    state.candidate_draft = {
        "blocks": [{"kind": "text", "text": "当前候选正文"}],
        "needs_clarification": False,
    }
    state.candidate_draft_errors = ["候选修改稿缺少：来源边界"]
    state.store_result(
        "projects",
        {"projects": [{"id": 9, "name": "旧项目"}]},
        "completed",
        "complete",
    )
    state.store_result(
        "entries",
        {"items": [{"entry_id": 35, "title": "当前记录", "content": "重复原正文"}]},
        "completed",
        "limited",
    )
    continuation = ContinuationState(
        task_type="candidate_draft",
        tool_name="finalize_answer",
        scope={"answer_basis": "candidate_draft"},
        recoverable_material={"candidate_draft": state.candidate_draft},
    )
    stop = StopState(
        status="partial_completed",
        reason_code="finalize_output_invalid",
        reason="候选修改稿缺少：来源边界",
        incomplete_steps=["候选修改稿缺少：来源边界"],
        can_continue=True,
        continuation=continuation,
    )

    text, blocks = _verified_failure_output(state, stop)

    assert text.count("当前候选正文") == 1
    assert "旧项目" not in text
    assert "重复原正文" not in text
    assert "来源边界" in text
    assert len(blocks) <= 4


@pytest.mark.parametrize(
    "boundary",
    [
        "来源边界说明：补充分析并非来自该来源原文。",
        "来源边界说明：补充建议没有对应的知识库来源原文。",
        "来源边界说明：本轮没有来源原文，补充内容不能视为来源转述。",
        "来源边界说明：本轮未取得来源原文，补充内容仅供审核。",
    ],
)
def test_candidate_revision_accepts_equivalent_source_boundary_wording(
    boundary: str,
) -> None:
    """等价来源边界说明不能被固定文案校验误拒绝。"""

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
                        + boundary
                    ),
                }
            ]
        }
    )

    assert output_errors(answer, state) == []


def test_content_only_candidate_accepts_one_text_and_rejects_evidence_block() -> None:
    """精简候选稿只保留正文和必要边界，不允许 Evidence 原文展开。"""

    state = _state()
    state.begin_turn(5, "就输出你补充后的知识内容就行，其他的都不用")
    candidate_text = (
        "国标 ENF 级用于描述人造板甲醛释放量等级。\n"
        "说明：这是候选内容，尚未写入知识库；模型补充不属于原始来源原文。"
    )
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": candidate_text}]}
    )

    assert output_errors(answer, state) == []

    state.current_evidence.add("ev-current")
    state.evidence["ev-current"] = {
        "entry_id": 7,
        "source_id": 66,
        "source_title": "来源",
        "quote": "来源原文",
    }
    with_evidence = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": candidate_text},
                {"kind": "evidence", "evidence_handle": "ev-current"},
            ]
        }
    )

    assert any(
        "精简候选稿只能包含一个文本块" in item
        for item in output_errors(with_evidence, state)
    )


def test_text_block_note_is_ignored_without_changing_rendered_content() -> None:
    """Provider 多出的无害 note 不进入展示、快照或引用授权。"""

    state = _state()
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": "合法正文", "note": "不展示的模型备注"}
            ]
        }
    )

    text, blocks = render_answer(answer, state)

    assert text == "合法正文"
    assert blocks == [{"kind": "text", "text": "合法正文"}]
    assert "note" not in answer.model_dump(mode="json")["blocks"][0]


@pytest.mark.asyncio
async def test_finalizer_accepts_harmless_text_note_without_second_request() -> None:
    """真实收尾路径可忽略 text.note，且仍只使用一次模型请求。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    provider_calls = 0

    def respond(_messages, info):
        nonlocal provider_calls
        provider_calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": "这是合法收尾正文。",
                                "note": "模型添加但不参与展示的备注",
                            }
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
    )
    result = await loop_module._finalize_once(
        build_finalizer_agent(model),
        state,
        "请完成回答",
        [],
        [],
        "input_soft_limit",
    )
    text, blocks = render_answer(result.output, state)

    assert provider_calls == 1
    assert text == "这是合法收尾正文。"
    assert blocks == [{"kind": "text", "text": "这是合法收尾正文。"}]
    assert state.instrumentation.finalize_response_received is True


@pytest.mark.asyncio
async def test_finalizer_normalizes_observed_legacy_envelope_once() -> None:
    """真实 F4 星旧外壳在引用仍合法时一次转换为标准回答。"""

    state = _state()
    seeded = await _seed_finalize_material(state)
    state.instrumentation.context_policy_enabled = True
    provider_calls = 0
    tool_events_before = len(state.tool_events)

    def respond(_messages, _info):
        nonlocal provider_calls
        provider_calls += 1
        return ModelResponse(
            parts=[
                TextPart(
                    json.dumps(
                        {
                            "answer_summary": {
                                "narrative": "第二条讲的是日本 F4 星级及其认证边界。",
                                "references": [
                                    {
                                        "kind": "evidence",
                                        "handle": "ev-finalize-enf",
                                        "entry_id": seeded["entry_id"],
                                        "source_id": seeded["source_id"],
                                    }
                                ],
                            },
                            "completion": {
                                "status": "completed",
                                "reason_code": "completed",
                                "reason": "任务已完整完成",
                                "incomplete_steps": [],
                                "can_continue": False,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    result = await loop_module._finalize_once(
        build_finalizer_agent(model),
        state,
        "第二条呢，讲的什么",
        [],
        [],
        "input_soft_limit",
    )
    text, blocks = render_answer(result.output, state)

    assert provider_calls == 1
    assert len(state.tool_events) == tool_events_before
    assert "第二条讲的是日本 F4 星级" in text
    assert [block["kind"] for block in blocks] == ["text", "evidence"]
    assert state.instrumentation.finalize_compatibility == {
        "kind": "legacy_answer_summary_envelope",
        "status": "normalized",
        "discarded_fields": ["completion"],
        "reference_count": 1,
    }
    assert state.instrumentation.logs[-1].response_compatibility == (
        state.instrumentation.finalize_compatibility
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_kind", ["relationship", "unknown_top_level"])
async def test_finalizer_does_not_normalize_unsafe_or_unknown_envelope(
    invalid_kind: str,
) -> None:
    """受限兼容不接受来源关系不一致或未知顶层结构。"""

    state = _state()
    seeded = await _seed_finalize_material(state)
    state.instrumentation.context_policy_enabled = True
    provider_calls = 0
    tool_events_before = len(state.tool_events)
    payload = {
        "answer_summary": {
            "narrative": "这是结构完整但引用非法的回答。",
            "references": [
                {
                    "kind": "evidence",
                    "handle": "ev-finalize-enf",
                    "entry_id": seeded["entry_id"],
                    "source_id": seeded["source_id"] + 1,
                }
            ],
        },
        "completion": {
            "status": "completed",
            "reason_code": "completed",
            "reason": "模型自报完成",
            "incomplete_steps": [],
            "can_continue": False,
        },
    }
    if invalid_kind == "unknown_top_level":
        payload["unexpected"] = True

    def respond(_messages, _info):
        nonlocal provider_calls
        provider_calls += 1
        return ModelResponse(
            parts=[TextPart(json.dumps(payload, ensure_ascii=False))]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    with pytest.raises(UnexpectedModelBehavior):
        await loop_module._finalize_once(
            build_finalizer_agent(model),
            state,
            "请完成回答",
            [],
            [],
            "input_soft_limit",
        )

    assert provider_calls == 1
    assert len(state.tool_events) == tool_events_before
    assert state.instrumentation.finalize_compatibility is None
    assert state.instrumentation.finalize_status == "invalid_output"
    if invalid_kind == "relationship":
        assert state.instrumentation.finalize_failure["category"] == (
            "reference_validation"
        )


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
            "title": "窗帘安装前必须清洗",
            "project_name": "房子装修",
            "excerpt": "安装前清洗窗帘，能去除大部分甲醛和灰尘。",
        },
        {
            "entry_id": 22,
            "title": "墙面材料选乳胶漆优于壁纸/墙布",
            "project_name": "房子装修",
            "excerpt": "墙面材料选环保乳胶漆，避免胶水带来的甲醛释放。",
        },
        {
            "entry_id": 33,
            "title": "甲醛环保等级：国标ENF级",
            "project_name": "房子装修",
            "excerpt": "ENF 是板材环保等级，说明甲醛释放限量。",
        },
        {
            "entry_id": 44,
            "title": "客厅灯光搭配",
            "project_name": "房子装修",
            "excerpt": "色温与照度的搭配建议。",
        },
    ]

    async def fake_dispatch(ctx, tool_name, params, kind, **kwargs):
        dispatched.append((tool_name, params, kwargs))
        if tool_name == "query_entries":
            payload = {"items": candidates, "returned_count": 4, "has_more": False}
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
                "result_summary": {"returned_count": 4, "has_more": False},
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
                    "title": "窗帘安装前必须清洗",
                    "content": "安装前清洗窗帘，能去除大部分甲醛和灰尘。",
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
                            "query": "除甲醛",
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
                                {
                                    "entry_id": 11,
                                    "relevance": "direct",
                                    "reason": "正文明确描述去除甲醛的处理动作",
                                },
                                {
                                    "entry_id": 22,
                                    "relevance": "indirect",
                                    "reason": "只讨论装修选材和可能的甲醛影响",
                                },
                                {
                                    "entry_id": 33,
                                    "relevance": "indirect",
                                    "reason": "只讨论材料环保等级，不是除甲醛处理动作",
                                },
                                {
                                    "entry_id": 44,
                                    "relevance": "unrelated",
                                    "reason": "只有装修场景相似，正文与甲醛处理无关",
                                },
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
        build_agent(FunctionModel(respond)), state, "房子装修项目中，有除甲醛的知识吗", []
    )

    assert turn["status"] == "completed", turn
    list_block = next(block for block in turn["blocks"] if block["kind"] == "list")
    assert [item["entry_id"] for item in list_block["items"]] == [11]
    assert list_block["semantics"]["classification_counts"] == {
        "direct": 1,
        "indirect": 2,
        "unrelated": 1,
    }
    assert [item[1] for item in dispatched if item[0] == "read_entries"] == [
        {"entry_ids": [11]}
    ]
    selected_handle = next(
        handle
        for handle in state.current_handles
        if state.result_sets[handle].semantics.get("relevance_scope") == "direct"
    )
    assert list_position_entry_id(state, selected_handle, 1) == 11
    with pytest.raises(ValueError):
        list_position_entry_id(state, selected_handle, 2)
    assert "窗帘安装前必须清洗" in turn["answer"]
    assert "墙面材料选乳胶漆" not in turn["answer"]
    assert "甲醛环保等级" not in turn["answer"]
    assert state.authorized_entry_ids == {11}
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


def test_successful_read_supersedes_only_matching_temporary_denial() -> None:
    state = _state()
    temporary_denial = {
        "tool": "read_entries",
        "shared_tool": "read_entries",
        "status": "denied",
        "params": {"entry_ids": [35, 18, 84]},
        "reason_code": "access_denied",
        "error": "部分 Entry 越权或不可用",
    }
    successful_read = {
        "tool": "read_entries",
        "shared_tool": "read_entries",
        "status": "completed",
        "params": {"entry_ids": [35, 18, 84]},
        "result_summary": {"returned_count": 3},
    }

    assert _stop_from_events(state, [temporary_denial, successful_read]) is None

    real_denial = _stop_from_events(
        state,
        [
            temporary_denial,
            {
                **successful_read,
                "params": {"entry_ids": [35, 18]},
                "result_summary": {"returned_count": 2},
            },
        ],
    )
    assert real_denial is not None
    assert real_denial.status == "denied"


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
    returned = next(iter(json.loads(history[0].parts[0].content).values()))[0]
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


def test_rehearsal_mode_uses_only_unified_loop() -> None:
    assert parser().parse_args(["--rehearsal"]).rehearsal is True
    with pytest.raises(SystemExit):
        parser().parse_args(["--rehearsal", "--compare"])


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
    result = evaluate([{"scenario": "A", "turns": turns}], oracle)
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
        [{"scenario": "A", "turns": [turn]}],
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
        [{"scenario": "A", "turns": [count, swapped, count, swapped]}],
        oracle,
    )
    assert result["turns"][1]["status"] == "fail"
    assert set(result["turns"][1]["reasons"][0]) >= {"甲", "乙"}


def test_list_reference_uses_actual_displayed_third_item() -> None:
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
    result = evaluate([{"scenario": "C", "turns": turns}], oracle)
    assert result["turns"][0]["status"] == "fail"
    assert result["turns"][1]["status"] == "review"
    assert result["turns"][3]["status"] == "review"


def test_denied_tool_request_is_not_reported_as_shared_tool_failure() -> None:
    results = [
        {
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
        {"turns": [{"scenario": "A", "status": "pass"}]},
        None,
    )
    assert "未识别到" in conclusion["shared_tools"]
    assert "边界拒绝 1 次" in conclusion["architecture"]


def test_resource_summary_keeps_unknown_cost() -> None:
    results = [
        {
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
    summary = _resource_summary(results)
    assert summary["text_requests"] == 1
    assert summary["input_tokens"] == 10
    assert summary["cost_available"] is False


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

    result = _rehearsal_scenario("A", checkpoint)
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
    assert plan["maximum_user_messages"] == 20
    assert plan["status"] == "active_unified_loop"
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
    ) <= 2 * (log["estimate_components"]["instruction_count"] - 1)
    assert log["estimate_components"]["instruction_count"] == len(
        info.model_request_parameters.instruction_parts
    )
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
        user = User(username=f"finalize-{uuid4().hex[:16]}", password_hash="test")
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
            "project_id": int(project.id),
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


def test_history_keeps_full_record_but_only_recent_model_summaries() -> None:
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

    assert "用户原话 7" in serialized
    assert [t["user"] for t in state.history_turns] == [f"用户原话 {i}" for i in range(8)]
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
async def test_run13_soft_limit_finalizes_without_exposing_five_candidates(
    monkeypatch,
) -> None:
    """Run 13：8295 成功后，9290 停止资料动作但保留无工具回答出口。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    candidates = [
        {"entry_id": entry_id, "title": f"未筛选候选 {entry_id}"}
        for entry_id in (6, 2, 7, 5, 1)
    ]
    candidate_handle = state.store_result(
        "list",
        {"items": candidates, "returned_count": 5, "has_more": False},
        "limited",
        "limited",
        semantics={"result_role": "candidate", "project_name": "AGENT学习"},
        displayable=False,
    )
    state.tool_events.append(
        {
            "tool": "query_entries",
            "result_handle": candidate_handle,
            "status": "limited",
            "completeness": "limited",
            "result_summary": {"returned_count": 5, "has_more": False},
        }
    )
    await state.ledger.reserve_text()
    state.instrumentation.logs.append(
        InvocationLog(
            kind="text",
            provider="deepseek",
            model="deepseek-v4-flash",
            duration_ms=1,
            usage={"input_tokens": 6151},
            error=None,
            projected_input_tokens=8295,
        )
    )
    monkeypatch.setattr(
        "evals.dialogue_loop.instrumentation.estimate_input",
        lambda *_args, **_kwargs: InputEstimate(
            tokens=9290, components={"version": "run13-fixture"}
        ),
    )
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": (
                                    "我不能直接保存正式 Entry，但可以根据已确认对话"
                                    "提供候选稿；这里没有使用未筛选搜索候选。"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    turn, _ = await run_turn(
        build_agent(model),
        state,
        "整理成一条知识记录存进 AGENT学习 项目",
        [],
        build_finalizer_agent(model),
    )

    assert calls == 1
    assert turn["status"] == "completed"
    assert "不能直接保存正式 Entry" in turn["answer"]
    assert not any(block["kind"] == "list" for block in turn["blocks"])
    assert all(item["title"] not in turn["answer"] for item in candidates)
    assert [call["projected_input_tokens"] for call in turn["model_calls"][:2]] == [
        9290,
        9290,
    ]


def test_unfiltered_candidates_cannot_be_reported_as_zero_results() -> None:
    state = _state()
    state.store_result(
        "list",
        {"items": [{"entry_id": 1, "title": "内部候选"}]},
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    state.instrumentation.phase = "finalize"
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "text", "text": "没有找到直接相关正式记录。"}]}
    )

    assert "未筛选语义候选不能表达为零条、查无结果或不存在记录" in output_errors(
        answer, state
    )


@pytest.mark.asyncio
async def test_soft_limit_candidate_dependent_answer_saves_selection_continuation(
    monkeypatch,
) -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    candidate_handle = state.store_result(
        "list",
        {
            "items": [
                {"entry_id": entry_id, "title": f"候选 {entry_id}"}
                for entry_id in (6, 2, 7, 5, 1)
            ],
            "returned_count": 5,
            "has_more": False,
        },
        "limited",
        "limited",
        semantics={"result_role": "candidate", "project_name": "AGENT学习"},
        displayable=False,
    )
    state.tool_events.append(
        {
            "tool": "query_entries",
            "result_handle": candidate_handle,
            "status": "limited",
            "completeness": "limited",
            "params": {"query": "完整 Agent 的组成部分"},
            "result_summary": {"returned_count": 5, "has_more": False},
        }
    )
    await state.ledger.reserve_text()
    monkeypatch.setattr(
        "evals.dialogue_loop.instrumentation.estimate_input",
        lambda *_args, **_kwargs: InputEstimate(
            tokens=9290, components={"version": "run13-fixture"}
        ),
    )
    async def fake_material_refs(_state, entry_ids, _pairs):
        return {
            "workspace_id": 1,
            "user_id": 2,
            "entry_ids": entry_ids,
            "source_ids": [],
            "source_pairs": [],
            "fingerprints": {
                f"entry:{entry_id}": f"fingerprint-{entry_id}"
                for entry_id in entry_ids
            },
        }

    monkeypatch.setattr(loop_module, "_database_material_refs", fake_material_refs)

    def respond(_messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "insufficient",
                                "text": "必须先完成候选相关性筛选才能回答。",
                            }
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    turn, _ = await run_turn(
        build_agent(model), state, "这些候选中哪些直接相关？", [], build_finalizer_agent(model)
    )

    assert turn["status"] == "partial_completed"
    assert turn["completion"]["reason_code"] == "relevance_selection_pending"
    assert turn["completion"]["can_continue"] is True
    assert turn["completion"]["continuation"]["task_type"] == "relevance_selection"
    assert not any(block["kind"] == "list" for block in turn["blocks"])


@pytest.mark.asyncio
async def test_relevance_continuation_reuses_candidates_without_repeating_query() -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await _seed_finalize_material(state)
    state.begin_turn(430, "哪些候选直接回答了问题？")
    candidate_handle = state.store_result(
        "list",
        {
            "items": [
                {
                    "entry_id": seeded["entry_id"],
                    "title": seeded["title"],
                    "content": seeded["content"],
                }
            ],
            "returned_count": 1,
            "has_more": False,
        },
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    state.tool_events.append(
        {
            "tool": "search_knowledge",
            "result_handle": candidate_handle,
            "status": "limited",
            "completeness": "limited",
        }
    )
    continuation = await loop_module._create_relevance_continuation(
        state, state.current_message, state.tool_events
    )
    state.continuation = continuation
    state.begin_turn(431, "继续")
    calls = 0

    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert seeded["title"] in str(messages)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "select_relevant_entries",
                        {
                            "candidate_result_handle": candidate_handle,
                            "classifications": [
                                {
                                    "entry_id": seeded["entry_id"],
                                    "relevance": "direct",
                                    "reason": "正文直接回答问题",
                                }
                            ],
                        },
                    )
                ]
            )
        authorized = next(
            handle
            for handle, record in state.result_sets.items()
            if record.semantics.get("candidate_result_handle") == candidate_handle
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {"kind": "list", "result_handle": authorized, "label": "直接相关"}
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    turn, _ = await run_turn(
        build_agent(model), state, "继续", [], build_finalizer_agent(model)
    )

    assert turn["status"] == "completed"
    assert turn["context"]["continuation_mode"] == "relevance_selection"
    assert [event["tool"] for event in turn["tool_calls"]] == [
        "select_relevant_entries"
    ]
    assert all(
        event["tool"] not in {"search_knowledge", "query_entries", "read_entries"}
        for event in turn["tool_calls"]
    )
    assert state.continuation is None
    assert calls == 2


@pytest.mark.asyncio
async def test_relevance_continuation_rejects_invalid_handle_before_model() -> None:
    state = _state()
    seeded = await _seed_finalize_material(state)
    state.begin_turn(432, "筛选候选")
    candidate_handle = state.store_result(
        "list",
        {"items": [{"entry_id": seeded["entry_id"], "title": seeded["title"]}]},
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )
    continuation = await loop_module._create_relevance_continuation(
        state, state.current_message, []
    )
    continuation.recoverable_material["record_fingerprints"][candidate_handle] = "forged"
    state.continuation = continuation
    state.begin_turn(433, "继续")
    calls = []

    def respond(_messages, _info):
        calls.append(True)
        raise AssertionError("失效候选不得派发模型")

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    turn, _ = await run_turn(
        build_agent(model), state, "继续", [], build_finalizer_agent(model)
    )

    assert turn["status"] == "not_executed"
    assert turn["completion"]["reason_code"] == "continuation_material_invalid"
    assert calls == []
    assert state.continuation is None


@pytest.mark.asyncio
async def test_validation_retry_preserves_safe_general_text_for_soft_finalizer(
    monkeypatch,
) -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    candidate_handle = state.store_result(
        "list",
        {"items": [{"entry_id": 9, "title": "未筛选内部候选"}]},
        "limited",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=False,
    )

    def estimate(*_args, **_kwargs):
        tokens = (
            8_000
            if state.instrumentation.phase == "finalize"
            else 8_295
            if state.ledger.active_text_requests == 0
            else 9_290
        )
        return InputEstimate(tokens=tokens, components={"version": "validation-retry"})

    monkeypatch.setattr("evals.dialogue_loop.instrumentation.estimate_input", estimate)
    calls = 0
    preserved = "以下属于模型通用知识，不是 Grove 正式记录或 Source 原文。"

    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "blocks": [
                                {"kind": "text", "text": preserved},
                                {
                                    "kind": "list",
                                    "result_handle": candidate_handle,
                                    "label": "未经筛选",
                                },
                            ]
                        },
                    )
                ]
            )
        assert preserved in str(messages)
        assert "未筛选内部候选" not in str(messages)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": preserved}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    turn, _ = await run_turn(
        build_agent(model), state, "解释一般原则", [], build_finalizer_agent(model)
    )

    assert turn["status"] == "completed"
    assert preserved in turn["answer"]
    assert "未筛选内部候选" not in turn["answer"]
    assert not any(block["kind"] == "list" for block in turn["blocks"])
    assert calls == 2


@pytest.mark.asyncio
async def test_real_damaged_invalid_json_keeps_finalize_only_continuation(
    monkeypatch,
) -> None:
    state = _state()
    state.instrumentation.context_policy_enabled = True
    await _seed_finalize_material(state)
    raw = (
        Path(__file__).parent / "fixtures" / "dialogue-invalid-json-six-point.txt"
    ).read_text(encoding="utf-8").rstrip("\n")
    await state.ledger.reserve_text()
    monkeypatch.setattr(
        "evals.dialogue_loop.instrumentation.estimate_input",
        lambda *_args, **_kwargs: InputEstimate(
            tokens=9_290, components={"version": "invalid-json-recovery"}
        ),
    )
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"INVALID_JSON": raw})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "已仅重试最终回答。"}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    agent = build_agent(model)
    finalizer = build_finalizer_agent(model)
    failed, history = await run_turn(agent, state, "整理六点", [], finalizer)

    assert failed["status"] == "partial_completed"
    assert failed["completion"]["reason_code"] == "finalize_output_invalid"
    assert failed["completion"]["continuation"]["task_type"] == "finalize_answer"
    events_before = len(state.tool_events)

    state.begin_turn(434, "继续")
    completed, _ = await run_turn(agent, state, "继续", history, finalizer)

    assert completed["status"] == "completed"
    assert completed["context"]["continuation_mode"] == "finalize_only"
    assert completed["tool_calls"] == []
    assert len(state.tool_events) == events_before
    assert calls == 2


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
async def test_candidate_draft_survives_finalize_failure_and_continue_only_reformats() -> None:
    """候选稿校验或收尾失败时保留原稿，继续只重试候选整理。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await _seed_finalize_material(state)
    state.remember_turn(
        "你觉得第一条内容可以补充什么呢",
        "已读取国标说明，并给出了补充建议。",
        state.tool_events,
        blocks=[
            {
                "kind": "evidence",
                "handle": seeded["evidence_handle"],
                "entry_id": seeded["entry_id"],
                "source_id": seeded["source_id"],
            },
            {"kind": "text", "text": "后续可以整理成候选稿。"},
        ],
        completion={"status": "completed", "reason_code": "completed"},
    )
    message = "按你的分析，把第一条的知识补充一下，发给我"
    state.begin_turn(900, message)
    provider_calls = []
    events_before = len(state.tool_events)

    def respond(messages, info):
        provider_calls.append((messages, info))
        if len(provider_calls) >= 2:
            assert seeded["evidence_handle"] not in str(messages)
        if len(provider_calls) == 1:
            # 收尾失败夹具明确触发请求预留边界，不依赖旧历史不压缩的偶然长度。
            state.ledger.active.text_requests = PER_TURN_TEXT_REQUESTS - 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "blocks": [
                                {
                                    "kind": "text",
                                    "text": (
                                        "现有记录说明了人造板的环保等级。\n"
                                        "在此基础上，可以补充选择和维护建议。\n"
                                        "这是一版候选修改稿，尚未写入正式记录。"
                                    ),
                                }
                            ]
                        },
                    )
                ]
            )
        if len(provider_calls) == 2:
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
                                    "现有记录说明了人造板的环保等级。在此基础上，可以补充"
                                    "选择和维护建议。这是一版候选修改稿，尚未写入正式记录；"
                                    "新增分析不等于来源原文。"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    failed, history = await run_turn(
        build_agent(model), state, message, history, build_finalizer_agent(model)
    )

    assert failed["status"] == "partial_completed"
    assert failed["completion"]["reason_code"] == "finalize_tool_attempted"
    assert failed["completion"]["continuation"]["task_type"] == "candidate_draft"
    material = state.continuation.recoverable_material
    saved_text = "\n".join(
        block["text"]
        for block in material["candidate_draft"]["blocks"]
        if block["kind"] == "text"
    )
    assert "现有记录说明了人造板的环保等级" in saved_text
    assert material["candidate_draft_errors"] == ["候选修改稿缺少：来源边界"]
    summary = failed["completion"]["continuation"]["material_summary"]
    assert summary["answer_basis"] == "candidate_draft"
    assert summary["entry_ids"] == [seeded["entry_id"]]
    assert summary["source_ids"] == [seeded["source_id"]]
    assert summary["candidate_text_chars"] == len(saved_text)
    assert summary["validation_gaps"] == ["候选修改稿缺少：来源边界"]
    assert "现有记录说明了人造板的环保等级" in failed["answer"]
    assert "候选稿" in failed["answer"]
    assert len(state.tool_events) == events_before
    assert all(
        event["tool"] != "read_evidence" for event in state.tool_events[events_before:]
    )

    state.begin_turn(901, "继续")
    completed, _ = await run_turn(
        build_agent(model), state, "继续", history, build_finalizer_agent(model)
    )

    assert completed["status"] == "completed"
    assert completed["context"]["continuation_mode"] == "finalize_only"
    assert len(provider_calls) == 3
    assert len(state.tool_events) == events_before
    assert state.continuation is None
    assert "尚未写入正式记录" in completed["answer"]
    assert "新增分析不等于来源原文" in completed["answer"]


@pytest.mark.asyncio
async def test_candidate_finalizer_discards_invalid_evidence_and_completes() -> None:
    """回归 20260911-212827 第四轮：无效 Evidence 不得毁掉完整候选稿。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    message = "结合你分析的，把知识内容补充一下，发给我"
    state.begin_turn(902, message)
    provider_calls = []

    def respond(_messages, info):
        provider_calls.append(info)
        if len(provider_calls) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "blocks": [
                                {
                                    "kind": "text",
                                    "text": (
                                        "现有记录说明日本 F4 星级。可以补充认证核验方法。"
                                        "这是一版候选稿，尚未写入知识库。"
                                    ),
                                }
                            ]
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
                                    "现有记录说明日本 F4 星级及其认证要求。\n"
                                    "建议补充认证编号、检测方法和选购核验步骤。"
                                ),
                            },
                            {
                                "kind": "text",
                                "text": (
                                    "修改后的候选内容已整理完成，但尚未写入知识库；"
                                    "新增分析不是知识库 Source 原文，采用前仍需核实。"
                                ),
                            },
                            {
                                "kind": "evidence",
                                "evidence_handle": "ev-history-invalid",
                            },
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond, model_name="deepseek-v4-flash"),
        state.instrumentation,
        request_scope="dialogue_agent",
    )
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(
        build_agent(model), state, message, history, build_finalizer_agent(model)
    )

    assert turn["status"] == "completed"
    assert turn["completion"]["reason_code"] == "completed"
    assert turn["completion"]["continuation"] is None
    assert all(block["kind"] == "text" for block in turn["blocks"])
    assert "ev-history-invalid" not in turn["answer"]
    assert turn["tool_calls"] == []
    assert len(provider_calls) == 2
    assert provider_calls[1].function_tools == []
    assert turn["finalization"]["status"] == "completed"
    assert turn["finalization"]["compatibility"] == {
        "kind": "candidate_text_only",
        "status": "normalized",
        "discarded_blocks": ["evidence"],
        "preserved_text_blocks": 2,
    }
    assert state.continuation is None
    assert state.candidate_draft is None


@pytest.mark.parametrize(
    ("repair", "expected_fragment", "unexpected_fragment", "expected_gap"),
    [
        (
            "这是一段仍然缺少边界的缩减稿。",
            "缩减稿",
            "现有记录说明了人造板",
            "原记录与现有内容",
        ),
        (
            "已写入正式记录。",
            "现有记录说明了人造板",
            "已写入正式记录",
            "候选修改稿缺少：来源边界",
        ),
    ],
)
@pytest.mark.asyncio
async def test_candidate_finalizer_pairs_safe_draft_with_its_validation_gaps(
    repair: str,
    expected_fragment: str,
    unexpected_fragment: str,
    expected_gap: str,
) -> None:
    """安全的新失败稿携带新缺口；越界新稿保留上一安全稿及其缺口。"""

    state = _state()
    state.instrumentation.context_policy_enabled = True
    await _seed_finalize_material(state)
    message = "按你的分析，把第一条的知识补充一下，发给我"
    state.begin_turn(903, message)
    original = (
        "现有记录说明了人造板的环保等级。\n"
        "建议补充选购和维护方法。\n"
        "这是候选修改稿，尚未写入正式记录。"
    )
    calls = 0

    def respond(_messages, info):
        nonlocal calls
        calls += 1
        text = original if calls == 1 else repair
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": text}]},
                )
            ]
        )

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 4_000)])]
    turn, _ = await run_turn(
        build_agent(model), state, message, history, build_finalizer_agent(model)
    )

    assert turn["status"] == "partial_completed"
    assert calls == 2
    material = state.continuation.recoverable_material
    saved_text = "\n".join(block["text"] for block in material["candidate_draft"]["blocks"])
    assert expected_fragment in saved_text
    assert unexpected_fragment not in saved_text
    assert expected_fragment in turn["answer"]
    assert expected_gap in "；".join(material["candidate_draft_errors"])


def test_tone_only_candidate_uses_previous_candidate_as_semantic_baseline() -> None:
    """连续改写须保留上一版候选新增的数量归属和不确定性。"""

    state = _state()
    state.begin_turn(904, "内容不变，只改得更口语化")
    state.editing_active = True
    state.editing_purpose = "candidate"
    state.editing_context = loop_module.EditingContext(
        entry={
            "entry_id": 35,
            "title": "安装记录",
            "content": "原记录只说明需要留出安装空间。",
        },
        validation_refs={},
        draft={
            "blocks": [
                {
                    "kind": "text",
                    "text": (
                        "候选建议：安装时可能需要在上方预留大约 20 厘米空间。"
                        "这是模型补充的候选判断，尚未写入正式记录，也不属于 Source 原文。"
                    ),
                }
            ],
            "needs_clarification": False,
        },
    )
    state.candidate_draft = state.editing_context.draft
    rewritten = DialogueAnswer.model_validate(
        {
            "blocks": [
                {
                    "kind": "text",
                    "text": (
                        "现有候选改成口语说法：安装时必须预留 20 厘米空间。"
                        "这是模型补充的候选判断，尚未写入正式记录，也不属于 Source 原文。"
                    ),
                }
            ]
        }
    )

    errors = output_errors(rewritten, state)

    assert any("程度或不确定性" in error for error in errors)


@pytest.mark.asyncio
async def test_no_knowledge_discussion_selects_displayed_entry_without_data_read(
    monkeypatch,
) -> None:
    """“抛开知识库”只定位并复验已展示正文，不重新读取资料。"""

    state = _state()
    state.begin_turn(806, "抛开知识库，第一条说得对吗")
    entries = [
        {
            "entry_id": 35,
            "title": "第一条",
            "content": "第一条已经展示的正文",
            "sources": [],
        },
        {
            "entry_id": 18,
            "title": "第二条",
            "content": "第二条已经展示的正文",
            "sources": [],
        },
    ]
    state.authorized_entry_ids.update({35, 18})
    state.discovered_entry_ids.update({35, 18})
    state.discovered_entry_fingerprints.update({35: "a" * 64, 18: "b" * 64})
    handle = state.store_result(
        "entries",
        {"items": entries, "denied_entry_ids": [], "unavailable_entry_ids": []},
        "completed",
        "limited",
    )
    refs = {
        "workspace_id": state.workspace_id,
        "user_id": state.user_id,
        "entry_ids": [35],
        "source_ids": [],
        "source_pairs": [],
        "fingerprints": {"entry:35": "current"},
    }
    state.result_sets[handle].semantics["entry_validation_refs"] = {"35": refs}
    saved_draft = {
        "blocks": [{"kind": "text", "text": "上一版安全候选"}],
        "needs_clarification": False,
    }
    state.editing_context = loop_module.EditingContext(
        entry=entries[0],
        validation_refs=refs,
        draft=saved_draft,
        discussion="上一轮针对第一条的具体分析",
        decisions=["先分析第一条"],
    )
    handles_before = set(state.current_handles)
    checks = []

    async def fake_material_refs(_state, entry_ids, source_pairs):
        checks.append((entry_ids, source_pairs))
        return refs

    monkeypatch.setattr(loop_module, "_database_material_refs", fake_material_refs)

    selected = await select_editing_context(
        state,
        "edit",
        purpose="discussion",
        result_set_handle=handle,
        position=1,
    )

    assert selected["entry"]["entry_id"] == 35
    assert selected["result_handle"] is None
    assert state.editing_context is not None
    assert state.editing_context.entry["content"] == "第一条已经展示的正文"
    assert state.editing_context.discussion == "上一轮针对第一条的具体分析"
    assert state.editing_context.draft == saved_draft
    assert state.editing_context.decisions == ["先分析第一条", state.current_message]
    assert checks == [([35], [])]
    assert state.current_handles == handles_before
    assert not any(event.get("tool") in {"search_knowledge", "query_entries", "read_entries"}
                   for event in state.tool_events)


@pytest.mark.asyncio
async def test_no_knowledge_context_cannot_start_candidate_edit(monkeypatch) -> None:
    """不使用知识库的讨论例外不得扩展为候选编辑或资料获取。"""

    state = _state()
    state.begin_turn(807, "抛开知识库，按第一条生成候选")
    with pytest.raises(ModelRetry, match="只能用于通用讨论"):
        await select_editing_context(
            state,
            "edit",
            purpose="candidate",
            result_set_handle="rs-1-1",
            position=1,
        )


@pytest.mark.asyncio
async def test_displayed_entry_context_rejects_material_fingerprint_change(monkeypatch) -> None:
    """已展示正文的 Entry 或 Source 指纹变化后不得继续复用旧内容。"""

    state = _state()
    state.begin_turn(808, "抛开知识库，第一条说得对吗")
    entry = {"entry_id": 35, "title": "第一条", "content": "旧正文", "sources": []}
    state.authorized_entry_ids.add(35)
    state.discovered_entry_ids.add(35)
    state.discovered_entry_fingerprints[35] = "a" * 64
    saved_refs = {
        "workspace_id": state.workspace_id,
        "user_id": state.user_id,
        "entry_ids": [35],
        "source_ids": [],
        "source_pairs": [],
        "fingerprints": {"entry:35": "old"},
    }
    handle = state.store_result(
        "entries",
        {"items": [entry]},
        "completed",
        "limited",
        semantics={"entry_validation_refs": {"35": saved_refs}},
    )

    async def changed_refs(_state, _entry_ids, _source_pairs):
        return {**saved_refs, "fingerprints": {"entry:35": "changed"}}

    monkeypatch.setattr(loop_module, "_database_material_refs", changed_refs)

    with pytest.raises(ModelRetry, match="材料发生变化"):
        await select_editing_context(
            state,
            "edit",
            purpose="discussion",
            result_set_handle=handle,
            position=1,
        )
    assert state.editing_context is None
    assert state.editing_active is False


@pytest.mark.asyncio
async def test_continue_without_continuation_does_not_call_model_or_tools() -> None:
    """公开状态没有真实 continuation 时，“继续”不得回到普通资料循环。"""

    state = _state()
    state.remember_turn(
        "上一轮请求",
        "上一轮未完成",
        [],
        completion={
            "status": "partial_completed",
            "reason_code": "output_validation_failed",
            "reason": "模型输出非法",
            "incomplete_steps": ["模型未能生成合法回答"],
            "can_continue": False,
            "continuation": None,
        },
    )
    state.begin_turn(5, "继续")
    provider_calls = 0

    def respond(_messages, _info):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("没有 continuation 时不应调用模型")

    turn, _ = await run_turn(
        build_agent(FunctionModel(respond)),
        state,
        "继续",
        [],
    )

    assert turn["status"] == "not_executed"
    assert turn["completion"] == {
        "status": "not_executed",
        "reason_code": "continuation_not_available",
        "reason": "当前没有可恢复的未完成步骤",
        "incomplete_steps": ["未找到可续执行的最终回答状态"],
        "can_continue": False,
        "continuation": None,
    }
    assert turn["context"]["continuation_mode"] == "not_available"
    assert turn["model_calls"] == []
    assert turn["tool_calls"] == []
    assert turn["budget"]["turn"]["text_requests"] == 0
    assert turn["budget"]["turn"]["tool_calls"] == 0
    assert provider_calls == 0


def test_public_can_continue_requires_actual_continuation() -> None:
    """没有恢复状态时，内部可重问语义不能泄露成公开可续执行。"""

    stop = StopState(
        status="partial_completed",
        reason_code="output_validation_failed",
        reason="输出非法",
        incomplete_steps=["模型未能生成合法回答"],
        can_continue=True,
        continuation=None,
    )

    assert stop.snapshot()["can_continue"] is False


@pytest.mark.asyncio
async def test_model_only_finalizer_drops_historical_material_and_supports_answer_only_continue(
) -> None:
    state = _state()
    state.history_turns = [
        {
            "turn": 1,
            "user": "甲醛是什么",
            "answer_summary": {
                "narrative": "上一轮说明了 ENF 的概念和讨论边界。",
                "references": [
                    {"kind": "evidence", "handle": "ev-old", "source_id": 66}
                ],
            },
            "tools": [
                {
                    "tool": "read_evidence",
                    "conditions": {"entry_id": 9, "source_ids": [66]},
                    "status": "completed",
                    "result_handle": "ev-old",
                }
            ],
            "completion": {"status": "completed"},
        }
    ]
    state.begin_turn(5, "抛开知识库，你觉得可信吗")
    state.instrumentation.context_policy_enabled = True
    provider_calls = []

    def respond(messages, info):
        provider_calls.append((messages, info))
        if len(provider_calls) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "blocks": [
                                {
                                    "kind": "evidence",
                                    "evidence_handle": "ev-old",
                                    "note": "历史来源",
                                }
                            ]
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
                                "text": "这是基于通用知识的分析，不是 Grove 来源核验。",
                            }
                        ]
                    },
                )
            ]
        )

    model = BudgetedModel(
        FunctionModel(respond), state.instrumentation, request_scope="dialogue_agent"
    )
    finalizer = build_finalizer_agent(model)

    try:
        await loop_module._finalize_once(
            finalizer,
            state,
            state.current_message,
            build_compact_history(state),
            [],
            "output_validation_failed",
        )
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ in {"UnexpectedModelBehavior", "ModelRetry"}
    else:
        pytest.fail("非法历史 Evidence 引用必须使无资料 finalizer 失败")

    serialized = json.dumps(provider_calls[0][0], ensure_ascii=False, default=str)
    assert "read_evidence" not in serialized
    assert "ev-old" not in serialized
    assert state.instrumentation.finalize_status == "invalid_output"
    assert await loop_module._attach_finalize_continuation(
        state, state.current_message, []
    )
    assert state.continuation is not None
    assert state.continuation.scope["answer_basis"] == "model_only"
    assert state.continuation.snapshot()["material_summary"]["answer_basis"] == "model_only"
    assert "ev-old" not in json.dumps(state.continuation.snapshot(), ensure_ascii=False)

    state.begin_turn(6, "下一轮继续")
    completed, _ = await run_turn(
        build_agent(model), state, "下一轮继续", [], finalizer
    )

    assert completed["status"] == "completed"
    assert completed["tool_calls"] == []
    assert len(provider_calls) == 2
    assert state.continuation is None
    assert state.tools_allowed is False
    assert "不是 Grove 来源核验" in completed["answer"]


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

    wrong_workspace = deepcopy(continuation)
    forged_state.workspace_id += 1
    valid, reason = await _validate_finalize_continuation(forged_state, wrong_workspace)
    assert valid is False and "Workspace" in reason
    forged_state.workspace_id -= 1

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

    candidate_state = _state()
    candidate = await _seed_finalize_material(candidate_state)
    candidate_state.scope_type = "project"
    candidate_state.project_id = candidate["project_id"]
    entry_record = next(
        record
        for record in candidate_state.result_sets.values()
        if record.kind == "entries"
    )
    refs = await loop_module._database_material_refs(
        candidate_state,
        [candidate["entry_id"]],
        [(candidate["entry_id"], candidate["source_id"])],
    )
    candidate_state.editing_context = loop_module.EditingContext(
        entry=entry_record.payload["items"][0],
        validation_refs=refs,
        decisions=["把这条记录改得更口语化"],
    )
    candidate_state.editing_active = True
    candidate_state.editing_purpose = "candidate"
    candidate_state.candidate_draft = {
        "blocks": [{"kind": "text", "text": "候选文本"}],
        "needs_clarification": False,
    }
    candidate_continuation = await _create_finalize_continuation(
        candidate_state, "把这条记录改得更口语化", []
    )
    candidate_state.editing_context = None
    valid, reason = await _validate_finalize_continuation(
        candidate_state, candidate_continuation
    )
    assert valid is True and reason is None
    assert candidate_state.editing_context is not None
    assert candidate_state.editing_context.entry["entry_id"] == candidate["entry_id"]

    missing_context = deepcopy(candidate_continuation)
    missing_context.recoverable_material.pop("editing_context")
    candidate_state.editing_context = None
    valid, reason = await _validate_finalize_continuation(
        candidate_state, missing_context
    )
    assert valid is False and "缺少可恢复的编辑对象" in reason

    candidate_state.project_id += 1
    valid, reason = await _validate_finalize_continuation(
        candidate_state, candidate_continuation
    )
    assert valid is False and "项目范围" in reason


@pytest.mark.asyncio
async def test_invalid_continuation_does_not_call_model_and_topic_switch_clears_it() -> None:
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
        # 测试 SQLite 未启用外键级联；走 ORM 删除，避免悬空来源关系污染下一个复用 ID 的夹具。
        await db.delete(await db.get(Entry, seeded["entry_id"]))
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
