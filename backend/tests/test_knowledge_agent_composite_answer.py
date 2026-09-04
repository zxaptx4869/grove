"""知识 Agent quick 复合回答计划与快照协议测试。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.composite_answer import CompositeAnswerPlanDraft
from app.agents.knowledge_agent import KnowledgeAnswerDraft, KnowledgeAnswerPointDraft
from app.core.config import Settings
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeAnswerPointOut,
    KnowledgeCompositeAnswerCoverageOut,
    KnowledgeCompositeAnswerPlanSummaryOut,
    KnowledgeRunCitationOut,
)
from app.services.knowledge_agent.basis import UserStatementCandidate, build_answer_basis
from app.services.knowledge_agent.composite_answer import (
    CompositeAnswerPlanError,
    composite_plan_summary,
    normalize_composite_answer_plan,
    plan_and_persist_composite_answer,
    restore_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_execution import (
    composite_request_fingerprint,
    execute_composite_answer_plan,
    restore_composite_execution,
    structured_result_tool_facts,
)
from app.services.knowledge_agent.composite_answer_projection import (
    composite_answer_out,
)
from app.services.knowledge_agent.composite_answer_response import (
    _derive_coverage,
    _validated_draft_bindings,
    build_composite_answer,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.structured_query_execution import (
    StructuredQueryExecutionResult,
)
from app.services.knowledge_agent.tools import (
    EvidenceReadItem,
    EvidenceReadOutput,
    ReadEntriesOutput,
    ReadEntryItem,
    RunToolContext,
    SearchResultItem,
    SearchToolOutput,
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


def test_composite_answer_draft_rejects_unbound_grove_requirement() -> None:
    """Grove 义务在模型输出阶段即触发可重试的 schema 校验。"""
    invalid = _candidate_plan()
    invalid["retrieval_requests"][0]["requirement_ids"] = ["definition"]

    with pytest.raises(ValidationError, match="要求 Grove，但没有关联只读输入"):
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


def test_composite_public_projection_omits_queries_handles_and_internal_prompt() -> None:
    """API 摘要只保留义务、状态和依据类型，不泄漏内部数据。"""
    plan = normalize_composite_answer_plan(_candidate_plan())
    execution = CompositeAnswerCoverageSnapshot(
        requirements=[
            {
                "requirement_id": "r1",
                "status": "partial",
                "evidence_handles": ["ev_" + "1" * 32],
                "result_handles": ["res_" + "2" * 24],
                "user_message_ids": [12],
                "model_knowledge_used": True,
                "note": "部分覆盖",
            },
            {
                "requirement_id": "r2",
                "status": "answered",
            },
        ]
    )
    public_plan, public_coverage = composite_answer_out(
        plan.model_dump_json(), execution.model_dump_json()
    )
    assert public_plan is not None and public_coverage is not None
    payload = public_plan.model_dump(mode="json")
    assert payload["input_kinds"] == ["retrieval"]
    assert "retrieval_requests" not in payload
    assert "prompt_version" not in payload
    coverage_payload = public_coverage.model_dump(mode="json")
    assert coverage_payload["requirements"][0]["basis_kinds"] == [
        "grove_evidence",
        "structured_result",
        "user_statement",
        "model_knowledge",
    ]
    assert "evidence_handles" not in coverage_payload["requirements"][0]
    assert "result_handles" not in coverage_payload["requirements"][0]


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

    async def _not_attempted(*args, **kwargs):
        return False

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
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer._composite_planning_already_attempted",
        _not_attempted,
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

    async def _not_attempted(*args, **kwargs):
        return False

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
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer._composite_planning_already_attempted",
        _not_attempted,
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

    async def _not_attempted(*args, **kwargs):
        return False

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
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer._composite_planning_already_attempted",
        _not_attempted,
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


@pytest.mark.asyncio
async def test_failed_composite_planning_is_not_repeated_on_recovery(monkeypatch) -> None:
    """规划 fallback 的调用记录是恢复控制状态，同一 Run 不再规划。"""
    planner_calls = 0
    planning_attempted = False

    async def _planner(*args, **kwargs):
        nonlocal planner_calls
        planner_calls += 1
        from app.services.knowledge_agent.observability import StageMeta

        return (
            None,
            StageMeta(
                purpose="composite_answer_plan",
                provider="llm",
                model="fake",
                is_fallback=True,
                error="规划失败",
                duration_ms=1,
            ),
        )

    async def _already_attempted(*args, **kwargs):
        return planning_attempted

    async def _record(*args, **kwargs):
        nonlocal planning_attempted
        planning_attempted = True

    class _Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.run_composite_answer_planner",
        _planner,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer._composite_planning_already_attempted",
        _already_attempted,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer.record_model_invocation",
        _record,
    )
    run = SimpleNamespace(
        id=10,
        workspace_id=1,
        request_basis_mode="auto",
        composite_answer_plan_json=None,
        planned_basis_strategy=None,
    )
    db = _Db()
    kwargs = {
        "current_message": "问题",
        "standalone_query": "问题",
        "scope_label": "全部知识",
        "context_decision": "new_topic",
        "topic_summary": None,
        "allowed_statements": [],
        "feature_enabled": True,
    }

    first = await plan_and_persist_composite_answer(db, run, **kwargs)
    second = await plan_and_persist_composite_answer(db, run, **kwargs)

    assert first is None and second is None
    assert planner_calls == 1
    assert db.commits == 1
    assert run.composite_answer_plan_json is None


def _multiple_input_plan():
    candidate = _candidate_plan()
    candidate["requirements"].append(
        {
            "id": "count",
            "order": 2,
            "summary": "统计知识数量",
            "kind": "aggregate",
            "basis_policy": "grove_only",
        }
    )
    candidate["retrieval_requests"].append(
        {
            "id": "search_definition",
            "query": "甲醛 定义",
            "requirement_ids": ["definition"],
        }
    )
    candidate["structured_requests"] = [
        {
            "id": "count_knowledge",
            "entry_set": {"main_types": ["knowledge"]},
            "outputs": [{"kind": "count"}],
            "requirement_ids": ["count"],
        }
    ]
    return normalize_composite_answer_plan(candidate)


@pytest.mark.asyncio
async def test_composite_execution_runs_inputs_in_order_and_reuses_checkpoints(
    monkeypatch,
) -> None:
    """多份输入严格串行；已提交指纹在恢复时不重放。"""
    plan = _multiple_input_plan()
    events: list[str] = []

    async def _search(db, ctx, query, **kwargs):
        events.append(f"search:{query}")
        entry_id = 1 if "来源" in query else 2
        ctx.discovered_entry_ids.add(entry_id)
        return SearchToolOutput(
            items=[
                SearchResultItem(
                    entry_id=entry_id,
                    title=f"知识{entry_id}",
                    project_name="项目",
                    node_path="根",
                    summary="摘要",
                    source_count=1,
                )
            ]
        )

    async def _read(db, ctx, entry_ids):
        events.append(f"read:{entry_ids[0]}")
        return ReadEntriesOutput(
            items=[
                ReadEntryItem(
                    entry_id=entry_ids[0],
                    title="知识",
                    content="内容",
                    project_name="项目",
                    node_path="根",
                    sources=[{"source_id": entry_ids[0]}],
                )
            ]
        )

    async def _evidence(db, ctx, entry_id, source_ids):
        events.append(f"evidence:{entry_id}")
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_ids[0],
                    evidence_handle=f"ev_{entry_id:032x}",
                    quote="原文",
                    citable=True,
                    status="completed",
                )
            ]
        )

    async def _structured(db, ctx, query_plan, *, cancel_check):
        await cancel_check()
        events.append("structured")
        return StructuredQueryExecutionResult(
            status="completed",
            set_completeness="complete",
            entries=None,
            count={"value": 2, "status": "completed", "completeness": "complete"},
            group_counts=[],
            output_completeness={"entries": None, "count": "complete", "group_count": {}},
            warnings=[],
        )

    async def _record(*args, **kwargs):
        return None

    class _Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _search,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_entries", _read
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_source_evidence",
        _evidence,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.execute_structured_query_plan",
        _structured,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.record_tool_result", _record
    )
    db = _Db()
    run = SimpleNamespace(id=71, composite_answer_execution_json=None)
    ctx = RunToolContext(
        run_id=71,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        project_id=None,
        project_name=None,
    )

    async def _not_cancelled():
        return None

    first = await execute_composite_answer_plan(
        db, run, ctx, plan, cancel_check=_not_cancelled
    )
    before_restore = list(events)
    second = await execute_composite_answer_plan(
        db, run, ctx, plan, cancel_check=_not_cancelled
    )

    assert events == [
        "search:甲醛 来源",
        "read:1",
        "evidence:1",
        "search:甲醛 定义",
        "read:2",
        "evidence:2",
        "structured",
    ]
    assert events == before_restore
    assert [item.request_id for item in first.snapshot.inputs] == ["q1", "q2", "s1"]
    assert second.snapshot == first.snapshot
    assert restore_composite_execution(run.composite_answer_execution_json) == first.snapshot
    assert db.commits == 3


@pytest.mark.asyncio
async def test_composite_retrieval_respects_total_object_and_evidence_budget(
    monkeypatch,
) -> None:
    """总对象/Evidence 预算用尽后，后续请求记录 limited 而不扩容。"""
    plan = _multiple_input_plan().model_copy(update={"structured_requests": []})
    search_calls = 0

    async def _search(db, ctx, query, **kwargs):
        nonlocal search_calls
        search_calls += 1
        ctx.discovered_entry_ids.add(1)
        return SearchToolOutput(
            items=[
                SearchResultItem(
                    entry_id=1,
                    title="知识",
                    project_name="项目",
                    node_path="",
                    summary="",
                    source_count=1,
                )
            ]
        )

    async def _read(db, ctx, entry_ids):
        return ReadEntriesOutput(
            items=[
                ReadEntryItem(
                    entry_id=1,
                    title="知识",
                    content="内容",
                    project_name="项目",
                    node_path="",
                    sources=[{"source_id": 1}],
                )
            ]
        )

    async def _evidence(db, ctx, entry_id, source_ids):
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=1,
                    source_id=1,
                    evidence_handle="ev_" + "1" * 32,
                    quote="原文",
                    citable=True,
                    status="completed",
                )
            ]
        )

    async def _record(*args, **kwargs):
        return None

    class _Db:
        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _search,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_entries", _read
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_source_evidence",
        _evidence,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.record_tool_result", _record
    )
    settings = Settings(
        knowledge_agent_composite_answer_max_entries=1,
        knowledge_agent_composite_answer_max_evidence=1,
    )
    run = SimpleNamespace(id=72, composite_answer_execution_json=None)
    ctx = RunToolContext(
        run_id=72,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        project_id=None,
        project_name=None,
    )

    async def _not_cancelled():
        return None

    result = await execute_composite_answer_plan(
        _Db(), run, ctx, plan, cancel_check=_not_cancelled, settings=settings
    )

    assert search_calls == 1
    assert result.snapshot.inputs[0].evidence_handles == ["ev_" + "1" * 32]
    assert result.snapshot.inputs[1].status == "limited"
    assert "预算" in (result.snapshot.inputs[1].error or "")


@pytest.mark.asyncio
async def test_composite_cancel_before_request_does_not_commit_late_checkpoint(
    monkeypatch,
) -> None:
    """请求边界取消直接中断，不执行工具也不提交迟到快照。"""
    plan = normalize_composite_answer_plan(_candidate_plan())

    async def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("取消后不应执行检索")

    class RunCancelled(Exception):
        pass

    async def _cancelled():
        raise RunCancelled()

    class _Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _forbidden,
    )
    run = SimpleNamespace(id=73, composite_answer_execution_json=None)
    ctx = RunToolContext(
        run_id=73,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        project_id=None,
        project_name=None,
    )
    db = _Db()

    with pytest.raises(RunCancelled):
        await execute_composite_answer_plan(
            db, run, ctx, plan, cancel_check=_cancelled
        )
    assert run.composite_answer_execution_json is None
    assert db.commits == 0


@pytest.mark.asyncio
async def test_composite_total_timeout_becomes_partial_checkpoint(monkeypatch) -> None:
    """总耗时预算用尽时保留并复用 partial 检查点。"""
    plan = normalize_composite_answer_plan(_candidate_plan())
    moments = iter([0.0, 2.0, 2.0])
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.monotonic",
        lambda: next(moments, 2.0),
    )

    async def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("超时后不应启动检索")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _forbidden,
    )

    class _Db:
        commits = 0

        async def commit(self):
            self.commits += 1

    async def _not_cancelled():
        return None

    run = SimpleNamespace(id=74, composite_answer_execution_json=None)
    ctx = RunToolContext(
        run_id=74,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        project_id=None,
        project_name=None,
    )
    db = _Db()
    result = await execute_composite_answer_plan(
        db,
        run,
        ctx,
        plan,
        cancel_check=_not_cancelled,
        settings=Settings(
            knowledge_agent_composite_answer_execution_timeout_seconds=1.0
        ),
    )
    assert result.snapshot.inputs[0].status == "partial"
    assert "耗时预算" in (result.snapshot.inputs[0].error or "")
    assert run.composite_answer_execution_json is not None
    restored = await execute_composite_answer_plan(
        db,
        run,
        ctx,
        plan,
        cancel_check=_not_cancelled,
        settings=Settings(
            knowledge_agent_composite_answer_execution_timeout_seconds=1.0
        ),
    )
    assert restored.snapshot == result.snapshot
    assert db.commits == 1


@pytest.mark.asyncio
async def test_composite_recovery_preserves_total_timeout_budget(monkeypatch) -> None:
    """恢复从已提交的累计耗时继续，不重置整体执行预算。"""
    plan = normalize_composite_answer_plan(_candidate_plan())
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.monotonic",
        lambda: 10.0,
    )

    async def _forbidden(*args, **kwargs):  # pragma: no cover
        raise AssertionError("累计耗时超限后不应执行检索")

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        _forbidden,
    )

    class _Db:
        async def commit(self):
            return None

    async def _not_cancelled():
        return None

    run = SimpleNamespace(
        id=75,
        composite_answer_execution_json=CompositeAnswerExecutionSnapshot(
            elapsed_ms=1_000
        ).model_dump_json(),
    )
    ctx = RunToolContext(
        run_id=75,
        workspace_id=1,
        owner_user_id=1,
        scope_type="workspace",
        project_id=None,
        project_name=None,
    )
    result = await execute_composite_answer_plan(
        _Db(),
        run,
        ctx,
        plan,
        cancel_check=_not_cancelled,
        settings=Settings(
            knowledge_agent_composite_answer_execution_timeout_seconds=1.0
        ),
    )

    assert result.snapshot.inputs[0].status == "partial"
    assert result.snapshot.elapsed_ms == 1_000
    assert "耗时预算" in (result.snapshot.inputs[0].error or "")


def test_composite_request_fingerprint_binds_run_plan_and_normalized_params() -> None:
    """指纹对 Run、计划版本和参数变化敏感，对键顺序稳定。"""
    plan = _multiple_input_plan()
    first = composite_request_fingerprint(
        1, plan, request_id="q1", kind="retrieval", params={"a": 1, "b": 2}
    )
    reordered = composite_request_fingerprint(
        1, plan, request_id="q1", kind="retrieval", params={"b": 2, "a": 1}
    )
    other_run = composite_request_fingerprint(
        2, plan, request_id="q1", kind="retrieval", params={"a": 1, "b": 2}
    )
    assert first == reordered
    assert first != other_run
    assert len(first) == 64


def test_structured_tool_fact_never_presents_limited_count_as_exact_total() -> None:
    """limited 统计只能使用有限结果措辞，complete 才能表达精确全集。"""
    request = _multiple_input_plan().structured_requests[0]
    complete = StructuredQueryExecutionResult(
        status="completed",
        set_completeness="complete",
        entries=None,
        count={"value": 8, "status": "completed", "completeness": "complete"},
        group_counts=[],
        output_completeness={"entries": None, "count": "complete", "group_count": {}},
        warnings=[],
    )
    limited = StructuredQueryExecutionResult(
        status="partial",
        set_completeness="limited",
        entries=None,
        count={"value": 8, "status": "limited", "completeness": "limited"},
        group_counts=[],
        output_completeness={"entries": None, "count": "limited", "group_count": {}},
        warnings=[],
    )
    exact_fact = structured_result_tool_facts(
        request, complete, fingerprint="a" * 64
    )[0]
    limited_fact = structured_result_tool_facts(
        request, limited, fingerprint="b" * 64
    )[0]
    assert exact_fact.text == "符合条件的知识条目共 8 条。"
    assert "不代表完整总数" in limited_fact.text


def test_composite_binding_rejects_grove_only_point_without_bound_basis() -> None:
    """grove_only 义务的无句柄模型文字不得通过校验。"""
    candidate = _candidate_plan()
    candidate["retrieval_requests"][0]["requirement_ids"] = [
        "definition",
        "sources",
    ]
    plan = normalize_composite_answer_plan(candidate, knowledge_only=True)
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r1", "r2"],
                fingerprint="a" * 64,
                status="empty",
                completeness="limited",
            )
        ]
    )
    draft = KnowledgeAnswerDraft(
        points=[
            KnowledgeAnswerPointDraft(
                text="模型自行生成的甲醛解释。",
                requirement_ids=["r2"],
            )
        ]
    )

    clean, missing, invalid_count = _validated_draft_bindings(
        draft, plan, execution
    )

    assert clean.points == []
    assert missing == ["r1", "r2"]
    assert invalid_count == 1


def test_composite_binding_cannot_borrow_evidence_from_another_requirement() -> None:
    """一个多义务 point 不能用 r1 证据冒充 r2 的 grove-required 依据。"""
    candidate = _candidate_plan()
    candidate["retrieval_requests"] = [
        {
            "id": "qa",
            "query": "甲醛定义",
            "requirement_ids": ["definition"],
        },
        {
            "id": "qb",
            "query": "甲醛来源",
            "requirement_ids": ["sources"],
        },
    ]
    plan = normalize_composite_answer_plan(candidate)
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r1"],
                fingerprint="a" * 64,
                status="completed",
                completeness="limited",
                evidence_handles=["ev_" + "1" * 32],
            ),
            CompositeExecutionInputSnapshot(
                request_id="q2",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="b" * 64,
                status="empty",
                completeness="limited",
            ),
        ]
    )
    draft = KnowledgeAnswerDraft(
        points=[
            KnowledgeAnswerPointDraft(
                text="同时回答两项。",
                requirement_ids=["r1", "r2"],
                evidence_handles=["ev_" + "1" * 32],
            )
        ]
    )
    clean, missing, invalid_count = _validated_draft_bindings(
        draft, plan, execution
    )
    assert clean.points == []
    assert missing == ["r1", "r2"]
    assert invalid_count == 1


def test_composite_coverage_does_not_borrow_evidence_across_requirements() -> None:
    """其他义务的 Citation 不得把无 Grove 依据的义务标记为 answered。"""
    candidate = _candidate_plan()
    candidate["retrieval_requests"] = [
        {
            "id": "qa",
            "query": "甲醛定义",
            "requirement_ids": ["definition"],
        },
        {
            "id": "qb",
            "query": "甲醛来源",
            "requirement_ids": ["sources"],
        },
    ]
    plan = normalize_composite_answer_plan(candidate)
    evidence_handle = "ev_" + "1" * 32
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r1"],
                fingerprint="a" * 64,
                status="completed",
                completeness="limited",
                evidence_handles=[evidence_handle],
            ),
            CompositeExecutionInputSnapshot(
                request_id="q2",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="b" * 64,
                status="empty",
                completeness="limited",
            ),
        ]
    )
    citation = KnowledgeRunCitationOut(
        evidence_id=1,
        evidence_handle=evidence_handle,
        entry_id=1,
        entry_title="甲醛定义",
        source_id=1,
        source_title="测试来源",
        quote="甲醛定义证据",
    )
    answer = KnowledgeAnswerOut(
        answer="分别回答两项。",
        status="partial",
        points=[
            KnowledgeAnswerPointOut(
                text="回答第一项。",
                requirement_ids=["r1"],
                citations=[citation],
            ),
            KnowledgeAnswerPointOut(
                text="模型补充第二项。",
                requirement_ids=["r2"],
            )
        ],
    )
    coverage = _derive_coverage(
        plan,
        execution,
        answer,
        answer_fallback=False,
    )

    assert coverage.requirements[0].status == "answered"
    assert coverage.requirements[1].status == "partial"
    assert coverage.requirements[1].evidence_handles == []


def test_composite_binding_removes_internal_handles_from_text() -> None:
    """义务与结果句柄只用于内部绑定，不得泄漏到回答正文。"""
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "a",
                    "order": 0,
                    "summary": "解释概念",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [],
            "reason": "概念解释",
        }
    )
    draft = KnowledgeAnswerDraft(
        points=[
            KnowledgeAnswerPointDraft(
                text="r1 的结论见 res_111111111111111111111111。",
                requirement_ids=["r1"],
            )
        ]
    )
    clean, missing, invalid_count = _validated_draft_bindings(
        draft, plan, CompositeAnswerExecutionSnapshot()
    )
    assert missing == []
    assert invalid_count == 0
    assert clean.points[0].text == "的结论见 。"


def test_composite_binding_rejects_model_numeric_rewrite_of_tool_fact() -> None:
    """绑定统计义务的模型文字不得另行重写数字结果。"""
    plan = _multiple_input_plan()
    fact = CompositeToolFact(
        handle="res_" + "3" * 24,
        request_id="s1",
        requirement_ids=["r3"],
        kind="count",
        text="符合条件的知识条目共 8 条。",
        completeness="complete",
        summary={"value": 8},
    )
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="s1",
                kind="structured",
                requirement_ids=["r3"],
                fingerprint="c" * 64,
                status="completed",
                completeness="complete",
                result_handles=[fact.handle],
            )
        ],
        tool_facts=[fact],
    )
    draft = KnowledgeAnswerDraft(
        points=[
            KnowledgeAnswerPointDraft(
                text="统计结果是 9 条。",
                requirement_ids=["r3"],
                result_handles=[fact.handle],
            )
        ]
    )
    clean, missing, invalid_count = _validated_draft_bindings(
        draft, plan, execution
    )
    assert clean.points == []
    # 义务仍由服务端 fact 覆盖，不会因丢弃冲突 point 而遗漏。
    assert missing == ["r1", "r2"]
    assert invalid_count == 1


def test_composite_answer_basis_counts_structured_fact_as_grove_usage() -> None:
    """结构化事实没有 Citation，但实际依据仍必须标记 Grove 已使用。"""
    answer = KnowledgeAnswerOut(
        answer="符合条件的知识条目共 8 条。",
        status="completed",
    )
    basis = build_answer_basis(
        answer=answer,
        user_statement_ids=[],
        model_knowledge_used=False,
        external_material_required=False,
        grove_result_used=True,
    )
    assert basis.grove.used is True
    assert basis.grove.citation_count == 0


def test_composite_coverage_marks_limited_aggregate_partial() -> None:
    """有 tool fact 不等于精确完成；limited 统计必须导出 partial。"""
    plan = _multiple_input_plan()
    fact = CompositeToolFact(
        handle="res_" + "1" * 24,
        request_id="s1",
        requirement_ids=["r3"],
        kind="count",
        text="本次匹配中可确认 8 条；不代表完整总数。",
        completeness="limited",
        summary={"value": 8},
    )
    execution = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="s1",
                kind="structured",
                requirement_ids=["r3"],
                fingerprint="b" * 64,
                status="limited",
                completeness="limited",
                result_handles=[fact.handle],
            )
        ],
        tool_facts=[fact],
    )
    answer = KnowledgeAnswerOut(
        answer=fact.text,
        status="partial",
        points=[
            KnowledgeAnswerPointOut(
                text=fact.text,
                requirement_ids=["r3"],
            )
        ],
    )
    coverage = _derive_coverage(
        plan, execution, answer, answer_fallback=False
    )
    row = next(item for item in coverage.requirements if item.requirement_id == "r3")
    assert row.status == "partial"
    assert "部分结果" in (row.note or "")


@pytest.mark.asyncio
async def test_composite_answer_retries_once_for_omitted_requirement(monkeypatch) -> None:
    """首次遗漏义务时只重试相同输入的回答，不重跑工具。"""
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "a",
                    "order": 0,
                    "summary": "解释甲醛是什么",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                },
                {
                    "id": "b",
                    "order": 1,
                    "summary": "说明一般健康影响",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [],
            "reason": "两项通用解释",
        }
    )
    calls: list[dict] = []

    async def _entries(*args, **kwargs):
        return [], {}

    async def _agent(*args, **kwargs):
        from app.services.knowledge_agent.observability import StageMeta

        calls.append(kwargs["composite_context"])
        points = [
            KnowledgeAnswerPointDraft(text="甲醛是一种化合物。", requirement_ids=["r1"])
        ]
        if len(calls) == 2:
            points.append(
                KnowledgeAnswerPointDraft(
                    text="较高暴露可引起刺激。", requirement_ids=["r2"]
                )
            )
        return (
            KnowledgeAnswerDraft(lead="简要说明。", points=points),
            StageMeta(
                purpose="answer",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    async def _validated(db, run_id, draft, **kwargs):
        return (
            KnowledgeAnswerOut(
                answer="",
                status="completed",
                points=[
                    KnowledgeAnswerPointOut(
                        text=point.text,
                        requirement_ids=point.requirement_ids,
                    )
                    for point in draft.points
                ],
            ),
            SimpleNamespace(),
        )

    async def _record(*args, **kwargs):
        return None

    class _Db:
        async def commit(self):
            return None

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_response._answer_entries", _entries
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_response.run_knowledge_answer_agent",
        _agent,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_response.build_validated_answer",
        _validated,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_response.record_model_invocation",
        _record,
    )

    async def _not_cancelled():
        return None

    result = await build_composite_answer(
        _Db(),
        SimpleNamespace(id=81, workspace_id=1),
        plan,
        CompositeAnswerExecutionSnapshot(),
        current_message="甲醛是什么，对健康有什么影响？",
        standalone_query="甲醛定义与健康影响",
        scope_label="全部知识",
        statement_context=[],
        cancel_check=_not_cancelled,
    )

    assert len(calls) == 2
    assert calls[0]["current_message"].startswith("甲醛是什么")
    assert calls[0]["standalone_query"] == "甲醛定义与健康影响"
    assert calls[1]["retry_note"] is not None
    assert [item.status for item in result.coverage.requirements] == [
        "answered",
        "answered",
    ]
    assert result.answer.status == "completed"
