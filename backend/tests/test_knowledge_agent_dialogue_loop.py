"""统一对话循环实验的无模型边界与停止条件测试。"""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from evals.dialogue_loop.__main__ import _write
from evals.dialogue_loop.cli import (
    InfrastructureFailure,
    _conclusion,
    _resource_by_arm,
    parser,
)
from evals.dialogue_loop.core import (
    BATCH_EMBEDDING_REQUESTS,
    BATCH_TEXT_REQUESTS,
    PER_TURN_EMBEDDING_REQUESTS,
    PER_TURN_TEXT_REQUESTS,
    VARIANT_SCENARIOS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
)
from evals.dialogue_loop.execution import _rehearsal_scenario
from evals.dialogue_loop.instrumentation import BudgetedModel, Instrumentation
from evals.dialogue_loop.isolation import assert_isolated, backup_database
from evals.dialogue_loop.loop import (
    SYSTEM_PROMPT,
    LoopState,
    _count_params,
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
        }
    )
    assert value["password"] == "<redacted>"
    assert value["api_key"] == "<redacted>"
    assert value["nested"]["authorization"] == "<redacted>"
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


@pytest.mark.asyncio
async def test_structured_output_gets_only_one_bounded_correction() -> None:
    state = _state()
    handle = state.store_result("statistic", {"value": 7}, "completed", "complete")
    calls = []

    def respond(messages, info):
        calls.append(messages)
        selected = "forged" if len(calls) == 1 else handle
        output = {"blocks": [{"kind": "statistic", "result_handle": selected, "label": "总数"}]}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    agent = build_agent(FunctionModel(respond))
    turn, _ = await run_turn(agent, state, "统计总数", [])
    assert turn["status"] == "completed"
    assert turn["answer"] == "总数：7"
    assert len(calls) == 2


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
    assert turn["budget"]["turn"]["text_requests"] == 1
    assert turn["context"]["input_estimates"][0]["finalize_only"] is True


@pytest.mark.asyncio
async def test_cancellation_does_not_turn_into_normal_answer() -> None:
    import asyncio

    state = _state()

    async def respond(messages, info):
        del messages, info
        await asyncio.sleep(10)

    task = asyncio.create_task(run_turn(build_agent(FunctionModel(respond)), state, "等待", []))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
