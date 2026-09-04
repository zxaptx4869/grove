"""共享执行图的协议、精确去重、调度与恢复单元测试。"""

import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services.knowledge_agent.composite_answer import normalize_composite_answer_plan
from app.services.knowledge_agent.composite_answer_execution import (
    composite_request_fingerprint,
    execute_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_types import CompositeExecutionInputSnapshot
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.shared_execution_graph import (
    GraphNode,
    NodeOutcome,
    SharedExecutionGraph,
    SharedExecutionGraphExecutionStartedError,
    SharedExecutionState,
    allocate_wave_quota,
    compile_shared_execution_graph,
    dump_shared_execution_graph,
    execute_graph_node,
    execute_shared_execution_graph_plan,
    materialize_composite_execution,
    ready_waves,
    restore_shared_execution_graph,
    run_graph_scheduler,
    run_scope_fingerprint,
)
from app.services.knowledge_agent.tools import (
    EvidenceReadItem,
    EvidenceReadOutput,
    RunToolContext,
)


def _plan(*, duplicate: bool = False):
    retrieval = [
        {"id": "q1", "query": "甲醛 来源", "requirement_ids": ["a"]},
    ]
    requirements = [
        {
            "id": "a",
            "order": 0,
            "summary": "说明来源",
            "kind": "retrieve",
            "basis_policy": "grove_required",
        },
    ]
    if duplicate:
        retrieval.append({"id": "q2", "query": "甲醛 来源", "requirement_ids": ["b"]})
        requirements.append(
            {
                "id": "b",
                "order": 1,
                "summary": "再次说明来源",
                "kind": "retrieve",
                "basis_policy": "grove_required",
            }
        )
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": requirements,
            "statement_message_ids": [],
            "retrieval_requests": retrieval,
            "structured_requests": [],
        }
    )


def _scope() -> str:
    return run_scope_fingerprint(
        owner_user_id=1, workspace_id=2, project_id=None, scope_type="workspace"
    )


def _structured_plan():
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计知识数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "groups",
                    "order": 1,
                    "summary": "按信息性质分组",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "s1",
                    "entry_set": {},
                    "outputs": [
                        {"kind": "count"},
                        {"kind": "group_count", "group_by": "info_nature"},
                    ],
                    "requirement_ids": ["count", "groups"],
                }
            ],
        }
    )


def _semantic_structured_plan():
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计相关知识",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "groups",
                    "order": 1,
                    "summary": "分组相关知识",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "s1",
                    "entry_set": {"semantic_query": "甲醛 来源"},
                    "outputs": [
                        {"kind": "count"},
                        {"kind": "group_count", "group_by": "info_nature"},
                    ],
                    "requirement_ids": ["count", "groups"],
                }
            ],
        }
    )


def _duplicate_structured_plan():
    return normalize_composite_answer_plan(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "count",
                    "order": 0,
                    "summary": "统计知识数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
                {
                    "id": "count_again",
                    "order": 1,
                    "summary": "再次统计知识数量",
                    "kind": "aggregate",
                    "basis_policy": "grove_only",
                },
            ],
            "statement_message_ids": [],
            "retrieval_requests": [],
            "structured_requests": [
                {
                    "id": "s1",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["count"],
                },
                {
                    "id": "s2",
                    "entry_set": {},
                    "outputs": [{"kind": "count"}],
                    "requirement_ids": ["count_again"],
                },
            ],
        }
    )


def test_schema_closed_and_bounds() -> None:
    with pytest.raises(ValidationError):
        GraphNode.model_validate(
            {
                "id": "n1",
                "kind": "unknown",
                "fingerprint": "a" * 64,
                "canonical_key": "x",
                "extra": True,
            }
        )
    with pytest.raises(ValidationError):
        NodeOutcome(node_id="n1", fingerprint="a" * 64, status="completed", error="x" * 501)


def test_compile_deduplicates_equivalent_retrieval_and_preserves_consumers() -> None:
    graph = compile_shared_execution_graph(_plan(duplicate=True), scope_fingerprint=_scope())
    assert len(graph.nodes) == 3
    assert graph.nodes[0].consumer_request_ids == ["q1", "q2"]
    assert graph.nodes[0].consumer_requirement_ids == ["r1", "r2"]


def test_restore_rejects_corrupt_and_digest_mismatch() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    with pytest.raises(ValueError, match="非法"):
        restore_shared_execution_graph("{")
    with pytest.raises(ValueError, match="digest"):
        restore_shared_execution_graph(
            dump_shared_execution_graph(graph), expected_plan_digest="b" * 64
        )


def test_ready_waves_and_stable_quota() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    assert [[node.id for node in wave] for wave in ready_waves(graph)] == [["n1"], ["n2"], ["n3"]]
    quota = allocate_wave_quota(graph.nodes[:1], budget=graph.frozen_budget, remaining_entries=1)
    assert quota["n1"]["entries"] == 1


@pytest.mark.asyncio
async def test_scheduler_propagates_upstream_failure() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())

    async def execute(node, _deps, _quota):
        if node.id == "n1":
            raise RuntimeError("fail")
        return {}

    state = await run_graph_scheduler(graph, execute_node=execute)
    assert [item.status for item in state.outcomes] == ["failed", "failed", "failed"]
    assert all(item.server_audits for item in state.outcomes)


@pytest.mark.asyncio
async def test_scheduler_uses_remaining_global_budget_across_waves() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    graph.frozen_budget.max_entries = 1
    graph.frozen_budget.max_tool_calls = 3
    quotas: dict[str, dict[str, int]] = {}

    async def execute(node, _deps, quota):
        quotas[node.id] = quota
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
            entry_count=1 if node.id == "n1" else 0,
            tool_calls=1,
        )

    await run_graph_scheduler(graph, execute_node=execute)
    assert quotas["n1"]["entries"] == 1
    assert quotas["n2"]["entries"] == 0
    assert quotas["n3"]["entries"] == 0


@pytest.mark.asyncio
async def test_scheduler_checkpoints_terminal_nodes_and_reuses_recovery() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    first = graph.nodes[0]
    restored = SharedExecutionState(
        plan_digest=graph.plan_digest,
        outcomes=[
            NodeOutcome(
                node_id=first.id,
                fingerprint=first.fingerprint,
                status="completed",
                completeness="limited",
                result={"entry_ids": [1]},
                tool_calls=1,
            )
        ],
    )
    executed: list[str] = []
    checkpoints: list[list[str]] = []

    async def execute(node, _deps, _quota):
        executed.append(node.id)
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
        )

    async def checkpoint(state):
        checkpoints.append([item.node_id for item in state.outcomes])

    state = await run_graph_scheduler(
        graph,
        state=restored,
        execute_node=execute,
        checkpoint=checkpoint,
    )
    assert executed == ["n2", "n3"]
    assert checkpoints == [["n1", "n2"], ["n1", "n2", "n3"]]
    assert len(state.outcomes) == 3


@pytest.mark.asyncio
async def test_scheduler_cancellation_stops_new_nodes_without_terminal_state() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    calls = 0
    class RunCancelled(Exception):
        pass

    async def cancel_check():
        if calls:
            raise RunCancelled("cancelled")

    async def execute(node, _deps, _quota):
        nonlocal calls
        calls += 1
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
        )

    with pytest.raises(RunCancelled):
        await run_graph_scheduler(
            graph,
            execute_node=execute,
            cancel_check=cancel_check,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_scheduler_enforces_total_duration_budget() -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    graph.frozen_budget.max_duration_ms = 10
    cancelled = False

    async def execute(node, _deps, _quota):
        nonlocal cancelled
        try:
            await asyncio.sleep(0.25)
            return NodeOutcome(
                node_id=node.id,
                fingerprint=node.fingerprint,
                status="completed",
                completeness="complete",
            )
        except asyncio.CancelledError:
            cancelled = True
            raise

    started_at = monotonic()
    state = await run_graph_scheduler(graph, execute_node=execute)
    elapsed = monotonic() - started_at
    assert elapsed < 0.15
    assert cancelled is True
    assert state.outcomes[0].status == "limited"
    assert "耗时" in (state.outcomes[0].error or "")
    assert state.outcomes[0].server_audits[0].status == "limited"


@pytest.mark.asyncio
async def test_semantic_structured_set_is_prepared_once_and_shared_by_outputs(
    monkeypatch,
) -> None:
    graph = compile_shared_execution_graph(
        _semantic_structured_plan(), scope_fingerprint=_scope()
    )
    entry_set_node = next(node for node in graph.nodes if node.kind == "structured_entry_set")
    output_nodes = [node for node in graph.nodes if node.kind.startswith("aggregate_")]
    prepare_calls = 0

    async def prepare(_db, _ctx, _entry_set, *, record_observability, model_audits):
        nonlocal prepare_calls
        prepare_calls += 1
        assert record_observability is False
        model_audits.append(
            StageMeta(
                purpose="embedding",
                provider="test",
                model="embedding-test",
                is_fallback=False,
                error=None,
                duration_ms=1,
            )
        )
        return [SimpleNamespace(id=9), SimpleNamespace(id=10)]

    seen_sets: list[tuple[set[int] | None, list[int] | None]] = []

    async def dispatch(_db, current_ctx, **kwargs):
        seen_sets.append(
            (current_ctx.structured_query_entry_ids, current_ctx.structured_query_entry_order)
        )
        operation = kwargs["params"]["operation"]
        return SimpleNamespace(
            status="completed",
            completeness="limited",
            payload={"value": 2}
            if operation == "count"
            else {"group_by": "info_nature", "buckets": []},
            error=None,
            duration_ms=1,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query_tools.prepare_semantic_entry_set",
        prepare,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.read_tools.dispatch_read_tool",
        dispatch,
    )
    ctx = RunToolContext(1, 2, 1, "workspace", None, None)
    prepared = await execute_graph_node(
        None,
        ctx,
        entry_set_node,
        {},
        quota={
            "tool_calls": 1,
            "entries": 2,
            "evidence": 0,
            "buckets": 0,
            "duration_ms": 1000,
        },
        cancel_check=_not_cancelled,
    )
    for node in output_nodes:
        isolated_ctx = RunToolContext(1, 2, 1, "workspace", None, None)
        await execute_graph_node(
            None,
            isolated_ctx,
            node,
            {entry_set_node.id: prepared},
            quota={
                "tool_calls": 1,
                "entries": 2,
                "evidence": 0,
                "buckets": 2,
                "duration_ms": 1000,
            },
            cancel_check=_not_cancelled,
        )

    assert prepare_calls == 1
    assert prepared.result["entry_ids"] == [9, 10]
    assert len(prepared.model_audits) == 1
    assert seen_sets == [({9, 10}, [9, 10]), ({9, 10}, [9, 10])]


@pytest.mark.asyncio
async def test_entry_evidence_consumes_one_tool_call_per_entry(monkeypatch) -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    content, evidence = graph.nodes[1:]
    ctx = RunToolContext(1, 2, 1, "workspace", None, None, {9, 10})
    calls: list[int] = []

    async def read_evidence(_db, _ctx, entry_id, source_ids):
        calls.append(entry_id)
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_ids[0],
                    evidence_handle=f"ev_{entry_id}",
                    citable=True,
                    status="completed",
                )
            ]
        )

    monkeypatch.setattr("app.services.knowledge_agent.tools.read_source_evidence", read_evidence)
    outcome = await execute_graph_node(
        None,
        ctx,
        evidence,
        {
            content.id: NodeOutcome(
                node_id=content.id,
                fingerprint=content.fingerprint,
                status="completed",
                completeness="complete",
                result={
                    "entry_ids": [9, 10],
                    "entry_sources": {"9": [33], "10": [44]},
                },
            )
        },
        quota={"tool_calls": 1, "entries": 2, "evidence": 2, "buckets": 0, "duration_ms": 1000},
        cancel_check=_not_cancelled,
    )
    assert calls == [9]
    assert outcome.tool_calls == 1
    assert outcome.status == "limited"
    assert outcome.result["evidence_handles"] == ["ev_9"]


@pytest.mark.asyncio
async def test_entry_evidence_reads_verified_source_handles(monkeypatch) -> None:
    graph = compile_shared_execution_graph(_plan(), scope_fingerprint=_scope())
    content, evidence = graph.nodes[1:]
    ctx = RunToolContext(1, 2, 1, "workspace", None, None, {9})

    async def read_evidence(_db, _ctx, entry_id, source_ids):
        assert (entry_id, source_ids) == (9, [33])
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=9,
                    source_id=33,
                    evidence_handle="ev_verified",
                    citable=True,
                    status="completed",
                )
            ]
        )

    monkeypatch.setattr("app.services.knowledge_agent.tools.read_source_evidence", read_evidence)
    outcome = await execute_graph_node(
        None,
        ctx,
        evidence,
        {
            content.id: NodeOutcome(
                node_id=content.id,
                fingerprint=content.fingerprint,
                status="completed",
                completeness="complete",
                result={"entry_ids": [9], "entry_sources": {"9": [33]}},
            )
        },
        quota={"tool_calls": 1, "entries": 1, "evidence": 1, "buckets": 0},
        cancel_check=lambda: _not_cancelled(),
    )
    assert outcome.result == {"entry_ids": [9], "evidence_handles": ["ev_verified"]}
    assert outcome.evidence_count == 1


async def _not_cancelled() -> None:
    return None


def test_compile_aggregate_carries_entry_set_and_materializes_once() -> None:
    plan = _structured_plan()
    graph = compile_shared_execution_graph(plan, scope_fingerprint=_scope())
    count = next(node for node in graph.nodes if node.kind == "aggregate_count")
    grouped = next(node for node in graph.nodes if node.kind == "aggregate_group_count")
    assert count.normalized_params["entry_set"]["schema_version"] == "v1"
    outcomes = [
        NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
            result=(
                {"entry_set": {}}
                if node.kind == "structured_entry_set"
                else {"value": 2}
                if node.kind == "aggregate_count"
                else {"group_by": "info_nature", "buckets": [{"key": "x", "count": 2}]}
            ),
            result_handle=f"res_{node.id}",
        )
        for node in graph.nodes
    ]
    snapshot = materialize_composite_execution(
        plan,
        graph,
        SharedExecutionState(plan_digest=graph.plan_digest, outcomes=outcomes),
    )
    assert {fact.kind for fact in snapshot.tool_facts} == {"count", "group_count"}
    assert next(fact for fact in snapshot.tool_facts if fact.kind == "count").text == "共 2 条"
    assert grouped.id in graph.original_request_map["s1"]


@pytest.mark.asyncio
async def test_enabled_path_executes_graph_nodes_and_persists_checkpoints(monkeypatch) -> None:
    plan = _plan()
    calls: list[str] = []

    class FakeDb:
        async def commit(self):
            return None

    run = SimpleNamespace(
        id=11,
        owner_user_id=1,
        workspace_id=2,
        project_id=None,
        scope_type="workspace",
        shared_execution_graph_json=None,
        shared_execution_state_json=None,
        composite_answer_execution_json=None,
    )
    ctx = RunToolContext(11, 2, 1, "workspace", None, None)

    async def execute(_db, _ctx, node, _deps, *, quota, cancel_check):
        calls.append(node.id)
        payload = {"entry_ids": [9]} if node.kind != "entry_evidence" else {
            "entry_ids": [9],
            "evidence_handles": ["ev_1"],
        }
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="complete",
            result=payload,
            result_handle=f"res_{node.id}",
            tool_calls=1 if node.kind != "entry_content" else 0,
            entry_count=1 if node.kind == "entry_content" else 0,
            evidence_count=1 if node.kind == "entry_evidence" else 0,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.shared_execution_graph.execute_graph_node", execute
    )
    artifacts = await execute_shared_execution_graph_plan(
        FakeDb(), run, ctx, plan, cancel_check=_not_cancelled
    )
    assert calls == ["n1", "n2", "n3"]
    assert artifacts.snapshot.inputs[0].evidence_handles == ["ev_1"]
    assert run.shared_execution_state_json is not None
    assert run.composite_answer_execution_json is not None


@pytest.mark.asyncio
async def test_checkpoint_failure_after_node_start_forbids_serial_fallback(monkeypatch) -> None:
    """真实节点开始后即使首个检查点失败，也必须显式失败而不是整体重放。"""
    plan = _plan()

    class FailingDb:
        def __init__(self):
            self.commits = 0

        async def commit(self):
            self.commits += 1
            if self.commits > 1:
                raise RuntimeError("检查点提交失败")

    run = SimpleNamespace(
        id=21,
        owner_user_id=1,
        workspace_id=2,
        project_id=None,
        scope_type="workspace",
        shared_execution_graph_json=None,
        shared_execution_state_json=None,
        composite_answer_execution_json=None,
    )
    ctx = RunToolContext(21, 2, 1, "workspace", None, None)

    async def execute(_db, _ctx, node, _deps, *, quota, cancel_check):
        del quota, cancel_check
        return NodeOutcome(
            node_id=node.id,
            fingerprint=node.fingerprint,
            status="completed",
            completeness="limited",
            result={"entry_ids": []},
            tool_calls=1,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.shared_execution_graph.execute_graph_node", execute
    )
    with pytest.raises(SharedExecutionGraphExecutionStartedError):
        await execute_shared_execution_graph_plan(
            FailingDb(), run, ctx, plan, cancel_check=_not_cancelled
        )


@pytest.mark.asyncio
async def test_equivalent_retrieval_reuse_persists_each_request_fingerprint(monkeypatch) -> None:
    plan = _plan(duplicate=True)
    run = SimpleNamespace(id=12, composite_answer_execution_json=None)
    ctx = RunToolContext(12, 2, 1, "workspace", None, None)
    calls = 0

    async def execute(_db, current_run, _ctx, current_plan, request, **_kwargs):
        nonlocal calls
        calls += 1
        fingerprint = composite_request_fingerprint(
            current_run.id,
            current_plan,
            request_id=request.id,
            kind="retrieval",
            params={
                "query": request.query,
                "requirement_ids": request.requirement_ids,
                "max_entries": 30,
                "max_evidence": 30,
            },
        )
        return CompositeExecutionInputSnapshot(
            request_id=request.id,
            kind="retrieval",
            requirement_ids=request.requirement_ids,
            fingerprint=fingerprint,
            status="completed",
            completeness="complete",
        )

    async def persist(_db, _run, snapshot, *, settings):
        return snapshot

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution._execute_retrieval", execute
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution._persist_checkpoint", persist
    )
    artifacts = await execute_composite_answer_plan(
        None,
        run,
        ctx,
        plan,
        cancel_check=_not_cancelled,
        deduplicate_equivalent_requests=True,
    )
    assert calls == 1
    assert {item.request_id for item in artifacts.snapshot.inputs} == {"q1", "q2"}
    assert len({item.fingerprint for item in artifacts.snapshot.inputs}) == 2


@pytest.mark.asyncio
async def test_equivalent_structured_reuse_persists_each_request_fingerprint(monkeypatch) -> None:
    plan = _duplicate_structured_plan()
    run = SimpleNamespace(id=13, composite_answer_execution_json=None)
    ctx = RunToolContext(13, 2, 1, "workspace", None, None)
    calls = 0

    async def execute(_db, current_run, _ctx, current_plan, request, **_kwargs):
        nonlocal calls
        calls += 1
        params = request.query_plan.model_dump(mode="json", by_alias=True)
        fingerprint = composite_request_fingerprint(
            current_run.id,
            current_plan,
            request_id=request.id,
            kind="structured",
            params=params,
        )
        item = CompositeExecutionInputSnapshot(
            request_id=request.id,
            kind="structured",
            requirement_ids=request.requirement_ids,
            fingerprint=fingerprint,
            status="completed",
            completeness="complete",
        )
        return item, []

    async def persist(_db, _run, snapshot, *, settings):
        return snapshot

    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution._execute_structured", execute
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.composite_answer_execution._persist_checkpoint", persist
    )
    artifacts = await execute_composite_answer_plan(
        None,
        run,
        ctx,
        plan,
        cancel_check=_not_cancelled,
        deduplicate_equivalent_requests=True,
    )
    assert calls == 1
    assert {item.request_id for item in artifacts.snapshot.inputs} == {"s1", "s2"}
    assert len({item.fingerprint for item in artifacts.snapshot.inputs}) == 2


def test_materialize_rejects_mismatched_state() -> None:
    plan = _plan()
    graph = compile_shared_execution_graph(plan, scope_fingerprint=_scope())
    state = SharedExecutionState(plan_digest=graph.plan_digest, outcomes=[])
    assert materialize_composite_execution(plan, graph, state).inputs == []
    broken = SharedExecutionGraph.model_validate({**graph.model_dump(), "plan_digest": "b" * 64})
    with pytest.raises(ValueError, match="摘要"):
        materialize_composite_execution(plan, broken, state)
