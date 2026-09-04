"""共享执行图的等价性、实际复用收益与安全门禁评估。"""

import asyncio
from collections import Counter

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models import (
    Candidate,
    Extraction,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeCandidateDraft,
    KnowledgeConversation,
    KnowledgeWorkingSetItem,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    RUN_COMPLETED,
    RUN_PROCESSING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.basis import build_answer_basis
from app.services.knowledge_agent.composite_answer import (
    CompositeAnswerPlanError,
    normalize_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_execution import execute_composite_answer_plan
from app.services.knowledge_agent.composite_answer_response import _derive_coverage
from app.services.knowledge_agent.shared_execution_graph import (
    GraphNode,
    NodeOutcome,
    compile_shared_execution_graph,
    execute_shared_execution_graph_plan,
    run_graph_scheduler,
    run_scope_fingerprint,
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
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


async def _never_cancel() -> None:
    return None


async def _create_run(db, user, workspace, *, project=None) -> KnowledgeAgentRun:
    scope_type = SCOPE_PROJECT if project is not None else SCOPE_WORKSPACE
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=scope_type,
        project_id=project.id if project is not None else None,
        title="共享图评估",
    )
    db.add(conversation)
    await db.flush()
    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=scope_type,
        project_id=project.id if project is not None else None,
        project_name=project.name if project is not None else None,
        status=RUN_PROCESSING,
        active_slot=ACTIVE_SLOT,
    )
    db.add(run)
    await db.flush()
    return run


def _context(run: KnowledgeAgentRun) -> RunToolContext:
    return RunToolContext(
        run_id=run.id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
    )


def _retrieval_plan(*, duplicate: bool = True, second_query: str | None = None):
    requirements = [
        {
            "id": "source",
            "order": 0,
            "summary": "说明来源",
            "kind": "retrieve",
            "basis_policy": "grove_required",
        }
    ]
    requests = [
        {"id": "first", "query": "甲醛 来源", "requirement_ids": ["source"]}
    ]
    if duplicate or second_query is not None:
        requirements.append(
            {
                "id": "risk",
                "order": 1,
                "summary": "说明风险",
                "kind": "retrieve",
                "basis_policy": "grove_required",
            }
        )
        requests.append(
            {
                "id": "second",
                "query": second_query or "甲醛 来源",
                "requirement_ids": ["risk"],
            }
        )
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": requirements,
            "statement_message_ids": [],
            "retrieval_requests": requests,
            "structured_requests": [],
        }
    )


def _structured_plan():
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "groups",
                    "order": 1,
                    "summary": "按性质分组",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "latest",
                    "order": 2,
                    "summary": "列出最近知识",
                    "kind": "retrieve",
                    "basis_policy": "grove_only",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "summary",
                    "entry_set": {},
                    "outputs": [
                        {"kind": "count"},
                        {"kind": "group_count", "group_by": "info_nature"},
                        {
                            "kind": "entries",
                            "limit": 10,
                            "sort": {"field": "updated_at", "direction": "desc"},
                        },
                    ],
                    "requirement_ids": ["count", "groups", "latest"],
                }
            ],
        }
    )


def _input_semantics(snapshot) -> list[dict]:
    return [
        {
            "request_id": item.request_id,
            "kind": item.kind,
            "requirement_ids": item.requirement_ids,
            "status": item.status,
            "completeness": item.completeness,
            "entry_ids": item.entry_ids,
            "evidence_handles": item.evidence_handles,
            "error": item.error,
        }
        for item in snapshot.inputs
    ]


def _fact_semantics(snapshot) -> list[dict]:
    return sorted(
        [
            {
                "request_id": fact.request_id,
                "requirement_ids": fact.requirement_ids,
                "kind": fact.kind,
                "text": fact.text,
                "completeness": fact.completeness,
                "summary": fact.summary,
            }
            for fact in snapshot.tool_facts
        ],
        key=lambda item: item["kind"],
    )


def _coverage_semantics(coverage) -> list[dict]:
    """忽略执行器内部句柄值，只比较对外覆盖含义与依据数量。"""
    return [
        {
            "requirement_id": item.requirement_id,
            "status": item.status,
            "evidence_count": len(item.evidence_handles),
            "result_count": len(item.result_handles),
            "user_message_ids": item.user_message_ids,
            "model_knowledge_used": item.model_knowledge_used,
            "note": item.note,
        }
        for item in coverage.requirements
    ]


@pytest.mark.asyncio
async def test_equivalence_retrieval_keeps_evidence_and_reduces_actual_calls(
    monkeypatch,
) -> None:
    """同一固化计划下，共享图保留串行语义并把重复底层读取从两次降为一次。"""
    plan = _retrieval_plan()
    phase = "serial"
    calls: Counter[tuple[str, str]] = Counter()

    async def search(*args, **kwargs):
        del args, kwargs
        calls[(phase, "search")] += 1
        return SearchToolOutput(
            items=[
                SearchResultItem(
                    entry_id=9,
                    title="甲醛",
                    project_name="装修",
                    node_path="材料",
                    summary="甲醛可能来自板材。",
                    source_count=1,
                )
            ]
        )

    async def read(*args, **kwargs):
        del args, kwargs
        calls[(phase, "read")] += 1
        return ReadEntriesOutput(
            items=[
                ReadEntryItem(
                    entry_id=9,
                    title="甲醛",
                    content="甲醛可能来自板材。",
                    project_name="装修",
                    node_path="材料",
                    sources=[{"source_id": 33}],
                )
            ]
        )

    async def evidence(*args, **kwargs):
        del args, kwargs
        calls[(phase, "evidence")] += 1
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=9,
                    source_id=33,
                    evidence_handle="ev_equivalent",
                    quote="甲醛可能来自板材",
                    citable=True,
                    status="completed",
                )
            ]
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.search_confirmed_knowledge",
        search,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_entries", read
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_source_evidence",
        evidence,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.tools.search_confirmed_knowledge", search
    )
    monkeypatch.setattr("app.services.knowledge_agent.tools.read_entries", read)
    monkeypatch.setattr("app.services.knowledge_agent.tools.read_source_evidence", evidence)

    async with async_session_factory() as db:
        user = await create_user(db, "检索等价")
        workspace = await create_workspace(db, user)
        serial_run = await _create_run(db, user, workspace)
        graph_run = await _create_run(db, user, workspace)
        await db.commit()
        serial = await execute_composite_answer_plan(
            db,
            serial_run,
            _context(serial_run),
            plan,
            cancel_check=_never_cancel,
        )
        phase = "graph"
        graph = await execute_shared_execution_graph_plan(
            db,
            graph_run,
            _context(graph_run),
            plan,
            cancel_check=_never_cancel,
        )

    assert _input_semantics(graph.snapshot) == _input_semantics(serial.snapshot)
    assert calls[("serial", "search")] == 2
    assert calls[("serial", "read")] == 2
    assert calls[("serial", "evidence")] == 2
    assert calls[("graph", "search")] == 1
    assert calls[("graph", "read")] == 1
    assert calls[("graph", "evidence")] == 1


@pytest.mark.asyncio
async def test_equivalence_structured_count_group_list_matches_serial() -> None:
    """共享集合上的 count/group/list 保持既有 tool fact 和完整性语义。"""
    plan = _structured_plan()
    async with async_session_factory() as db:
        user = await create_user(db, "结构化等价")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "装修")
        node = await create_child_node(db, project, "材料")
        source, attachment = await create_source_attachment(
            db, workspace, project, text_content="材料经验与事实"
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="材料事实",
            content="材料事实",
            quote="材料事实",
            info_nature="fact",
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="材料经验",
            content="材料经验",
            quote="材料经验",
            info_nature="experience",
        )
        serial_run = await _create_run(db, user, workspace)
        graph_run = await _create_run(db, user, workspace)
        await db.commit()
        serial = await execute_composite_answer_plan(
            db,
            serial_run,
            _context(serial_run),
            plan,
            cancel_check=_never_cancel,
        )
        graph = await execute_shared_execution_graph_plan(
            db,
            graph_run,
            _context(graph_run),
            plan,
            cancel_check=_never_cancel,
        )
        serial_calls = int(
            (
                await db.execute(
                    select(func.count(KnowledgeAgentToolCall.id)).where(
                        KnowledgeAgentToolCall.run_id == serial_run.id
                    )
                )
            ).scalar_one()
        )
        graph_calls = int(
            (
                await db.execute(
                    select(func.count(KnowledgeAgentToolCall.id)).where(
                        KnowledgeAgentToolCall.run_id == graph_run.id
                    )
                )
            ).scalar_one()
        )

    assert _input_semantics(graph.snapshot) == _input_semantics(serial.snapshot)
    assert _fact_semantics(graph.snapshot) == _fact_semantics(serial.snapshot)
    assert serial_calls == graph_calls == 3
    empty_answer = KnowledgeAnswerOut(answer="", status="completed")
    serial_coverage = _derive_coverage(
        plan, serial.snapshot, empty_answer, answer_fallback=False
    )
    graph_coverage = _derive_coverage(
        plan, graph.snapshot, empty_answer, answer_fallback=False
    )
    assert _coverage_semantics(graph_coverage) == _coverage_semantics(serial_coverage)
    assert {item.status for item in graph_coverage.requirements} == {"answered"}
    serial_basis = build_answer_basis(
        answer=empty_answer,
        user_statement_ids=[],
        model_knowledge_used=False,
        external_material_required=False,
        grove_result_used=bool(serial.snapshot.tool_facts),
    )
    graph_basis = build_answer_basis(
        answer=empty_answer,
        user_statement_ids=[],
        model_knowledge_used=False,
        external_material_required=False,
        grove_result_used=bool(graph.snapshot.tool_facts),
    )
    assert graph_basis == serial_basis
    final_status = (
        RUN_COMPLETED
        if all(item.status == "answered" for item in graph_coverage.requirements)
        else "partial"
    )
    assert final_status == RUN_COMPLETED


def test_guardrail_scope_fingerprint_binds_workspace_project_and_run() -> None:
    """相同计划不能跨 Run、Workspace 或项目得到同一节点/result handle。"""
    plan = _retrieval_plan(duplicate=False)
    scopes = [
        run_scope_fingerprint(
            run_id=1,
            owner_user_id=1,
            workspace_id=10,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
        run_scope_fingerprint(
            run_id=2,
            owner_user_id=1,
            workspace_id=10,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
        run_scope_fingerprint(
            run_id=3,
            owner_user_id=1,
            workspace_id=11,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
        run_scope_fingerprint(
            run_id=4,
            owner_user_id=1,
            workspace_id=10,
            project_id=20,
            scope_type=SCOPE_PROJECT,
        ),
    ]
    graphs = [compile_shared_execution_graph(plan, scope_fingerprint=scope) for scope in scopes]
    assert len(set(scopes)) == 4
    assert len({graph.nodes[0].fingerprint for graph in graphs}) == 4


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("root", "workspace_id", 99),
        ("root", "parallelism", 8),
        ("request", "node_id", "n1"),
        ("request", "depends_on", ["n2"]),
        ("request", "candidate_id", 7),
        ("request", "draft_id", 8),
        ("request", "extraction_id", 9),
        ("request", "write_operation", "create_entry"),
    ],
)
def test_guardrail_rejects_graph_control_and_write_inputs(target, field, value) -> None:
    """模型/客户端不能把范围、图控制字段或候选写对象带入可执行计划。"""
    payload = {
        "schema_version": "v1",
        "requirements": [
            {
                "id": "source",
                "order": 0,
                "summary": "说明来源",
                "kind": "retrieve",
                "basis_policy": "grove_required",
            }
        ],
        "statement_message_ids": [],
        "retrieval_requests": [
            {"id": "first", "query": "甲醛", "requirement_ids": ["source"]}
        ],
        "structured_requests": [],
    }
    if target == "root":
        payload[field] = value
    else:
        payload["retrieval_requests"][0][field] = value
    with pytest.raises((CompositeAnswerPlanError, ValidationError)):
        normalize_composite_answer_plan(payload)


@pytest.mark.parametrize("kind", ["unknown", "write_entry", "create_candidate"])
def test_guardrail_rejects_unknown_and_write_graph_nodes(kind: str) -> None:
    with pytest.raises(ValidationError):
        GraphNode.model_validate(
            {
                "id": "n1",
                "kind": kind,
                "fingerprint": "a" * 64,
                "canonical_key": "forbidden",
            }
        )


@pytest.mark.asyncio
async def test_guardrail_workspace_project_scope_and_no_knowledge_writes() -> None:
    """查询只读取 Run 范围内正式 Entry，且不创建候选、抽取、草稿或工作集。"""
    plan = normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                }
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "summary",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["count"],
                }
            ],
        }
    )
    async with async_session_factory() as db:
        user = await create_user(db, "范围门禁")
        workspace = await create_workspace(db, user)
        first_project = await create_project(db, workspace, "项目一")
        second_project = await create_project(db, workspace, "项目二")
        first_node = await create_child_node(db, first_project, "一")
        second_node = await create_child_node(db, second_project, "二")
        source_one, attachment_one = await create_source_attachment(
            db, workspace, first_project, text_content="一"
        )
        source_two, attachment_two = await create_source_attachment(
            db, workspace, second_project, text_content="二"
        )
        await create_entry_with_evidence(
            db, first_project, first_node, source_one, attachment_one, title="一"
        )
        await create_entry_with_evidence(
            db, second_project, second_node, source_two, attachment_two, title="二一"
        )
        await create_entry_with_evidence(
            db, second_project, second_node, source_two, attachment_two, title="二二"
        )
        project_run = await _create_run(db, user, workspace, project=first_project)
        workspace_run = await _create_run(db, user, workspace)
        await db.commit()
        guarded_models = (
            Candidate,
            Extraction,
            KnowledgeCandidateDraft,
            KnowledgeWorkingSetItem,
        )
        write_counts_before = {
            model.__name__: int((await db.execute(select(func.count(model.id)))).scalar_one())
            for model in guarded_models
        }
        project_result = await execute_shared_execution_graph_plan(
            db,
            project_run,
            _context(project_run),
            plan,
            cancel_check=_never_cancel,
        )
        workspace_result = await execute_shared_execution_graph_plan(
            db,
            workspace_run,
            _context(workspace_run),
            plan,
            cancel_check=_never_cancel,
        )
        write_counts = {
            model.__name__: int((await db.execute(select(func.count(model.id)))).scalar_one())
            for model in guarded_models
        }

    assert project_result.snapshot.tool_facts[0].summary == {"value": 1}
    assert workspace_result.snapshot.tool_facts[0].summary == {"value": 3}
    assert write_counts == write_counts_before


def test_distinct_similar_queries_are_not_merged() -> None:
    graph = compile_shared_execution_graph(
        _retrieval_plan(duplicate=False, second_query="甲醛 风险"),
        scope_fingerprint=run_scope_fingerprint(
            run_id=1,
            owner_user_id=1,
            workspace_id=2,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
    )
    semantic_nodes = [node for node in graph.nodes if node.kind == "semantic_entry_set"]
    assert len(semantic_nodes) == 2
    assert len({node.fingerprint for node in semantic_nodes}) == 2


@pytest.mark.asyncio
async def test_parallel_independent_outputs_reach_configured_concurrency() -> None:
    """并发收益以实际重叠执行证明，不依赖易波动的总墙钟阈值。"""
    plan = _structured_plan()
    graph = compile_shared_execution_graph(
        plan,
        scope_fingerprint=run_scope_fingerprint(
            run_id=1,
            owner_user_id=1,
            workspace_id=2,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
    )
    active = 0
    peak = 0

    async def execute(node: GraphNode, dependencies, quota):
        nonlocal active, peak
        del dependencies, quota
        if node.parallel_eligible:
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
            result=(
                {"entry_set": {}}
                if node.kind == "structured_entry_set"
                else {"value": 0}
                if node.kind == "aggregate_count"
                else {"group_by": "info_nature", "buckets": []}
                if node.kind == "aggregate_group_count"
                else {"entry_ids": [], "items": [], "has_more": False}
            ),
        )

    await run_graph_scheduler(graph, execute_node=execute)
    assert peak == graph.frozen_budget.max_concurrency == 2


@pytest.mark.asyncio
async def test_upstream_failure_blocks_descendants_without_replaying_tool_calls() -> None:
    """共享根节点失败只执行一次，后继由调度器传播失败且不再触发底层调用。"""
    graph = compile_shared_execution_graph(
        _retrieval_plan(),
        scope_fingerprint=run_scope_fingerprint(
            run_id=1,
            owner_user_id=1,
            workspace_id=2,
            project_id=None,
            scope_type=SCOPE_WORKSPACE,
        ),
    )
    calls: list[str] = []

    async def execute(node: GraphNode, dependencies, quota):
        del dependencies, quota
        calls.append(node.id)
        raise RuntimeError("模拟上游检索失败")

    state = await run_graph_scheduler(graph, execute_node=execute)
    assert calls == [graph.nodes[0].id]
    assert [item.status for item in state.outcomes] == ["failed", "failed", "failed"]
    assert all(item.server_audits for item in state.outcomes)
