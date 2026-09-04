"""共享执行图的协议、精确去重、调度与恢复单元测试。"""

import pytest
from pydantic import ValidationError

from app.services.knowledge_agent.composite_answer import normalize_composite_answer_plan
from app.services.knowledge_agent.shared_execution_graph import (
    GraphNode,
    NodeOutcome,
    SharedExecutionGraph,
    SharedExecutionState,
    allocate_wave_quota,
    compile_shared_execution_graph,
    dump_shared_execution_graph,
    materialize_composite_execution,
    ready_waves,
    restore_shared_execution_graph,
    run_graph_scheduler,
    run_scope_fingerprint,
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


def test_materialize_rejects_mismatched_state() -> None:
    plan = _plan()
    graph = compile_shared_execution_graph(plan, scope_fingerprint=_scope())
    state = SharedExecutionState(plan_digest=graph.plan_digest, outcomes=[])
    assert materialize_composite_execution(plan, graph, state).inputs == []
    broken = SharedExecutionGraph.model_validate({**graph.model_dump(), "plan_digest": "b" * 64})
    with pytest.raises(ValueError, match="摘要"):
        materialize_composite_execution(plan, broken, state)
