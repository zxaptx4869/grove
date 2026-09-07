"""统一对话循环实验的无模型边界与停止条件测试。"""

import hashlib
import json
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
    INPUT_ESTIMATE_VERSION,
    PER_TURN_EMBEDDING_REQUESTS,
    PER_TURN_TEXT_REQUESTS,
    VARIANT_SCENARIOS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
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
    _count_params,
    _current_material_history,
    _entry_set,
    _group_params,
    _model_payload,
    build_agent,
    build_compact_history,
    list_position_entry_id,
    output_errors,
    render_answer,
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
    assert project["project_name"] == "房子装修"
    assert all_projects["project_name"] is None
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
        "1. 甲\n2. 乙",
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
    assert info.instructions == SYSTEM_PROMPT
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


def test_no_knowledge_instruction_is_programmatically_recorded() -> None:
    state = _state()
    state.begin_turn(5, "先不查知识库，聊聊怎样记笔记")
    assert state.tools_allowed is False
    state.begin_turn(6, "先别查库，聊聊怎样安排间隔复习")
    assert state.tools_allowed is False


def test_agent_exposes_split_statistics_without_composite_arguments() -> None:
    agent = build_agent(FunctionModel(lambda _messages, _info: None))
    tools = agent._function_toolset.tools
    assert "count_entries" in tools
    assert "group_entries" in tools
    assert "aggregate_entries" not in tools
    count_schema = tools["count_entries"].function_schema.json_schema
    group_schema = tools["group_entries"].function_schema.json_schema
    assert "operation" not in count_schema["properties"]
    assert "group_by" not in count_schema["properties"]
    assert group_schema["required"] == ["project_scope", "project_name", "group_by"]


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
    assert checkpoints[0]["turns"][0]["context"]["experiment_version"] == "prototype-v2"


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
    assert all(info.instructions == SYSTEM_PROMPT for _, info in calls)
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
    assert turn["status"] == "failed"
    assert "上下文" in turn["error"]
    assert calls == []


@pytest.mark.asyncio
async def test_soft_input_limit_forces_one_budgeted_finalize_request() -> None:
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(agent, state, "请总结", history)
    assert turn["status"] == "completed"
    assert len(calls) == 1
    assert calls[0][1].function_tools == []
    assert calls[0][1].instructions == SYSTEM_PROMPT
    assert SYSTEM_PROMPT not in str(calls[0][0])
    assert FINALIZE_INSTRUCTION in str(calls[0][0])
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert turn["context"]["input_estimates"][0]["finalize_only"] is True
    assert turn["finalization"]["status"] == "completed"
    assert turn["finalization"]["reason"] == "input_soft_limit"


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

    assert turn["status"] == "completed"
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
    from evals.dialogue_loop.core import PER_TURN_TOOL_CALLS

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

    assert turn["status"] == "completed"
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

    assert turn["status"] == "completed"
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

    assert turn["status"] == "failed"
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "failed"
    assert turn["finalization"]["status"] == "failed"
    assert turn["finalization"]["attempted"] is True
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert turn["usage"]["requests"] == 1
    assert turn["usage"]["input_tokens"] is None
    assert turn["usage"]["usage_complete"] is False
    assert any(block.get("handle") == handle for block in turn["blocks"])
    assert "provider unavailable" in turn["error"]
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "failed"
    assert turn["solve_error"] is None
    assert turn["finalization"]["status"] == "timed_out"
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert turn["duration_ms"] < 500
    assert "已验证统计：5" in turn["answer"]
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(agent, state, "请总结", history)

    assert turn["status"] == "failed"
    assert turn["finalization"]["status"] == "invalid_output"
    assert len(calls) == 1
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert any(block.get("handle") == handle for block in turn["blocks"])
    assert "未重试模型请求" in turn["error"]
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(build_agent(model), state, "请总结", history)

    assert turn["status"] == "failed"
    assert len(calls) == 1
    assert turn["error_details"]["category"] == "schema_validation"
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
    history = [ModelRequest(parts=[UserPromptPart(content="甲" * 9_500)])]
    turn, _ = await run_turn(build_agent(model), state, "请总结", history)

    assert turn["status"] == "failed"
    assert turn["error_details"]["category"] == "truncated"
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
    assert log["estimate_components"]["instruction_utf8_bytes"] == len(
        SYSTEM_PROMPT.encode("utf-8")
    )
    assert log["estimate_components"]["instruction_count"] == 1
    assert log["estimate_components"]["historical_system_count"] == 0
    assert log["estimate_components"]["instruction_sha256"] == hashlib.sha256(
        SYSTEM_PROMPT.encode("utf-8")
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

    assert turn["status"] == "failed"
    assert turn["finalization"]["status"] == "not_dispatched"
    assert turn["finalization"]["attempted"] is False
    assert turn["budget"]["batch_text_requests"] == BATCH_TEXT_REQUESTS
    assert calls == []
    assert "未派发模型收尾" in turn["answer"]
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
