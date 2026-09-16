"""知识 Agent 当前数据合同与历史字段兼容测试。"""

import json
from datetime import UTC, datetime

from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import (
    ANSWER_MODE_AUTO,
    CONTEXT_MODE_AUTO,
    RESULT_MODE_AUTO,
    RUN_ACTIVE_STATUSES,
    RUN_KIND_ANSWER,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.runs import run_out


def test_run_status_and_request_defaults() -> None:
    assert RUN_ACTIVE_STATUSES | RUN_TERMINAL_STATUSES == {
        "waiting",
        "processing",
        "completed",
        "partial",
        "failed",
        "cancelled",
    }
    request = KnowledgeRunSubmitRequest(client_message_id="defaults", message="问题")
    assert request.context_mode == CONTEXT_MODE_AUTO
    assert request.answer_mode == ANSWER_MODE_AUTO
    assert request.result_mode == RESULT_MODE_AUTO
    assert request.basis_mode is None


def test_run_model_keeps_current_and_historical_columns() -> None:
    columns = KnowledgeAgentRun.__table__.c
    current = {
        "run_kind",
        "status",
        "cancel_requested",
        "current_step",
        "dialogue_loop_state_json",
        "retry_count",
        "claimed_at",
    }
    historical = {
        "investigation_summary",
        "composite_answer_plan_json",
        "composite_answer_execution_json",
        "composite_answer_coverage_json",
        "shared_execution_graph_json",
        "coverage_repair_json",
        "coverage_repair_plan_json",
        "coverage_repair_execution_json",
        "coverage_repair_graph_json",
        "coverage_repair_graph_state_json",
    }
    assert current <= set(columns.keys())
    assert historical <= set(columns.keys())
    assert columns.run_kind.default.arg == RUN_KIND_ANSWER
    assert columns.status.default.arg == RUN_WAITING


def test_historical_run_projection_tolerates_empty_legacy_snapshots() -> None:
    run = KnowledgeAgentRun(
        id=1,
        conversation_id=1,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        status="completed",
        run_kind="answer",
        request_context_mode="auto",
        request_answer_mode="auto",
        request_result_mode="auto",
        request_basis_mode="auto",
        cancel_requested=False,
        retry_count=0,
        max_retries=1,
        current_round=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        composite_answer_plan_json=None,
        composite_answer_coverage_json=None,
        dialogue_loop_state_json=json.dumps(
            {"loop_status": "completed", "completion": {"can_continue": False}}
        ),
    )
    projected = run_out(run)
    assert projected.composite_answer_plan is None
    assert projected.composite_answer_coverage is None
    assert projected.dialogue_loop_status == "completed"
