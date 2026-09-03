"""知识 Agent quick 复合回答计划与快照协议测试。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.composite_answer import CompositeAnswerPlanDraft
from app.core.config import Settings
from app.schemas.knowledge_agent import (
    KnowledgeAnswerPointOut,
    KnowledgeCompositeAnswerCoverageOut,
    KnowledgeCompositeAnswerPlanSummaryOut,
)
from app.services.knowledge_agent.basis import UserStatementCandidate
from app.services.knowledge_agent.composite_answer import (
    CompositeAnswerPlanError,
    composite_plan_summary,
    normalize_composite_answer_plan,
    plan_and_persist_composite_answer,
    restore_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
)


def _candidate_plan() -> dict:
    return {
        "schema_version": "v1",
        "requirements": [
            {
                "id": "definition",
                "order": 0,
                "summary": "解释甲醛是什么",
                "kind": "explain",
                "basis_policy": "model_allowed",
            },
            {
                "id": "sources",
                "order": 1,
                "summary": "结合个人知识说明甲醛来源",
                "kind": "retrieve",
                "basis_policy": "grove_required",
            },
        ],
        "statement_message_ids": [12],
        "retrieval_requests": [
            {
                "id": "search_sources",
                "query": "甲醛 来源",
                "requirement_ids": ["sources"],
            }
        ],
        "structured_requests": [],
        "reason": "概念解释与个人知识需要不同依据",
    }


def test_composite_answer_draft_uses_closed_bounded_schema() -> None:
    """候选协议允许多义务，但拒绝未知字段、未知枚举和越界列表。"""
    plan = CompositeAnswerPlanDraft.model_validate(_candidate_plan())
    assert [item.id for item in plan.requirements] == ["definition", "sources"]
    assert plan.retrieval_requests[0].requirement_ids == ["sources"]

    invalid = _candidate_plan()
    invalid["workspace_id"] = 999
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)

    invalid = _candidate_plan()
    invalid["requirements"][0]["basis_policy"] = "browse_everything"
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)

    invalid = _candidate_plan()
    invalid["requirements"] = invalid["requirements"] * 5
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)


def test_composite_execution_and_coverage_snapshots_reject_unknown_fields() -> None:
    """恢复快照同样使用闭合 schema，历史 JSON 不能扩大解释。"""
    execution = CompositeAnswerExecutionSnapshot.model_validate(
        {
            "schema_version": "v1",
            "inputs": [
                {
                    "request_id": "search_sources",
                    "kind": "retrieval",
                    "requirement_ids": ["r2"],
                    "fingerprint": "a" * 64,
                    "status": "completed",
                    "completeness": "limited",
                    "entry_ids": [1],
                    "evidence_handles": ["ev_12345678"],
                }
            ],
            "tool_facts": [],
        }
    )
    assert execution.inputs[0].request_id == "search_sources"

    with pytest.raises(ValidationError):
        CompositeAnswerExecutionSnapshot.model_validate(
            {"schema_version": "v1", "inputs": [], "tool_facts": [], "scope": "all"}
        )

    coverage = CompositeAnswerCoverageSnapshot.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "requirement_id": "r1",
                    "status": "answered",
                    "model_knowledge_used": True,
                }
            ],
        }
    )
    assert coverage.requirements[0].status == "answered"


def test_public_composite_fields_are_optional_and_legacy_points_remain_valid() -> None:
    """新增字段为可选；旧 point 可读取，新 point 可保留义务绑定。"""
    legacy = KnowledgeAnswerPointOut.model_validate(
        {"section": "定义", "text": "甲醛是一种挥发性有机化合物。"}
    )
    assert legacy.requirement_ids == []

    current = KnowledgeAnswerPointOut.model_validate(
        {
            "section": "定义",
            "text": "甲醛是一种挥发性有机化合物。",
            "requirement_ids": ["r1"],
        }
    )
    assert current.requirement_ids == ["r1"]

    plan = KnowledgeCompositeAnswerPlanSummaryOut.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "r1",
                    "order": 0,
                    "summary": "解释甲醛是什么",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ],
            "input_kinds": [],
        }
    )
    assert plan.requirements[0].id == "r1"

    public_coverage = KnowledgeCompositeAnswerCoverageOut.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "requirement_id": "r1",
                    "summary": "解释甲醛是什么",
                    "status": "answered",
                    "basis_kinds": ["model_knowledge"],
                }
            ],
        }
    )
    assert public_coverage.requirements[0].basis_kinds == ["model_knowledge"]


def test_normalize_composite_plan_stabilizes_ids_and_drops_unknown_statements() -> None:
    """服务端重编号义务/请求，只保留白名单用户消息句柄。"""
    candidate = _candidate_plan()
    candidate["requirements"][0]["order"] = 2
    candidate["requirements"][1]["order"] = 1
    candidate["statement_message_ids"] = [12, 999, 12]

    plan = normalize_composite_answer_plan(
        candidate,
        allowed_statement_ids={12},
    )

    assert [item.id for item in plan.requirements] == ["r1", "r2"]
    assert [item.summary for item in plan.requirements] == [
        "结合个人知识说明甲醛来源",
        "解释甲醛是什么",
    ]
    assert plan.retrieval_requests[0].id == "q1"
    assert plan.retrieval_requests[0].requirement_ids == ["r1"]
    assert plan.statement_message_ids == [12]
    assert composite_plan_summary(plan)["input_kinds"] == ["retrieval"]
    assert restore_composite_answer_plan(plan.model_dump_json()) == plan


def test_normalize_composite_plan_rejects_unknown_links_and_server_budget() -> None:
    """未知义务关联和服务端预算超限均整体拒绝，不静默删语义。"""
    unknown = _candidate_plan()
    unknown["retrieval_requests"][0]["requirement_ids"] = ["missing"]
    with pytest.raises(CompositeAnswerPlanError, match="未知回答义务"):
        normalize_composite_answer_plan(unknown)

    with pytest.raises(CompositeAnswerPlanError, match="回答义务数"):
        normalize_composite_answer_plan(
            _candidate_plan(),
            settings=Settings(knowledge_agent_composite_answer_max_requirements=1),
        )


def test_normalize_composite_plan_knowledge_only_requires_grove_for_every_item() -> None:
    """knowledge_only 会收紧全部义务，缺少 Grove 输入时拒绝候选。"""
    with pytest.raises(CompositeAnswerPlanError, match="要求 Grove"):
        normalize_composite_answer_plan(_candidate_plan(), knowledge_only=True)

    candidate = _candidate_plan()
    candidate["retrieval_requests"][0]["requirement_ids"] = [
        "definition",
        "sources",
    ]
    plan = normalize_composite_answer_plan(candidate, knowledge_only=True)
    assert {item.basis_policy for item in plan.requirements} == {"grove_only"}
    assert plan.retrieval_requests[0].requirement_ids == ["r1", "r2"]


@pytest.mark.asyncio
async def test_plan_and_persist_composite_answer_reuses_snapshot(monkeypatch) -> None:
    """首次计划在工具前固化；再次调用只恢复，不重复规划。"""
    calls = 0

    async def _planner(*args, **kwargs):
        nonlocal calls
        calls += 1
        from app.services.knowledge_agent.observability import StageMeta

        return (
            CompositeAnswerPlanDraft.model_validate(_candidate_plan()),
            StageMeta(
                purpose="composite_answer_plan",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    recorded = []

    async def _record(*args, **kwargs):
        recorded.append(kwargs)

    class _Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _planner,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.record_model_invocation",
        _record,
    )
    run = SimpleNamespace(
        id=7,
        workspace_id=1,
        request_basis_mode="auto",
        composite_answer_plan_json=None,
        planned_basis_strategy=None,
    )
    db = _Db()
    statements = [UserStatementCandidate(message_id=12, content="我的装修记录")]

    first = await plan_and_persist_composite_answer(
        db,
        run,
        current_message="结合我的知识库说明甲醛",
        standalone_query="甲醛是什么以及来源",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary="甲醛",
        allowed_statements=statements,
        feature_enabled=True,
    )
    second = await plan_and_persist_composite_answer(
        db,
        run,
        current_message="不应改变",
        standalone_query="不应改变",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary=None,
        allowed_statements=[],
        feature_enabled=True,
    )

    assert first is not None and second == first
    assert calls == 1
    assert len(recorded) == 1
    assert db.commits == 1
    assert run.planned_basis_strategy == "hybrid"


@pytest.mark.asyncio
async def test_composite_feature_disabled_does_not_call_planner(monkeypatch) -> None:
    """开关关闭时不制造一次模型调用或 fallback。"""
    async def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("特性关闭不应调用复合规划器")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _forbidden,
    )
    run = SimpleNamespace(composite_answer_plan_json=None)
    result = await plan_and_persist_composite_answer(
        object(),
        run,
        current_message="问题",
        standalone_query="问题",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary=None,
        allowed_statements=[],
        feature_enabled=False,
    )
    assert result is None


@pytest.mark.asyncio
async def test_natural_knowledge_only_is_passed_to_planner_and_hard_enforced(
    monkeypatch,
) -> None:
    """自然语言严格限制既进入提示，也在服务端把全部义务收紧。"""
    captured: dict[str, bool] = {}

    async def _planner(*args, **kwargs):
        from app.services.knowledge_agent.observability import StageMeta

        captured["knowledge_only"] = kwargs["knowledge_only"]
        candidate = _candidate_plan()
        candidate["retrieval_requests"][0]["requirement_ids"] = [
            "definition",
            "sources",
        ]
        return (
            CompositeAnswerPlanDraft.model_validate(candidate),
            StageMeta(
                purpose="composite_answer_plan",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    async def _record(*args, **kwargs):
        return None

    class _Db:
        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _planner,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.record_model_invocation",
        _record,
    )
    run = SimpleNamespace(
        id=8,
        workspace_id=1,
        request_basis_mode="auto",
        composite_answer_plan_json=None,
        planned_basis_strategy=None,
    )
    plan = await plan_and_persist_composite_answer(
        _Db(),
        run,
        current_message="只根据我的知识库回答甲醛是什么和来源",
        standalone_query="甲醛是什么和来源",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary="甲醛",
        allowed_statements=[],
        feature_enabled=True,
    )

    assert captured["knowledge_only"] is True
    assert plan is not None
    assert {item.basis_policy for item in plan.requirements} == {"grove_only"}
    assert run.planned_basis_strategy == "knowledge_only"


@pytest.mark.asyncio
async def test_invalid_composite_candidate_records_explicit_fallback(monkeypatch) -> None:
    """候选无法满足 Grove 义务时不固化，调用记录明确变为 fallback。"""
    async def _planner(*args, **kwargs):
        from app.services.knowledge_agent.observability import StageMeta

        return (
            CompositeAnswerPlanDraft.model_validate(_candidate_plan()),
            StageMeta(
                purpose="composite_answer_plan",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    recorded = []

    async def _record(*args, **kwargs):
        recorded.append(kwargs["meta"])

    class _Db:
        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _planner,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.record_model_invocation",
        _record,
    )
    run = SimpleNamespace(
        id=9,
        workspace_id=1,
        request_basis_mode="knowledge_only",
        composite_answer_plan_json=None,
        planned_basis_strategy=None,
    )
    plan = await plan_and_persist_composite_answer(
        _Db(),
        run,
        current_message="问题",
        standalone_query="问题",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary=None,
        allowed_statements=[],
        feature_enabled=True,
    )

    assert plan is None
    assert run.composite_answer_plan_json is None
    assert recorded[0].is_fallback is True
    assert "要求 Grove" in (recorded[0].error or "")
