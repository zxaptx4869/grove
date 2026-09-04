"""一次有界覆盖补查的等价性、复用、隔离与无写入评估。"""

import json
from collections import Counter

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models import (
    Candidate,
    Entry,
    Extraction,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeCandidateDraft,
    KnowledgeConversation,
    KnowledgeWorkingSetItem,
    Source,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    RUN_PROCESSING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeAnswerPointOut,
    KnowledgeRunCitationOut,
)
from app.services.knowledge_agent.basis import build_answer_basis
from app.services.knowledge_agent.composite_answer import normalize_composite_answer_plan
from app.services.knowledge_agent.composite_answer_execution import (
    execute_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_response import (
    CompositeAnswerResult,
    _derive_coverage,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)
from app.services.knowledge_agent.coverage_repair import (
    CoverageRepairBudget,
    CoverageRepairSnapshot,
    coverage_repair_material_from_result,
    execute_coverage_repair,
    merge_composite_execution,
    normalize_coverage_repair_plan,
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
        title="覆盖补查评估",
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


def _plans():
    original = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "source",
                    "order": 0,
                    "summary": "说明材料来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                }
            ],
            "retrieval_requests": [
                {
                    "id": "initial",
                    "query": "甲醛 来源",
                    "requirement_ids": ["source"],
                }
            ],
        }
    )
    repair = normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r1"],
            "retrieval_requests": [
                {
                    "id": "repair",
                    "query": "装修材料 释放源",
                    "requirement_ids": ["r1"],
                }
            ],
        },
        original_plan=original,
        eligible_requirement_ids={"r1"},
        scope_fingerprint="eval-scope",
        budget=CoverageRepairBudget(),
    )
    return original, repair


def _snapshot(mode: str) -> CoverageRepairSnapshot:
    answer = KnowledgeAnswerOut(answer="首次仍缺来源", status="partial")
    result = CompositeAnswerResult(
        answer=answer,
        coverage=CompositeAnswerCoverageSnapshot(
            requirements=[{"requirement_id": "r1", "status": "partial"}]
        ),
        answer_basis=build_answer_basis(
            answer=answer,
            user_statement_ids=[],
            model_knowledge_used=False,
            external_material_required=False,
        ),
        run_status="partial",
        answer_fallback=False,
    )
    return CoverageRepairSnapshot(
        stage="plan_ready",
        execution_mode=mode,
        frozen_budget=CoverageRepairBudget(),
        eligible_requirement_ids=["r1"],
        baseline=coverage_repair_material_from_result(result),
        planner_attempted=True,
    )


def _semantics(execution) -> list[dict]:
    return [
        {
            "request_id": item.request_id,
            "status": item.status,
            "completeness": item.completeness,
            "entry_ids": item.entry_ids,
            "evidence_count": len(item.evidence_handles),
        }
        for item in execution.inputs
    ]


def test_repair_coverage_improves_only_real_gap_in_representative_composite() -> None:
    """解释、Grove 来源、结构化统计并存时，补查只改善目标义务。"""
    original = normalize_composite_answer_plan(
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
                    "id": "source",
                    "order": 1,
                    "summary": "说明材料来源",
                    "kind": "retrieve",
                    "basis_policy": "grove_required",
                },
                {
                    "id": "count",
                    "order": 2,
                    "summary": "统计知识数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "retrieval_requests": [
                {
                    "id": "source",
                    "query": "甲醛 来源",
                    "requirement_ids": ["source"],
                }
            ],
            "structured_requests": [
                {
                    "id": "count",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["count"],
                }
            ],
        }
    )
    initial = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q1",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="a" * 64,
                status="empty",
                completeness="limited",
            ),
            CompositeExecutionInputSnapshot(
                request_id="s1",
                kind="structured",
                requirement_ids=["r3"],
                fingerprint="b" * 64,
                status="completed",
                completeness="complete",
                result_handles=["res_initial_count"],
            ),
        ],
        tool_facts=[
            CompositeToolFact(
                handle="res_initial_count",
                request_id="s1",
                requirement_ids=["r3"],
                kind="count",
                text="符合条件的知识条目共 2 条。",
                completeness="complete",
            )
        ],
    )
    initial_answer = KnowledgeAnswerOut(
        answer="解释并给出统计，来源暂缺。",
        status="partial",
        points=[
            KnowledgeAnswerPointOut(text="这是概念解释。", requirement_ids=["r1"]),
            KnowledgeAnswerPointOut(text="来源仍待补充。", requirement_ids=["r2"]),
        ],
    )
    initial_coverage = _derive_coverage(
        original, initial, initial_answer, answer_fallback=False
    )
    repair_plan = normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r2"],
            "retrieval_requests": [
                {
                    "id": "repair",
                    "query": "装修材料 释放源",
                    "requirement_ids": ["r2"],
                }
            ],
        },
        original_plan=original,
        eligible_requirement_ids={"r2"},
        scope_fingerprint="representative",
        budget=CoverageRepairBudget(),
    )
    evidence_handle = "ev_" + "1" * 32
    repair = CompositeAnswerExecutionSnapshot(
        inputs=[
            CompositeExecutionInputSnapshot(
                request_id="q2",
                kind="retrieval",
                requirement_ids=["r2"],
                fingerprint="c" * 64,
                status="completed",
                completeness="limited",
                evidence_handles=[evidence_handle],
            )
        ]
    )
    merged = merge_composite_execution(original, initial, repair_plan, repair)
    citation = KnowledgeRunCitationOut(
        evidence_id=1,
        evidence_handle=evidence_handle,
        entry_id=1,
        entry_title="甲醛来源",
        source_id=1,
        source_title="材料手册",
        quote="板材可能释放甲醛",
    )
    repaired_answer = KnowledgeAnswerOut(
        answer="解释、来源与统计均已覆盖。",
        status="completed",
        points=[
            KnowledgeAnswerPointOut(text="这是概念解释。", requirement_ids=["r1"]),
            KnowledgeAnswerPointOut(
                text="板材可能释放甲醛。",
                requirement_ids=["r2"],
                citations=[citation],
            ),
        ],
    )
    repaired_coverage = _derive_coverage(
        original, merged, repaired_answer, answer_fallback=False
    )

    assert [item.status for item in initial_coverage.requirements] == [
        "answered",
        "partial",
        "answered",
    ]
    assert [item.status for item in repaired_coverage.requirements] == [
        "answered",
        "answered",
        "answered",
    ]


@pytest.mark.asyncio
async def test_repair_serial_graph_equivalence_and_scope_isolation(monkeypatch) -> None:
    """串行/共享图补查语义等价，且上下文始终绑定各自 Run 范围。"""
    original, repair = _plans()
    calls: Counter[tuple[int, str]] = Counter()

    async def search(db, ctx, query, **kwargs):
        calls[(ctx.run_id, "search")] += 1
        ctx.discovered_entry_ids.add(9)
        return SearchToolOutput(
            items=[
                SearchResultItem(
                    entry_id=9,
                    title="甲醛来源",
                    project_name="装修",
                    node_path="材料",
                    summary="板材可能释放甲醛。",
                    source_count=1,
                )
            ]
        )

    async def read(db, ctx, entry_ids):
        assert entry_ids == [9]
        calls[(ctx.run_id, "read")] += 1
        return ReadEntriesOutput(
            items=[
                ReadEntryItem(
                    entry_id=9,
                    title="甲醛来源",
                    content="板材可能释放甲醛。",
                    project_name="装修",
                    node_path="材料",
                    sources=[{"source_id": 33}],
                )
            ]
        )

    async def evidence(db, ctx, entry_id, source_ids):
        assert entry_id == 9 and source_ids == [33]
        calls[(ctx.run_id, "evidence")] += 1
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=9,
                    source_id=33,
                    evidence_handle=f"ev_{ctx.run_id}",
                    quote="板材可能释放甲醛",
                    citable=True,
                    status="completed",
                )
            ]
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "search_confirmed_knowledge",
        search,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_entries", read
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution.read_source_evidence",
        evidence,
    )
    monkeypatch.setattr("app.services.knowledge_agent.tools.search_confirmed_knowledge", search)
    monkeypatch.setattr("app.services.knowledge_agent.tools.read_entries", read)
    monkeypatch.setattr("app.services.knowledge_agent.tools.read_source_evidence", evidence)

    async with async_session_factory() as db:
        user = await create_user(db, "补查图等价")
        workspace = await create_workspace(db, user)
        serial_run = await _create_run(db, user, workspace)
        graph_run = await _create_run(db, user, workspace)
        await db.commit()

        serial, _ = await execute_coverage_repair(
            db,
            serial_run,
            _context(serial_run),
            original,
            repair,
            _snapshot("serial"),
            cancel_check=_never_cancel,
        )
        graph, _ = await execute_coverage_repair(
            db,
            graph_run,
            _context(graph_run),
            original,
            repair,
            _snapshot("shared_graph"),
            cancel_check=_never_cancel,
        )
        graph_payload = graph_run.coverage_repair_graph_json

    assert _semantics(serial) == _semantics(graph)
    assert calls[(serial_run.id, "search")] == 1
    assert calls[(graph_run.id, "search")] == 1
    assert all(run_id in {serial_run.id, graph_run.id} for run_id, _ in calls)
    assert graph_payload is not None
    assert len(json.loads(graph_payload)["nodes"]) <= 8


@pytest.mark.asyncio
async def test_repair_reuses_evidence_and_never_replays_completed_inputs(
    monkeypatch,
) -> None:
    """新查询命中同来源时复用 Evidence 行；恢复不重放首次或补查终态。"""
    original, repair = _plans()
    calls: Counter[str] = Counter()

    async def search(db, ctx, query, **kwargs):
        calls[f"search:{query}"] += 1
        ctx.discovered_entry_ids.add(entry.id)
        return SearchToolOutput(
            items=[
                SearchResultItem(
                    entry_id=entry.id,
                    title=entry.title,
                    project_name=project.name,
                    node_path="材料",
                    summary=entry.content,
                    source_count=1,
                )
            ]
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "search_confirmed_knowledge",
        search,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "Evidence 复用")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "装修")
        node = await create_child_node(db, project, "材料")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="材料手册",
            text_content="板材可能释放甲醛。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="甲醛来源",
            content="板材可能释放甲醛。",
            quote="板材可能释放甲醛",
        )
        run = await _create_run(db, user, workspace)
        await db.commit()
        ctx = _context(run)

        initial = await execute_composite_answer_plan(
            db, run, ctx, original, cancel_check=_never_cancel
        )
        repair_execution, ready = await execute_coverage_repair(
            db,
            run,
            ctx,
            original,
            repair,
            _snapshot("serial"),
            cancel_check=_never_cancel,
        )
        calls_before_recovery = calls.copy()
        recovered, _ = await execute_coverage_repair(
            db,
            run,
            ctx,
            original,
            repair,
            ready,
            cancel_check=_never_cancel,
        )
        evidence_count = (
            await db.execute(
                select(func.count(KnowledgeAgentEvidence.id)).where(
                    KnowledgeAgentEvidence.run_id == run.id
                )
            )
        ).scalar_one()

    assert initial.snapshot.inputs[0].evidence_handles
    assert (
        repair_execution.inputs[0].evidence_handles
        == initial.snapshot.inputs[0].evidence_handles
    )
    assert recovered == repair_execution
    assert calls == calls_before_recovery
    assert calls["search:甲醛 来源"] == 1
    assert calls["search:装修材料 释放源"] == 1
    assert evidence_count == 1


@pytest.mark.asyncio
async def test_repair_guardrail_has_no_knowledge_write_side_effect(monkeypatch) -> None:
    """补查只允许 Evidence/审计检查点写入，不创建任何知识或候选工作集。"""
    original, repair = _plans()

    async def empty_search(db, ctx, query, **kwargs):
        return SearchToolOutput(items=[])

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution."
        "search_confirmed_knowledge",
        empty_search,
    )
    guarded_models = [
        Entry,
        Source,
        Candidate,
        Extraction,
        KnowledgeCandidateDraft,
        KnowledgeWorkingSetItem,
    ]
    async with async_session_factory() as db:
        user = await create_user(db, "补查无写入")
        workspace = await create_workspace(db, user)
        run = await _create_run(db, user, workspace)
        await db.commit()
        before = {
            model.__name__: (await db.execute(select(func.count()).select_from(model))).scalar_one()
            for model in guarded_models
        }
        result, _ = await execute_coverage_repair(
            db,
            run,
            _context(run),
            original,
            repair,
            _snapshot("serial"),
            cancel_check=_never_cancel,
        )
        after = {
            model.__name__: (await db.execute(select(func.count()).select_from(model))).scalar_one()
            for model in guarded_models
        }

    assert result.inputs[0].status == "empty"
    assert before == after


@pytest.mark.asyncio
async def test_repair_structured_query_respects_workspace_and_project_guardrail() -> None:
    """结构化补查只统计 Run 注入的 Workspace/项目，不能跨范围读取。"""
    original = normalize_composite_answer_plan(
        {
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计当前项目知识",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                }
            ],
            "retrieval_requests": [
                {
                    "id": "initial",
                    "query": "当前项目知识",
                    "requirement_ids": ["count"],
                }
            ],
        }
    )
    repair = normalize_coverage_repair_plan(
        {
            "target_requirement_ids": ["r1"],
            "structured_requests": [
                {
                    "id": "count",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["r1"],
                }
            ],
        },
        original_plan=original,
        eligible_requirement_ids={"r1"},
        scope_fingerprint="guardrail-scope",
        budget=CoverageRepairBudget(),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "补查范围")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "范围内项目")
        other_project = await create_project(db, workspace, "同空间其他项目")
        other_user = await create_user(db, "补查范围外用户")
        other_workspace = await create_workspace(db, other_user)
        foreign_project = await create_project(db, other_workspace, "其他空间项目")
        for current_project, current_workspace, title in [
            (project, workspace, "范围内知识"),
            (other_project, workspace, "同空间范围外知识"),
            (foreign_project, other_workspace, "跨空间知识"),
        ]:
            node = await create_child_node(db, current_project, "材料")
            source, attachment = await create_source_attachment(
                db,
                current_workspace,
                current_project,
                title=title,
                text_content=title,
            )
            await create_entry_with_evidence(
                db,
                current_project,
                node,
                source,
                attachment,
                title=title,
                content=title,
                quote=title,
            )
        run = await _create_run(db, user, workspace, project=project)
        await db.commit()

        execution, _ = await execute_coverage_repair(
            db,
            run,
            _context(run),
            original,
            repair,
            _snapshot("serial"),
            cancel_check=_never_cancel,
        )

    assert execution.tool_facts[0].summary["value"] == 1
    assert execution.tool_facts[0].completeness == "complete"
