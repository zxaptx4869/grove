"""知识 Agent 一次有界覆盖补查单元测试。"""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeRequirementCoverageSnapshot,
)
from app.services.knowledge_agent.coverage_repair import (
    CoverageRepairBaseline,
    CoverageRepairBudget,
    CoverageRepairSnapshot,
    dump_coverage_repair_snapshot,
    restore_coverage_repair_snapshot,
)


def _baseline() -> CoverageRepairBaseline:
    return CoverageRepairBaseline(
        answer=KnowledgeAnswerOut(answer="首次合法回答", status="partial"),
        coverage=CompositeAnswerCoverageSnapshot(
            requirements=[
                CompositeRequirementCoverageSnapshot(
                    requirement_id="r1",
                    status="partial",
                    note="未形成该义务需要的 Grove 依据",
                )
            ]
        ),
        answer_basis={"schema_version": "v1", "basis_kinds": ["grove_evidence"]},
        run_status="partial",
        answer_fallback=False,
    )


def test_coverage_repair_snapshot_round_trip_preserves_baseline() -> None:
    """基线 answer/coverage/basis 在补查失败前必须可完整恢复。"""
    settings = Settings(_env_file=None)
    snapshot = CoverageRepairSnapshot(
        stage="baseline_ready",
        execution_mode="serial",
        frozen_budget=CoverageRepairBudget.from_settings(settings),
        eligible_requirement_ids=["r1"],
        baseline=_baseline(),
    )

    raw = dump_coverage_repair_snapshot(snapshot, settings=settings)
    restored = restore_coverage_repair_snapshot(raw, settings=settings)

    assert restored == snapshot
    assert restored is not None
    assert restored.baseline.answer.answer == "首次合法回答"
    assert restored.baseline.coverage.requirements[0].status == "partial"


def test_coverage_repair_snapshot_rejects_unknown_fields_and_bytes() -> None:
    """恢复不得接受未知语义或超出冻结字节上限。"""
    settings = Settings(_env_file=None)
    snapshot = CoverageRepairSnapshot(
        stage="baseline_ready",
        execution_mode="serial",
        frozen_budget=CoverageRepairBudget(max_snapshot_bytes=1000),
        eligible_requirement_ids=["r1"],
        baseline=_baseline(),
    )
    raw = snapshot.model_dump_json()

    with pytest.raises(ValueError, match="冻结预算"):
        restore_coverage_repair_snapshot(raw + " " * 1000, settings=settings)
    with pytest.raises(ValueError, match="非法"):
        restore_coverage_repair_snapshot(
            raw[:-1] + ',"workspace_id":2}', settings=settings
        )


def test_coverage_repair_run_fields_are_internal_nullable_snapshots() -> None:
    """Run ORM 只追加内部可空列，不改变公开协议。"""
    from app.models import KnowledgeAgentRun

    names = set(KnowledgeAgentRun.__table__.columns.keys())
    assert {
        "coverage_repair_json",
        "coverage_repair_plan_json",
        "coverage_repair_execution_json",
        "coverage_repair_graph_json",
        "coverage_repair_graph_state_json",
    }.issubset(names)
    assert all(
        KnowledgeAgentRun.__table__.columns[name].nullable
        for name in names
        if name.startswith("coverage_repair")
    )


def test_legacy_run_without_coverage_repair_snapshot_restores_none() -> None:
    """旧 Run 不反向生成补查决策。"""
    run = SimpleNamespace(coverage_repair_json=None)
    assert restore_coverage_repair_snapshot(run.coverage_repair_json) is None
