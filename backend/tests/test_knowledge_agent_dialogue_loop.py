"""统一对话循环实验的无模型边界与停止条件测试。"""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from evals.dialogue_loop.__main__ import _write
from evals.dialogue_loop.cli import InfrastructureFailure, parser
from evals.dialogue_loop.core import (
    BATCH_EMBEDDING_REQUESTS,
    BATCH_TEXT_REQUESTS,
    PER_TURN_EMBEDDING_REQUESTS,
    PER_TURN_TEXT_REQUESTS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
)
from evals.dialogue_loop.execution import _rehearsal_scenario
from evals.dialogue_loop.instrumentation import Instrumentation
from evals.dialogue_loop.isolation import assert_isolated, backup_database
from evals.dialogue_loop.loop import (
    LoopState,
    _entry_set,
    build_agent,
    list_position_entry_id,
    output_errors,
    render_answer,
    run_turn,
)
from evals.dialogue_loop.report import sanitize


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
    with pytest.raises(BudgetExceeded, match="上下文"):
        await run_turn(agent, state, "继续", ["x" * 50_000])
    assert calls == []


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
