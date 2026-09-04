"""知识 Agent 一次有界覆盖补查单元测试。"""

from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeRequirementCoverageSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.coverage_repair import (
    CoverageRepairBaseline,
    CoverageRepairBudget,
    CoverageRepairNoNovelRequest,
    CoverageRepairPlanError,
    CoverageRepairSnapshot,
    RepairRunStorageAdapter,
    coverage_repair_execution_plan,
    derive_repair_eligibility,
    dump_coverage_repair_snapshot,
    execute_coverage_repair,
    merge_composite_execution,
    normalize_coverage_repair_plan,
    plan_and_persist_coverage_repair,
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


def test_coverage_repair_snapshot_uses_frozen_bytes_after_config_shrinks() -> None:
    """恢复期写检查点只服从 Run 冻结上限，不被新部署缩小值改道。"""
    baseline = _baseline().model_copy(deep=True)
    baseline.answer.answer = "甲" * 1600
    snapshot = CoverageRepairSnapshot(
        stage="executing",
        execution_mode="serial",
        frozen_budget=CoverageRepairBudget(max_snapshot_bytes=10_000),
        eligible_requirement_ids=["r1"],
        baseline=baseline,
    )
    changed = Settings(
        _env_file=None,
        knowledge_agent_coverage_repair_snapshot_bytes_limit=1000,
    )

    raw = dump_coverage_repair_snapshot(snapshot, settings=changed)

    assert restore_coverage_repair_snapshot(raw, settings=changed) == snapshot


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


def _original_plan():
    from app.services.knowledge_agent.composite_answer import normalize_composite_answer_plan

    return normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "explain",
                    "order": 0,
                    "summary": "解释概念",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                },
                {
                    "id": "grove",
                    "order": 1,
                    "summary": "说明个人知识中的来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                },
                {
                    "id": "external",
                    "order": 2,
                    "summary": "核验当前政策",
                    "kind": "other",
                    "basis_policy": "external_required",
                },
            ],
            "retrieval_requests": [
                {
                    "id": "initial",
                    "query": "甲醛 来源",
                    "requirement_ids": ["grove"],
                }
            ],
        }
    )


def _eligibility_execution() -> CompositeAnswerExecutionSnapshot:
    return CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="a" * 64,
                status="limited",
                completeness="limited",
            )
        ]
    )


def _eligibility_coverage() -> CompositeAnswerCoverageSnapshot:
    return CompositeAnswerCoverageSnapshot(
        requirements=[
            CompositeRequirementCoverageSnapshot(
                requirement_id="r1", status="insufficient"
            ),
            CompositeRequirementCoverageSnapshot(
                requirement_id="r2", status="partial"
            ),
            CompositeRequirementCoverageSnapshot(
                requirement_id="r3", status="partial"
            ),
        ]
    )


def test_coverage_repair_eligibility_only_accepts_repairable_grove_gaps() -> None:
    """纯模型漏答和无外部工具义务不能伪装成 Grove 补查。"""
    eligibility = derive_repair_eligibility(
        _original_plan(), _eligibility_execution(), _eligibility_coverage()
    )

    assert eligibility.requirement_ids == ["r2"]
    assert eligibility.reasons == {"r2": "limited_input"}


def test_coverage_repair_plan_draft_rejects_scope_and_unknown_targets() -> None:
    """候选 schema 不接受 Workspace 或非准入义务。"""
    from pydantic import ValidationError

    from app.agents.coverage_repair import CoverageRepairPlanDraft

    with pytest.raises(ValidationError):
        CoverageRepairPlanDraft.model_validate(
            {"target_requirement_ids": ["r2"], "workspace_id": 9}
        )
    with pytest.raises(CoverageRepairPlanError, match="非准入"):
        normalize_coverage_repair_plan(
            {
                "target_requirement_ids": ["r1"],
                "retrieval_requests": [
                    {"id": "x", "query": "新查询", "requirement_ids": ["r1"]}
                ],
            },
            original_plan=_original_plan(),
            eligible_requirement_ids={"r2"},
            scope_fingerprint="scope-a",
            budget=CoverageRepairBudget(),
        )


def test_coverage_repair_normalization_assigns_continuing_ids() -> None:
    """补查只生成接续首次计划的新请求 id。"""
    plan = normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r2"],
            "retrieval_requests": [
                {
                    "id": "broader",
                    "query": "室内污染 材料 释放源",
                    "requirement_ids": ["r2"],
                }
            ],
        },
        original_plan=_original_plan(),
        eligible_requirement_ids={"r2"},
        scope_fingerprint="scope-a",
        budget=CoverageRepairBudget(),
    )

    assert plan.target_requirement_ids == ["r2"]
    assert plan.retrieval_requests[0].id == "q2"
    assert _original_plan().retrieval_requests[0].query == "甲醛 来源"


def test_coverage_repair_duplicate_requests_stop_without_execution() -> None:
    """完全重复以 no_novel 停止，混合重复和新请求整份拒绝。"""
    common = {
        "original_plan": _original_plan(),
        "eligible_requirement_ids": {"r2"},
        "scope_fingerprint": "scope-a",
        "budget": CoverageRepairBudget(),
    }
    with pytest.raises(CoverageRepairNoNovelRequest):
        normalize_coverage_repair_plan(
            {
                "target_requirement_ids": ["r2"],
                "retrieval_requests": [
                    {
                        "id": "same",
                        "query": "  甲醛   来源 ",
                        "requirement_ids": ["r2"],
                    }
                ],
            },
            **common,
        )
    with pytest.raises(CoverageRepairPlanError, match="混合"):
        normalize_coverage_repair_plan(
            {
                "target_requirement_ids": ["r2"],
                "retrieval_requests": [
                    {
                        "id": "same",
                        "query": "甲醛 来源",
                        "requirement_ids": ["r2"],
                    },
                    {
                        "id": "new",
                        "query": "装修材料 释放源",
                        "requirement_ids": ["r2"],
                    },
                ],
            },
            **common,
        )


@pytest.mark.asyncio
async def test_coverage_repair_planner_is_attempted_once(monkeypatch) -> None:
    """计划失败也是已提交决策，恢复不再调用模型。"""
    calls = 0

    async def planner(*args, **kwargs):
        nonlocal calls
        calls += 1
        from app.services.knowledge_agent.observability import StageMeta

        return None, StageMeta(
            purpose="coverage_repair_plan",
            provider="offline",
            model=None,
            is_fallback=True,
            error="不可用",
            duration_ms=1,
        )

    async def record(*args, **kwargs):
        return None

    class Db:
        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.coverage_repair.run_coverage_repair_planner",
        planner,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.coverage_repair.record_model_invocation", record
    )
    run = SimpleNamespace(
        id=7,
        workspace_id=3,
        coverage_repair_plan_json=None,
        coverage_repair_json=None,
    )
    snapshot = CoverageRepairSnapshot(
        stage="baseline_ready",
        execution_mode="serial",
        frozen_budget=CoverageRepairBudget(),
        eligible_requirement_ids=["r2"],
        baseline=CoverageRepairBaseline(
            answer=KnowledgeAnswerOut(answer="基线", status="partial"),
            coverage=_eligibility_coverage(),
            answer_basis={"schema_version": "v1"},
            run_status="partial",
        ),
    )

    _, failed = await plan_and_persist_coverage_repair(
        Db(),
        run,
        snapshot,
        original_plan=_original_plan(),
        original_execution=_eligibility_execution(),
        current_message="问题",
        scope_fingerprint="scope-a",
        cancel_check=lambda: _noop(),
    )
    _, restored = await plan_and_persist_coverage_repair(
        Db(),
        run,
        failed,
        original_plan=_original_plan(),
        original_execution=_eligibility_execution(),
        current_message="问题",
        scope_fingerprint="scope-a",
        cancel_check=lambda: _noop(),
    )

    assert calls == 1
    assert restored.stop_reason == "planner_failed"


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_coverage_repair_planner_prompt_is_closed_and_bounded(monkeypatch) -> None:
    """Planner 只看到义务/执行/预算摘要，不获得可控范围字段。"""
    from dataclasses import dataclass

    from app.agents.coverage_repair import (
        COVERAGE_REPAIR_SYSTEM_PROMPT,
        CoverageRepairPlanDraft,
        run_coverage_repair_planner,
    )

    captured: dict[str, str] = {}

    class Model:
        model_name = "fake-repair-model"

    @dataclass
    class Usage:
        requests: int = 1

    class Result:
        output = CoverageRepairPlanDraft()
        usage = Usage()

    class FakeAgent:
        def __init__(self, model, **kwargs):
            captured["prompt"] = kwargs["system_prompt"]

        async def run(self, context: str):
            captured["context"] = context
            return Result()

    async def model(*args, **kwargs):
        return Model()

    monkeypatch.setattr("app.agents.coverage_repair.get_text_model", model)
    monkeypatch.setattr("app.agents.coverage_repair.Agent", FakeAgent)
    draft, meta = await run_coverage_repair_planner(
        object(),
        99,
        current_message="补齐我的甲醛来源说明",
        requirements=[
            {
                "id": "r2",
                "summary": "说明个人知识中的来源",
                "basis_policy": "grove_required",
            }
        ],
        eligible_requirement_ids=["r2"],
        executed_inputs=[{"request_id": "q1", "status": "limited"}],
        budget={"max_queries": 2},
    )

    assert draft is not None and draft.retrieval_requests == []
    assert meta.is_fallback is False
    assert "可修复 requirement id：[\"r2\"]" in captured["context"]
    assert "Workspace" not in captured["context"]
    assert "不要输出 owner、Workspace" in COVERAGE_REPAIR_SYSTEM_PROMPT


def _repair_plan():
    return normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r2"],
            "retrieval_requests": [
                {
                    "id": "new",
                    "query": "装修材料 释放源",
                    "requirement_ids": ["r2"],
                }
            ],
        },
        original_plan=_original_plan(),
        eligible_requirement_ids={"r2"},
        scope_fingerprint="scope-a",
        budget=CoverageRepairBudget(),
    )


def test_coverage_repair_adapter_and_plan_keep_initial_snapshots_immutable() -> None:
    """补查执行器只能看到补查列，子计划只含接续请求。"""
    run = SimpleNamespace(
        composite_answer_execution_json="initial-execution",
        shared_execution_graph_json="initial-graph",
        shared_execution_state_json="initial-state",
        coverage_repair_execution_json=None,
        coverage_repair_graph_json=None,
        coverage_repair_graph_state_json=None,
    )
    adapter = RepairRunStorageAdapter(run)
    adapter.composite_answer_execution_json = "repair-execution"
    adapter.shared_execution_graph_json = "repair-graph"
    adapter.shared_execution_state_json = "repair-state"
    execution_plan = coverage_repair_execution_plan(_original_plan(), _repair_plan())

    assert run.composite_answer_execution_json == "initial-execution"
    assert run.shared_execution_graph_json == "initial-graph"
    assert run.shared_execution_state_json == "initial-state"
    assert run.coverage_repair_execution_json == "repair-execution"
    assert run.coverage_repair_graph_json == "repair-graph"
    assert run.coverage_repair_graph_state_json == "repair-state"
    assert [item.id for item in execution_plan.retrieval_requests] == ["q2"]
    assert execution_plan.structured_requests == []
    assert execution_plan.requirements == _original_plan().requirements


@pytest.mark.parametrize("execution_mode", ["serial", "shared_graph"])
@pytest.mark.asyncio
async def test_coverage_repair_execute_uses_frozen_mode_and_budget(
    monkeypatch, execution_mode
) -> None:
    """配置变化后仍按快照模式和冻结总预算执行到独立列。"""
    from app.services.knowledge_agent.composite_answer_execution import (
        CompositeExecutionArtifacts,
    )

    captured = {}

    async def execute(db, adapter, ctx, plan, **kwargs):
        captured["settings"] = kwargs["settings"]
        captured["request_ids"] = [item.id for item in plan.retrieval_requests]
        captured["max_tool_calls"] = kwargs.get("max_tool_calls")
        adapter.composite_answer_execution_json = "repair-checkpoint"
        return CompositeExecutionArtifacts(snapshot=CompositeAnswerExecutionSnapshot())

    target = (
        "app.services.knowledge_agent.shared_execution_graph."
        "execute_shared_execution_graph_plan"
        if execution_mode == "shared_graph"
        else "app.services.knowledge_agent.composite_answer_execution."
        "execute_composite_answer_plan"
    )
    monkeypatch.setattr(target, execute)

    class Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    run = SimpleNamespace(
        id=8,
        coverage_repair_json=None,
        coverage_repair_execution_json=None,
        coverage_repair_graph_json=None,
        coverage_repair_graph_state_json=None,
        composite_answer_execution_json="initial-execution",
        shared_execution_graph_json="initial-graph",
        shared_execution_state_json="initial-state",
    )
    budget = CoverageRepairBudget(
        max_nodes=7,
        max_tool_calls=5,
        max_entries=9,
        max_evidence=8,
        max_duration_ms=12_000,
    )
    snapshot = CoverageRepairSnapshot(
        stage="plan_ready",
        execution_mode=execution_mode,
        frozen_budget=budget,
        eligible_requirement_ids=["r2"],
        baseline=_baseline(),
    )
    changed_settings = Settings(
        _env_file=None,
        knowledge_agent_coverage_repair_max_nodes=1,
        knowledge_agent_coverage_repair_max_tool_calls=1,
        knowledge_agent_coverage_repair_max_entries=1,
        knowledge_agent_coverage_repair_max_evidence=1,
    )

    _, completed = await execute_coverage_repair(
        Db(),
        run,
        object(),
        _original_plan(),
        _repair_plan(),
        snapshot,
        cancel_check=_noop,
        settings=changed_settings,
    )

    assert completed.stage == "execution_ready"
    assert captured["request_ids"] == ["q2"]
    assert captured["settings"].knowledge_agent_shared_execution_graph_max_nodes == 7
    assert captured["settings"].knowledge_agent_composite_answer_max_entries == 9
    assert captured["settings"].knowledge_agent_composite_answer_max_evidence == 8
    if execution_mode == "serial":
        assert captured["max_tool_calls"] == 5
        assert run.coverage_repair_execution_json == "repair-checkpoint"
    else:
        assert captured["max_tool_calls"] is None
    assert run.composite_answer_execution_json == "initial-execution"
    assert run.shared_execution_graph_json == "initial-graph"
    assert run.shared_execution_state_json == "initial-state"


def test_merge_execution_only_appends_repair_results() -> None:
    """合并完整保留首次序列化对象，只追加无冲突补查结果。"""
    original = _eligibility_execution()
    repair = CompositeAnswerExecutionSnapshot(
        elapsed_ms=12,
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q2",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="b" * 64,
                status="completed",
                completeness="limited",
                entry_ids=[9],
                evidence_handles=["ev_repair"],
                tool_calls=3,
            )
        ],
        tool_facts=[
            CompositeToolFact(
                handle="res_repair",
                request_id="q2",
                requirement_ids=["r2"],
                kind="count",
                text="可确认 1 条。",
                completeness="limited",
            )
        ],
    )
    original_raw = original.model_dump_json()

    merged = merge_composite_execution(
        _original_plan(), original, _repair_plan(), repair
    )

    assert original.model_dump_json() == original_raw
    assert [item.request_id for item in merged.inputs] == ["q1", "q2"]
    assert merged.inputs[0] == original.inputs[0]
    assert merged.inputs[1].evidence_handles == ["ev_repair"]


def test_merge_execution_rejects_request_and_handle_conflicts() -> None:
    """补查不能覆盖首次 request 或复用不可区分的结果句柄。"""
    repair = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="b" * 64,
                status="completed",
            )
        ]
    )
    with pytest.raises(ValueError, match="request id"):
        merge_composite_execution(
            _original_plan(), _eligibility_execution(), _repair_plan(), repair
        )


@pytest.mark.asyncio
async def test_repair_cancel_checkpoint_stops_before_any_tool(monkeypatch) -> None:
    """进入 executing 后的取消边界不得启动补查请求。"""
    from app.services.knowledge_agent.runner import RunCancelled

    called = False

    async def forbidden(*args, **kwargs):  # pragma: no cover
        nonlocal called
        called = True
        raise AssertionError("取消后不得启动执行器")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "execute_composite_answer_plan",
        forbidden,
    )

    class Db:
        async def commit(self):
            return None

    run = SimpleNamespace(
        id=12,
        coverage_repair_json=None,
        coverage_repair_execution_json=None,
        coverage_repair_graph_json=None,
        coverage_repair_graph_state_json=None,
    )

    async def cancelled():
        raise RunCancelled()

    snapshot = CoverageRepairSnapshot(
        stage="plan_ready",
        execution_mode="serial",
        frozen_budget=CoverageRepairBudget(),
        eligible_requirement_ids=["r2"],
        baseline=_baseline(),
    )
    with pytest.raises(RunCancelled):
        await execute_coverage_repair(
            Db(),
            run,
            object(),
            _original_plan(),
            _repair_plan(),
            snapshot,
            cancel_check=cancelled,
        )

    assert called is False
    assert restore_coverage_repair_snapshot(run.coverage_repair_json).stage == "executing"


@pytest.mark.asyncio
async def test_repair_serial_budget_exhaustion_dispatches_no_tool(monkeypatch) -> None:
    """冻结工具预算不足一个检索请求时固化 limited，不发生透支调用。"""
    from app.services.knowledge_agent.composite_answer_execution import (
        execute_composite_answer_plan,
    )

    async def forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("预算耗尽不得调用检索工具")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "search_confirmed_knowledge",
        forbidden,
    )

    class Db:
        async def commit(self):
            return None

    run = SimpleNamespace(id=13, composite_answer_execution_json=None)
    result = await execute_composite_answer_plan(
        Db(),
        run,
        object(),
        coverage_repair_execution_plan(_original_plan(), _repair_plan()),
        cancel_check=_noop,
        max_tool_calls=1,
    )

    assert result.snapshot.inputs[0].status == "limited"
    assert result.snapshot.inputs[0].tool_calls == 0
    assert "预算已耗尽" in result.snapshot.inputs[0].error
