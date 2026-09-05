"""手动验收回归：部分回答、依据、补查统计口径与失败恢复。"""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.knowledge_agent import KnowledgeAnswerDraft, KnowledgeAnswerPointDraft
from app.core.config import Settings
from app.models import KnowledgeAgentEvidence
from app.schemas.knowledge_agent import KnowledgeAnswerOut, KnowledgeAnswerPointOut
from app.services.knowledge_agent.basis import answer_uses_model_knowledge, build_answer_basis
from app.services.knowledge_agent.composite_answer import normalize_composite_answer_plan
from app.services.knowledge_agent.composite_answer_response import (
    CompositeAnswerResult,
    _answer_entries,
    _validated_draft_bindings,
    label_repair_facts,
    preserve_answer_with_repair_facts,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.coverage_repair import (
    CoverageRepairBudget,
    CoverageRepairPlanError,
    CoverageRepairSnapshot,
    coverage_repair_material_from_result,
    dump_coverage_repair_plan,
    normalize_coverage_repair_plan,
    restore_coverage_repair_snapshot,
)
from app.services.knowledge_agent.evidence import build_validated_answer


def _plan():
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
                    "id": "count",
                    "order": 1,
                    "summary": "统计治理方案",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "structured_requests": [
                {
                    "id": "first",
                    "requirement_ids": ["count"],
                    "entry_set": {
                        "semantic_query": "甲醛治理方案",
                        "main_types": ["knowledge", "method"],
                    },
                    "outputs": [{"kind": "count"}],
                }
            ],
        }
    )


def _execution(request_id, value):
    fact = CompositeToolFact(
        handle=f"res_{request_id}",
        request_id=request_id,
        requirement_ids=["r2"],
        kind="count",
        text=f"本次有限匹配 {value} 条，不代表完整总数。",
        completeness="limited",
        summary={"value": value},
    )
    return CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id=request_id,
                kind="structured",
                requirement_ids=["r2"],
                fingerprint=request_id,
                status="limited",
                completeness="limited",
                result_handles=[fact.handle],
            )
        ],
        tool_facts=[fact],
    )


def _baseline():
    answer = KnowledgeAnswerOut(
        answer="首次合法解释",
        status="partial",
        points=[
            KnowledgeAnswerPointOut(text="首次合法解释", requirement_ids=["r1"]),
            KnowledgeAnswerPointOut(
                text=_execution("s1", 0).tool_facts[0].text, requirement_ids=["r2"]
            ),
        ],
    )
    return CompositeAnswerResult(
        answer=answer,
        coverage=CompositeAnswerCoverageSnapshot(
            requirements=[
                {"requirement_id": "r1", "status": "answered"},
                {"requirement_id": "r2", "status": "partial", "result_handles": ["res_s1"]},
            ]
        ),
        answer_basis=build_answer_basis(
            answer=answer,
            user_statement_ids=[],
            model_knowledge_used=True,
            external_material_required=False,
            grove_result_used=True,
        ),
        run_status="partial",
        answer_fallback=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "direct,valid,expected",
    [
        (True, True, "partial"),
        (False, True, "insufficient"),
        (None, True, "insufficient"),
        (True, False, "insufficient"),
    ],
)
async def test_partial_answer_requires_direct_and_valid_point(monkeypatch, direct, valid, expected):
    """有引用不等于答题；只有有效且明确直接回答的内容能纠正矛盾标记。"""
    row = KnowledgeAgentEvidence(
        id=1,
        handle="ev_valid",
        entry_id=1,
        source_id=1,
        quote="胶水释放甲醛",
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.evidence.resolve_evidence_handles",
        AsyncMock(return_value={"ev_valid": row} if valid else {}),
    )
    draft = KnowledgeAnswerDraft(
        insufficient=True,
        core_question_answered=False,
        coverage_complete=False,
        points=[
            KnowledgeAnswerPointDraft(
                text="胶水是来源之一", evidence_handles=["ev_valid"], answers_core_question=direct
            )
        ],
    )
    answer, _ = await build_validated_answer(None, 1, draft)
    assert answer.status == expected
    if expected == "partial":
        assert len(answer.citations) == 1
        assert answer.insufficient_note is None
        assert answer.gaps
    assert not answer_uses_model_knowledge(answer, allowed=True, is_fallback=False)


def test_composite_sections_and_points_are_requirement_bound():
    draft = KnowledgeAnswerDraft(
        points=[
            KnowledgeAnswerPointDraft(
                section="主要来源", text="甲醛是化合物", requirement_ids=["r1"]
            ),
            KnowledgeAnswerPointDraft(
                section="又一段来源", text="甲醛是化合物", requirement_ids=["r1"]
            ),
            KnowledgeAnswerPointDraft(
                text="旁支等级", requirement_ids=["r1"], answers_core_question=False
            ),
        ]
    )
    cleaned, _, invalid = _validated_draft_bindings(draft, _plan(), _execution("s1", 0))
    assert len(cleaned.points) == 1
    assert cleaned.points[0].section == "解释概念"
    assert invalid == 1


@pytest.mark.asyncio
async def test_merged_evidence_context_is_unique(monkeypatch):
    evidence = SimpleNamespace(
        entry_id=1,
        entry_title="来源",
        project_name="装修",
        node_path="材料",
        handle="ev_same",
        quote="胶水释放甲醛",
        source_title="材料手册",
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_response.resolve_evidence_handles",
        AsyncMock(return_value={"ev_same": evidence}),
    )
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id=f"q{i}",
                kind="retrieval",
                requirement_ids=[f"r{i}"],
                fingerprint=str(i),
                status="limited",
                evidence_handles=["ev_same"],
            )
            for i in (1, 2)
        ]
    )
    entries, bindings = await _answer_entries(None, 1, execution)
    assert len(entries[0]["evidences"]) == 1
    assert bindings == {"ev_same": ["r1", "r2"]}


def _repair_candidate(types=None):
    return {
        "target_requirement_ids": ["r2"],
        "structured_requests": [
            {
                "id": "repair",
                "requirement_ids": ["r2"],
                "entry_set": {
                    "semantic_query": "除醛治理方法",
                    "main_types": types or ["knowledge", "method"],
                },
                "outputs": [{"kind": "count"}],
            }
        ],
    }


def test_repair_cannot_broaden_statistics_filters():
    with pytest.raises(CoverageRepairPlanError, match="过滤口径"):
        normalize_coverage_repair_plan(
            _repair_candidate(["knowledge", "method", "reminder"]),
            original_plan=_plan(),
            eligible_requirement_ids={"r2"},
            scope_fingerprint="project-a",
            budget=CoverageRepairBudget(),
        )


@pytest.mark.asyncio
async def test_router_knows_composite_capabilities(monkeypatch):
    from app.agents.investigation import AnswerModeRouteDraft, run_answer_mode_router
    from app.services.knowledge_agent.investigation import resolve_answer_mode

    captured = {}

    class FakeAgent:
        def __init__(self, model, **kwargs):
            captured.update(kwargs)

        async def run(self, context):
            captured["context"] = context
            return SimpleNamespace(output=AnswerModeRouteDraft(mode="quick"))

    monkeypatch.setattr("app.agents.investigation.Agent", FakeAgent)
    monkeypatch.setattr(
        "app.agents.investigation.get_settings",
        lambda: Settings(
            _env_file=None,
            knowledge_agent_composite_answer_enabled=True,
        ),
    )
    monkeypatch.setattr(
        "app.agents.investigation.get_text_model",
        AsyncMock(
            return_value=SimpleNamespace(model_name="test"),
        ),
    )
    result, meta = await run_answer_mode_router(
        None,
        1,
        objective="解释甲醛、当前项目来源并统计治理方案",
        topic_summary="装修",
    )
    assert result.mode == "quick" and not meta.is_fallback
    assert "统计必须选择 quick" in captured["system_prompt"]
    assert "当前项目来源并统计" in captured["context"]
    # 能力调整不覆盖用户显式调查选择。
    explicit = await resolve_answer_mode(
        None,
        workspace_id=1,
        request_mode="investigate",
        objective="统计",
        topic_summary=None,
    )
    assert explicit.mode == "investigate" and explicit.meta is None


@pytest.mark.asyncio
async def test_composite_model_uses_small_output_contract(monkeypatch):
    from app.agents.knowledge_agent import CompositeKnowledgeAnswerDraft, run_knowledge_answer_agent

    class FakeAgent:
        def __init__(self, model, **kwargs):
            assert kwargs["output_type"] is CompositeKnowledgeAnswerDraft

        async def run(self, context):
            return SimpleNamespace(
                output=CompositeKnowledgeAnswerDraft(
                    points=[
                        KnowledgeAnswerPointDraft(text="解释", requirement_ids=["r1"]),
                    ]
                )
            )

    monkeypatch.setattr("app.agents.knowledge_agent.Agent", FakeAgent)
    monkeypatch.setattr(
        "app.agents.knowledge_agent.get_text_model",
        AsyncMock(
            return_value=SimpleNamespace(model_name="test"),
        ),
    )
    draft, meta = await run_knowledge_answer_agent(
        None,
        1,
        "解释并统计",
        "装修",
        [],
        allow_model_knowledge=True,
        composite_context={
            "current_message": "解释并统计",
            "standalone_query": "统计",
            "requirements": [],
            "evidence_requirements": {},
            "tool_facts": [],
            "execution_gaps": [],
            "retry_note": None,
        },
    )
    assert isinstance(draft, KnowledgeAnswerDraft)
    assert draft.points[0].text == "解释" and not meta.is_fallback


def test_repair_facts_keep_batches_and_immutable_baseline():
    original, repair, baseline = _execution("s1", 0), _execution("s2", 6), _baseline()
    merged = CompositeAnswerExecutionSnapshot(
        inputs=original.inputs + repair.inputs, tool_facts=original.tool_facts + repair.tool_facts
    )
    before = baseline.answer.model_dump()
    result = preserve_answer_with_repair_facts(baseline, _plan(), original, merged)
    assert baseline.answer.model_dump() == before
    assert result.answer.answer.count("0 条") == 1
    assert result.answer.answer.count("6 条") == 1
    assert "首次匹配" in result.answer.answer and "补查匹配" in result.answer.answer
    assert result.answer.gaps[0].startswith("补查后的回答整理失败")
    assert result.answer_basis.model_knowledge.used is True
    assert result.run_status == result.answer.status == "partial"
    assert label_repair_facts(_plan(), merged).tool_facts[0].summary == {"value": 0}
    assert original.tool_facts[0].text.startswith("本次")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "fallback", "interrupted", "budget"])
async def test_failed_resynthesis_retains_new_facts_on_recovery(monkeypatch, failure):
    from app.services.knowledge_agent.runner import _run_bounded_coverage_repair

    settings, budget, baseline = Settings(_env_file=None), CoverageRepairBudget(), _baseline()
    repair_plan = normalize_coverage_repair_plan(
        _repair_candidate(),
        original_plan=_plan(),
        eligible_requirement_ids={"r2"},
        scope_fingerprint="project-a",
        budget=budget,
    )
    snapshot = CoverageRepairSnapshot(
        stage="execution_ready",
        execution_mode="serial",
        frozen_budget=budget,
        eligible_requirement_ids=["r2"],
        baseline=coverage_repair_material_from_result(baseline),
        planner_attempted=True,
        synthesis_attempted=failure == "interrupted",
    )
    if failure == "budget":
        snapshot.frozen_budget.max_snapshot_bytes = len(
            snapshot.model_dump_json(exclude_none=True).encode("utf-8")
        ) + 250
    run = SimpleNamespace(
        id=1,
        workspace_id=1,
        owner_user_id=1,
        project_id=26,
        scope_type="project",
        coverage_repair_plan_json=dump_coverage_repair_plan(repair_plan, budget=budget),
        coverage_repair_execution_json=_execution("s2", 6).model_dump_json(),
    )
    for name in ("_check_cancelled", "update_run_step", "_record_server_fallback"):
        monkeypatch.setattr(f"app.services.knowledge_agent.runner.{name}", AsyncMock())
    build = (
        AsyncMock(side_effect=ValueError("结构化输出校验失败"))
        if failure == "exception"
        else AsyncMock(
            return_value=replace(baseline, answer_fallback=True),
        )
    )
    monkeypatch.setattr("app.services.knowledge_agent.runner.build_composite_answer", build)

    async def execute(control):
        return await _run_bounded_coverage_repair(
            SimpleNamespace(commit=AsyncMock()),
            run,
            None,
            _plan(),
            _execution("s1", 0),
            control,
            current_message="解释并统计",
            standalone_query="解释并统计",
            scope="房子装修",
            statement_context=[],
            settings=settings,
        )

    result = await execute(snapshot)
    restored = restore_coverage_repair_snapshot(run.coverage_repair_json)
    assert restored.stage == "failed"
    if failure == "budget":
        assert restored.final_result is None
        assert result == baseline
        assert "预算" in restored.error
    else:
        assert restored.final_result is not None
        assert "6 条" in result.answer.answer
    assert (await execute(restored)) == result
    assert build.await_count == (0 if failure == "interrupted" else 1)
    assert run.scope_type == "project" and run.project_id == 26
