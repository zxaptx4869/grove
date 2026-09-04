"""Knowledge Agent quick 复合回答共享执行图领域模型。

图是服务端从已规范化计划编译出的内部快照。模型与客户端不能提交图控制
字段；所有模型使用 ``extra=forbid``，恢复时也不会扩大历史 JSON 的语义。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings, get_settings
from app.services.knowledge_agent.composite_answer import NormalizedCompositeAnswerPlan
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerExecutionSnapshot,
    CompositeExecutionInputSnapshot,
    CompositeToolFact,
)

SHARED_EXECUTION_GRAPH_VERSION = "v1"
NODE_KINDS = (
    "semantic_entry_set",
    "structured_entry_set",
    "entry_list",
    "entry_content",
    "entry_evidence",
    "aggregate_count",
    "aggregate_group_count",
)
NODE_TERMINAL_STATUSES = ("completed", "empty", "limited", "partial", "failed", "cancelled")


class GraphModel(BaseModel):
    """共享图快照的闭合基础模型。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class SharedExecutionBudget(GraphModel):
    """Run 固化的共享图总预算。"""

    max_nodes: int = Field(default=24, ge=1, le=100)
    max_depth: int = Field(default=4, ge=1, le=20)
    max_dependencies_per_node: int = Field(default=4, ge=0, le=20)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_tool_calls: int = Field(default=12, ge=0, le=100)
    max_entries: int = Field(default=30, ge=0, le=500)
    max_evidence: int = Field(default=30, ge=0, le=500)
    max_buckets: int = Field(default=24, ge=0, le=500)
    max_graph_bytes: int = Field(default=24000, ge=1000, le=60000)
    max_state_bytes: int = Field(default=60000, ge=1000, le=64000)
    max_duration_ms: int = Field(default=30000, ge=1, le=180000)


# 兼容测试和调用方可能使用的更明确名称。
SharedExecutionGraphBudget = SharedExecutionBudget
FrozenBudget = SharedExecutionBudget


class GraphNode(GraphModel):
    """闭合领域节点；参数只能来自服务端规范化计划。"""

    id: str = Field(pattern=r"^n[1-9][0-9]*$", max_length=8)
    kind: Literal[
        "semantic_entry_set",
        "structured_entry_set",
        "entry_list",
        "entry_content",
        "entry_evidence",
        "aggregate_count",
        "aggregate_group_count",
    ]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    canonical_key: str = Field(min_length=1, max_length=2000)
    dependencies: list[str] = Field(default_factory=list, max_length=4)
    consumer_request_ids: list[str] = Field(default_factory=list, max_length=20)
    consumer_requirement_ids: list[str] = Field(default_factory=list, max_length=20)
    normalized_params: dict[str, Any] = Field(default_factory=dict)
    parallel_eligible: bool = False

    @field_validator("normalized_params")
    @classmethod
    def _bounded_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(raw.encode("utf-8")) > 12000:
            raise ValueError("图节点参数超过长度上限")
        return value

    @field_validator("dependencies", "consumer_request_ids", "consumer_requirement_ids")
    @classmethod
    def _bounded_items(cls, values: list[str]) -> list[str]:
        if any(len(value) > 100 for value in values):
            raise ValueError("图引用字段过长")
        return list(dict.fromkeys(values))


class NodeOutcome(GraphModel):
    """一次已提交节点终态及有界结果句柄。"""

    node_id: str = Field(pattern=r"^n[1-9][0-9]*$", max_length=8)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    status: Literal["completed", "empty", "limited", "partial", "failed", "cancelled"]
    completeness: Literal["complete", "limited", "unknown"] = "unknown"
    result_handle: str | None = Field(default=None, max_length=128)
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=500)
    duration_ms: int = Field(default=0, ge=0, le=180000)
    tool_calls: int = Field(default=0, ge=0, le=100)
    entry_count: int = Field(default=0, ge=0, le=500)
    evidence_count: int = Field(default=0, ge=0, le=500)
    bucket_count: int = Field(default=0, ge=0, le=500)
    upstream_fingerprints: list[str] = Field(default_factory=list, max_length=4)
    reused: bool = False

    @field_validator("result")
    @classmethod
    def _bounded_result(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(raw.encode("utf-8")) > 16000:
            raise ValueError("节点结果超过长度上限")
        return value


class SharedExecutionGraph(GraphModel):
    """服务端固化的 SharedExecutionGraph v1。"""

    schema_version: Literal["v1"] = "v1"
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    run_scope_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    frozen_budget: SharedExecutionBudget
    nodes: list[GraphNode] = Field(min_length=1, max_length=100)
    original_request_map: dict[str, list[str]] = Field(default_factory=dict)


class SharedExecutionState(GraphModel):
    """按稳定 node id 排序的图检查点。"""

    schema_version: Literal["v1"] = "v1"
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    graph_version: Literal["v1"] = "v1"
    outcomes: list[NodeOutcome] = Field(default_factory=list, max_length=100)

    @field_validator("outcomes")
    @classmethod
    def _sort_outcomes(cls, values: list[NodeOutcome]) -> list[NodeOutcome]:
        return sorted(values, key=lambda item: int(item.node_id[1:]))


def _json_bytes(value: BaseModel) -> int:
    return len(value.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))


def dump_shared_execution_graph(
    graph: SharedExecutionGraph, *, settings: Settings | None = None
) -> str:
    """严格序列化图并校验独立图字节预算。"""
    active = settings or get_settings()
    raw = graph.model_dump_json(by_alias=True, exclude_none=True)
    limit = min(
        active.knowledge_agent_shared_execution_graph_bytes_limit,
        graph.frozen_budget.max_graph_bytes,
    )
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("共享执行图超过 JSON 字节预算")
    return raw


def dump_shared_execution_state(
    state: SharedExecutionState,
    *,
    settings: Settings | None = None,
    budget: SharedExecutionBudget | None = None,
) -> str:
    """严格序列化检查点并校验 state 字节预算。"""
    active = settings or get_settings()
    raw = state.model_dump_json(by_alias=True, exclude_none=True)
    limit = min(
        active.knowledge_agent_shared_execution_state_bytes_limit,
        (budget or SharedExecutionBudget()).max_state_bytes,
    )
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("共享执行状态超过 JSON 字节预算")
    return raw


def restore_shared_execution_graph(
    raw: str | None,
    *,
    settings: Settings | None = None,
    expected_plan_digest: str | None = None,
) -> SharedExecutionGraph | None:
    """恢复图；旧 Run 的空字段返回 None，损坏快照直接失败。"""
    if raw is None:
        return None
    active = settings or get_settings()
    if len(raw.encode("utf-8")) > active.knowledge_agent_shared_execution_graph_bytes_limit:
        raise ValueError("共享执行图超过 JSON 字节预算")
    try:
        graph = SharedExecutionGraph.model_validate_json(raw)
        if expected_plan_digest is not None and graph.plan_digest != expected_plan_digest:
            raise ValueError("共享执行图 plan digest 不匹配")
        return graph
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"共享执行图快照非法：{exc}") from exc


def restore_shared_execution_state(
    raw: str | None,
    *,
    settings: Settings | None = None,
    budget: SharedExecutionBudget | None = None,
    expected_plan_digest: str | None = None,
) -> SharedExecutionState | None:
    """恢复检查点；未知字段、重复节点和损坏 JSON 均拒绝。"""
    if raw is None:
        return None
    active = settings or get_settings()
    if len(raw.encode("utf-8")) > active.knowledge_agent_shared_execution_state_bytes_limit:
        raise ValueError("共享执行状态超过 JSON 字节预算")
    try:
        state = SharedExecutionState.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"共享执行状态快照非法：{exc}") from exc
    if expected_plan_digest is not None and state.plan_digest != expected_plan_digest:
        raise ValueError("共享执行状态 plan digest 不匹配")
    if budget is not None and _json_bytes(state) > budget.max_state_bytes:
        raise ValueError("共享执行状态超过冻结预算")
    return state


def plan_digest(plan: NormalizedCompositeAnswerPlan) -> str:
    """计算规范化计划摘要；不包含运行时图控制字段。"""
    raw = plan.model_dump_json(by_alias=True, exclude_none=True, exclude_defaults=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_scope_fingerprint(
    *, owner_user_id: int, workspace_id: int, project_id: int | None, scope_type: str
) -> str:
    raw = json.dumps(
        {
            "owner_user_id": owner_user_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "scope_type": scope_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _fingerprint(
    kind: str,
    params: dict[str, Any],
    dependencies: list[str],
    scope: str,
    budget: SharedExecutionBudget,
) -> tuple[str, str]:
    key = json.dumps(
        {
            "kind": kind,
            "params": params,
            "dependencies": dependencies,
            "scope": scope,
            "budget": budget.model_dump(mode="json"),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return key, hashlib.sha256(key.encode("utf-8")).hexdigest()


def canonical_node_key(
    *,
    kind: str,
    normalized_params: dict[str, Any],
    dependencies: list[str] | None = None,
    scope_fingerprint: str,
    budget: SharedExecutionBudget,
) -> str:
    """公开 canonical key 计算入口；不包含 request/requirement 身份。"""
    key, _ = _fingerprint(
        kind,
        normalized_params,
        dependencies or [],
        scope_fingerprint,
        budget,
    )
    return key


def node_fingerprint(
    *,
    kind: str,
    normalized_params: dict[str, Any],
    dependencies: list[str] | None = None,
    scope_fingerprint: str,
    budget: SharedExecutionBudget,
) -> str:
    """公开稳定 fingerprint 计算入口。"""
    _, fingerprint = _fingerprint(
        kind,
        normalized_params,
        dependencies or [],
        scope_fingerprint,
        budget,
    )
    return fingerprint


def _append_or_merge(
    nodes: list[GraphNode],
    index: dict[str, GraphNode],
    *,
    kind: str,
    params: dict[str, Any],
    dependencies: list[str],
    request_ids: list[str],
    requirement_ids: list[str],
    scope: str,
    budget: SharedExecutionBudget,
) -> GraphNode:
    canonical_key, fingerprint = _fingerprint(kind, params, dependencies, scope, budget)
    existing = index.get(canonical_key)
    if existing is not None:
        existing.consumer_request_ids = sorted(set(existing.consumer_request_ids + request_ids))
        existing.consumer_requirement_ids = sorted(
            set(existing.consumer_requirement_ids + requirement_ids),
            key=lambda item: int(item[1:]) if item[1:].isdigit() else item,
        )
        return existing
    node = GraphNode(
        id=f"n{len(nodes) + 1}",
        kind=kind,
        fingerprint=fingerprint,
        canonical_key=canonical_key,
        dependencies=list(dependencies),
        consumer_request_ids=list(request_ids),
        consumer_requirement_ids=list(requirement_ids),
        normalized_params=params,
        parallel_eligible=kind in {"entry_list", "aggregate_count", "aggregate_group_count"},
    )
    nodes.append(node)
    index[canonical_key] = node
    return node


def compile_shared_execution_graph(
    plan: NormalizedCompositeAnswerPlan,
    *,
    scope_fingerprint: str,
    budget: SharedExecutionBudget | None = None,
    settings: Settings | None = None,
) -> SharedExecutionGraph:
    """从规范化 CompositeAnswerPlan v1 纯函数编译闭合图。"""
    active = settings or get_settings()
    frozen = budget or SharedExecutionBudget(
        max_nodes=active.knowledge_agent_shared_execution_graph_max_nodes,
        max_depth=active.knowledge_agent_shared_execution_graph_max_depth,
        max_dependencies_per_node=active.knowledge_agent_shared_execution_graph_max_dependencies,
        max_concurrency=active.knowledge_agent_shared_execution_graph_max_concurrency,
        max_tool_calls=active.knowledge_agent_shared_execution_graph_max_tool_calls,
        max_entries=active.knowledge_agent_shared_execution_graph_max_entries,
        max_evidence=active.knowledge_agent_shared_execution_graph_max_evidence,
        max_buckets=active.knowledge_agent_shared_execution_graph_max_buckets,
        max_graph_bytes=active.knowledge_agent_shared_execution_graph_bytes_limit,
        max_state_bytes=active.knowledge_agent_shared_execution_graph_state_bytes_limit,
        max_duration_ms=int(active.knowledge_agent_shared_execution_graph_timeout_seconds * 1000),
    )
    nodes: list[GraphNode] = []
    index: dict[str, GraphNode] = {}
    request_map: dict[str, list[str]] = {}
    for request in plan.retrieval_requests:
        params = {
            "query": request.query,
            "max_entries": frozen.max_entries,
            "max_evidence": frozen.max_evidence,
            "completeness": "limited_or_unknown",
        }
        semantic = _append_or_merge(
            nodes,
            index,
            kind="semantic_entry_set",
            params=params,
            dependencies=[],
            request_ids=[request.id],
            requirement_ids=request.requirement_ids,
            scope=scope_fingerprint,
            budget=frozen,
        )
        content = _append_or_merge(
            nodes,
            index,
            kind="entry_content",
            params={"source": semantic.id, "max_entries": frozen.max_entries},
            dependencies=[semantic.id],
            request_ids=[request.id],
            requirement_ids=request.requirement_ids,
            scope=scope_fingerprint,
            budget=frozen,
        )
        evidence = _append_or_merge(
            nodes,
            index,
            kind="entry_evidence",
            params={"source": content.id, "max_evidence": frozen.max_evidence},
            dependencies=[content.id],
            request_ids=[request.id],
            requirement_ids=request.requirement_ids,
            scope=scope_fingerprint,
            budget=frozen,
        )
        request_map[request.id] = [semantic.id, content.id, evidence.id]
    for request in plan.structured_requests:
        entry_set = request.query_plan.entry_set.model_dump(mode="json", by_alias=True)
        base = _append_or_merge(
            nodes,
            index,
            kind="structured_entry_set",
            params={"entry_set": entry_set},
            dependencies=[],
            request_ids=[request.id],
            requirement_ids=request.requirement_ids,
            scope=scope_fingerprint,
            budget=frozen,
        )
        outputs: list[str] = [base.id]
        for output in request.query_plan.outputs:
            if output.kind == "entries":
                params = {
                    "source": base.id,
                    "limit": output.limit,
                    "sort": output.sort.model_dump(mode="json"),
                }
                kind = "entry_list"
            elif output.kind == "count":
                params = {"source": base.id, "operation": "count"}
                kind = "aggregate_count"
            else:
                params = {
                    "source": base.id,
                    "operation": "group_count",
                    "group_by": output.group_by,
                }
                kind = "aggregate_group_count"
            output_node = _append_or_merge(
                nodes,
                index,
                kind=kind,
                params=params,
                dependencies=[base.id],
                request_ids=[request.id],
                requirement_ids=request.requirement_ids,
                scope=scope_fingerprint,
                budget=frozen,
            )
            outputs.append(output_node.id)
        request_map[request.id] = outputs
    graph = SharedExecutionGraph(
        plan_digest=plan_digest(plan),
        run_scope_fingerprint=scope_fingerprint,
        frozen_budget=frozen,
        nodes=nodes,
        original_request_map=request_map,
    )
    validate_shared_execution_graph(graph, plan=plan, settings=active)
    dump_shared_execution_graph(graph, settings=active)
    return graph


def validate_shared_execution_graph(
    graph: SharedExecutionGraph,
    *,
    plan: NormalizedCompositeAnswerPlan | None = None,
    settings: Settings | None = None,
) -> None:
    """校验图闭合性、依赖方向、消费者和所有冻结预算。"""
    active = settings or get_settings()
    budget = graph.frozen_budget
    if len(graph.nodes) > min(
        budget.max_nodes, active.knowledge_agent_shared_execution_graph_max_nodes
    ):
        raise ValueError("共享执行图节点数超过预算")
    ids = [node.id for node in graph.nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("共享执行图节点 id 不唯一")
    by_id = {node.id: node for node in graph.nodes}
    valid_requests = (
        {item.id for item in plan.retrieval_requests + plan.structured_requests}
        if plan
        else set(graph.original_request_map)
    )
    valid_requirements = (
        {item.id for item in plan.requirements}
        if plan
        else {rid for node in graph.nodes for rid in node.consumer_requirement_ids}
    )
    for node in graph.nodes:
        if len(node.dependencies) > budget.max_dependencies_per_node:
            raise ValueError("共享执行图单节点依赖超过预算")
        if node.id in node.dependencies or any(dep not in by_id for dep in node.dependencies):
            raise ValueError("共享执行图依赖非法")
        if not node.consumer_request_ids and not node.consumer_requirement_ids:
            raise ValueError("共享执行图节点缺少消费者")
        if not set(node.consumer_request_ids).issubset(valid_requests) or not set(
            node.consumer_requirement_ids
        ).issubset(valid_requirements):
            raise ValueError("共享执行图消费者引用未知对象")
    indegree = {node.id: 0 for node in graph.nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        for dep in node.dependencies:
            indegree[node.id] += 1
            children[dep].append(node.id)
    queue = deque(
        sorted(
            (node_id for node_id, degree in indegree.items() if degree == 0),
            key=lambda item: int(item[1:]),
        )
    )
    seen: list[str] = []
    while queue:
        current = queue.popleft()
        seen.append(current)
        for child in sorted(children[current], key=lambda item: int(item[1:])):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if len(seen) != len(graph.nodes):
        raise ValueError("共享执行图存在循环依赖")
    depth = {node_id: 1 for node_id in seen}
    for node_id in seen:
        node = by_id[node_id]
        if node.dependencies:
            depth[node_id] = max(depth[dep] for dep in node.dependencies) + 1
    if max(depth.values(), default=0) > budget.max_depth:
        raise ValueError("共享执行图深度超过预算")
    if sum(1 for node in graph.nodes if node.kind != "entry_content") > budget.max_tool_calls:
        raise ValueError("共享执行图工具调用预算不足")
    for request_id, node_ids in graph.original_request_map.items():
        if (
            request_id not in valid_requests
            or not node_ids
            or any(node_id not in by_id for node_id in node_ids)
        ):
            raise ValueError("共享执行图原始请求映射非法")


def persist_shared_execution_graph(
    run: Any, graph: SharedExecutionGraph, *, settings: Settings | None = None
) -> SharedExecutionGraph:
    """首次固化图；已有图只能恢复并原样复用。"""
    existing = restore_shared_execution_graph(
        getattr(run, "shared_execution_graph_json", None), settings=settings
    )
    if existing is not None:
        if existing.plan_digest != graph.plan_digest:
            raise ValueError("共享执行图 plan digest 不匹配")
        return existing
    run.shared_execution_graph_json = dump_shared_execution_graph(graph, settings=settings)
    if getattr(run, "shared_execution_state_json", None) is None:
        run.shared_execution_state_json = dump_shared_execution_state(
            SharedExecutionState(plan_digest=graph.plan_digest),
            settings=settings,
            budget=graph.frozen_budget,
        )
    return graph


def ready_waves(
    graph: SharedExecutionGraph,
    state: SharedExecutionState | None = None,
) -> list[list[GraphNode]]:
    """按 Kahn 算法生成稳定 ready 波次；终态节点不会再次入队。"""
    outcomes = {item.node_id: item for item in (state.outcomes if state else [])}
    terminal = set(outcomes)
    by_id = {node.id: node for node in graph.nodes}
    remaining = set(by_id) - terminal
    waves: list[list[GraphNode]] = []
    while remaining:
        ready = [
            by_id[node_id]
            for node_id in remaining
            if all(dep in terminal for dep in by_id[node_id].dependencies)
        ]
        if not ready:
            raise ValueError("共享执行图存在未满足依赖或循环")
        ready.sort(key=lambda node: int(node.id[1:]))
        waves.append(ready)
        for node in ready:
            remaining.remove(node.id)
            terminal.add(node.id)
    return waves


def validate_shared_execution_state(
    graph: SharedExecutionGraph,
    state: SharedExecutionState,
) -> None:
    """校验 state 只包含当前图节点且每个结果绑定正确 fingerprint。"""
    if state.plan_digest != graph.plan_digest:
        raise ValueError("共享执行状态 plan digest 不匹配")
    by_id = {node.id: node for node in graph.nodes}
    seen: set[str] = set()
    for outcome in state.outcomes:
        if outcome.node_id in seen or outcome.node_id not in by_id:
            raise ValueError("共享执行状态节点引用非法")
        if outcome.fingerprint != by_id[outcome.node_id].fingerprint:
            raise ValueError("共享执行状态 node fingerprint 不匹配")
        seen.add(outcome.node_id)


def allocate_wave_quota(
    nodes: list[GraphNode],
    *,
    budget: SharedExecutionBudget,
    remaining_tool_calls: int | None = None,
    remaining_entries: int | None = None,
    remaining_evidence: int | None = None,
    remaining_buckets: int | None = None,
) -> dict[str, dict[str, int]]:
    """按稳定 node id 预分配额度，避免并发完成先后影响结果。"""
    quotas = {
        "tool_calls": max(
            0, budget.max_tool_calls if remaining_tool_calls is None else remaining_tool_calls
        ),
        "entries": max(0, budget.max_entries if remaining_entries is None else remaining_entries),
        "evidence": max(
            0, budget.max_evidence if remaining_evidence is None else remaining_evidence
        ),
        "buckets": max(0, budget.max_buckets if remaining_buckets is None else remaining_buckets),
    }
    allocation: dict[str, dict[str, int]] = {}
    for node in sorted(nodes, key=lambda item: int(item.id[1:])):
        wants = {
            "tool_calls": 1,
            "entries": budget.max_entries
            if node.kind
            in {"semantic_entry_set", "structured_entry_set", "entry_list", "entry_content"}
            else 0,
            "evidence": budget.max_evidence if node.kind == "entry_evidence" else 0,
            "buckets": budget.max_buckets if node.kind == "aggregate_group_count" else 0,
        }
        granted = {key: min(value, quotas[key]) for key, value in wants.items()}
        if node.kind == "entry_evidence" and granted["evidence"] == 0:
            granted["tool_calls"] = 0
        allocation[node.id] = granted
        for key, value in granted.items():
            quotas[key] -= value
    return allocation


def stable_result_handle(fingerprint: str, output_slot: str = "result") -> str:
    """绑定节点 fingerprint 与输出槽的稳定句柄。"""
    if len(fingerprint) != 64:
        raise ValueError("节点 fingerprint 非法")
    digest = hashlib.sha256(f"{fingerprint}:{output_slot}".encode()).hexdigest()[:32]
    return f"res_{digest}"


def materialize_composite_execution(
    plan: NormalizedCompositeAnswerPlan,
    graph: SharedExecutionGraph,
    state: SharedExecutionState,
) -> CompositeAnswerExecutionSnapshot:
    """把图 state 确定性投影回既有 v1 execution snapshot。"""
    if graph.plan_digest != state.plan_digest or graph.plan_digest != plan_digest(plan):
        raise ValueError("共享执行图与计划摘要不匹配")
    validate_shared_execution_state(graph, state)
    node_by_id = {node.id: node for node in graph.nodes}
    outcome_by_id = {outcome.node_id: outcome for outcome in state.outcomes}
    planned = {item.id: item for item in [*plan.retrieval_requests, *plan.structured_requests]}
    inputs: list[CompositeExecutionInputSnapshot] = []
    facts: list[CompositeToolFact] = []
    for request_id, node_ids in graph.original_request_map.items():
        request = planned.get(request_id)
        if request is None:
            raise ValueError("图映射引用未知请求")
        outcomes = [outcome_by_id[node_id] for node_id in node_ids if node_id in outcome_by_id]
        if not outcomes:
            continue
        status = "completed"
        completeness = "complete"
        errors: list[str] = []
        entry_ids: list[int] = []
        evidence_handles: list[str] = []
        result_handles: list[str] = []
        for outcome in outcomes:
            if outcome.status in {"failed", "cancelled"}:
                status = "error" if outcome.status == "failed" else "cancelled"
            elif outcome.status in {"partial", "limited"} and status == "completed":
                status = outcome.status
            if outcome.completeness != "complete":
                completeness = outcome.completeness
            if outcome.error:
                errors.append(outcome.error)
            payload = outcome.result or {}
            entry_ids.extend(
                int(value) for value in payload.get("entry_ids", []) if isinstance(value, int)
            )
            evidence_handles.extend(str(value) for value in payload.get("evidence_handles", []))
            if outcome.result_handle:
                result_handles.append(outcome.result_handle)
            node = node_by_id[outcome.node_id]
            if node.kind.startswith("aggregate_") or node.kind == "entry_list":
                slot = (
                    "count"
                    if node.kind == "aggregate_count"
                    else "group_count"
                    if node.kind == "aggregate_group_count"
                    else "entries"
                )
                text = str(payload.get("text") or payload.get("summary") or f"{slot} 结果")
                facts.append(
                    CompositeToolFact(
                        handle=outcome.result_handle
                        or stable_result_handle(outcome.fingerprint, slot),
                        request_id=request_id,
                        requirement_ids=node.consumer_requirement_ids or request.requirement_ids,
                        kind=slot,
                        text=text[:2000],
                        completeness=outcome.completeness,
                        summary={key: value for key, value in payload.items() if key != "text"},
                    )
                )
        if (
            status == "completed"
            and not entry_ids
            and any(node_by_id[item.node_id].kind == "semantic_entry_set" for item in outcomes)
        ):
            status = "empty"
        inputs.append(
            CompositeExecutionInputSnapshot(
                request_id=request_id,
                kind="retrieval" if request_id.startswith("q") else "structured",
                requirement_ids=request.requirement_ids,
                fingerprint=outcomes[-1].fingerprint,
                status=status,
                completeness=completeness,
                entry_ids=list(dict.fromkeys(entry_ids)),
                evidence_handles=list(dict.fromkeys(evidence_handles)),
                result_handles=list(dict.fromkeys(result_handles)),
                error="；".join(dict.fromkeys(errors))[:500] if errors else None,
            )
        )
    inputs.sort(key=lambda item: (0 if item.kind == "retrieval" else 1, item.request_id))
    facts.sort(key=lambda item: (item.request_id, item.kind, item.handle))
    return CompositeAnswerExecutionSnapshot(inputs=inputs, tool_facts=facts)


async def run_graph_scheduler(
    graph: SharedExecutionGraph,
    *,
    state: SharedExecutionState | None = None,
    execute_node,
    cancel_check=None,
) -> SharedExecutionState:
    """执行确定性拓扑波次；白名单节点可受限并行，协调器按 node id 接纳结果。"""
    current = state or SharedExecutionState(plan_digest=graph.plan_digest)
    validate_shared_execution_state(graph, current)
    outcomes = {item.node_id: item for item in current.outcomes}
    for wave in ready_waves(graph, current):
        if cancel_check is not None:
            await cancel_check()
        quotas = allocate_wave_quota(wave, budget=graph.frozen_budget)
        parallel = [node for node in wave if node.parallel_eligible]
        serial = [node for node in wave if not node.parallel_eligible]

        async def run_one(
            node: GraphNode,
            wave_quotas: dict[str, dict[str, int]] = quotas,
        ) -> tuple[str, NodeOutcome]:
            try:
                if cancel_check is not None:
                    await cancel_check()
                deps = {dep: outcomes[dep] for dep in node.dependencies if dep in outcomes}
                blocked = [item for item in deps.values() if item.status in {"failed", "cancelled"}]
                if blocked:
                    return node.id, NodeOutcome(
                        node_id=node.id,
                        fingerprint=node.fingerprint,
                        status="failed",
                        completeness="unknown",
                        error="上游节点失败，未执行当前节点",
                        upstream_fingerprints=[item.fingerprint for item in blocked],
                    )
                result = await execute_node(node, deps, wave_quotas[node.id])
                if isinstance(result, NodeOutcome):
                    outcome = result
                else:
                    outcome = NodeOutcome(
                        node_id=node.id,
                        fingerprint=node.fingerprint,
                        status="completed",
                        result=result if isinstance(result, dict) else {"value": result},
                        result_handle=stable_result_handle(node.fingerprint, node.kind),
                    )
                return node.id, outcome
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                return node.id, NodeOutcome(
                    node_id=node.id,
                    fingerprint=node.fingerprint,
                    status="failed",
                    completeness="unknown",
                    error=str(exc)[:500],
                )

        results: list[tuple[str, NodeOutcome]] = []
        if parallel:
            semaphore = asyncio.Semaphore(graph.frozen_budget.max_concurrency)

            async def limited(
                node: GraphNode,
                wave_semaphore: asyncio.Semaphore = semaphore,
            ) -> tuple[str, NodeOutcome]:
                async with wave_semaphore:
                    return await run_one(node)

            results.extend(await asyncio.gather(*(limited(node) for node in parallel)))
        for node in serial:
            results.append(await run_one(node))
        for node_id, outcome in sorted(results, key=lambda item: int(item[0][1:])):
            if cancel_check is not None:
                await cancel_check()
            outcomes[node_id] = outcome
        current = SharedExecutionState(
            plan_digest=graph.plan_digest, outcomes=list(outcomes.values())
        )
    return current


class SharedExecutionNodeExecutor:
    """闭合节点适配器注册表；调用方注入只读 handler。"""

    def __init__(self, handlers: dict[str, Any] | None = None):
        self.handlers = handlers or {}

    async def __call__(
        self, node: GraphNode, dependencies: dict[str, NodeOutcome], quota: dict[str, int]
    ) -> dict[str, Any]:
        handler = self.handlers.get(node.kind)
        if handler is None:
            raise ValueError(f"未注册共享图节点适配器：{node.kind}")
        result = handler(node, dependencies, quota)
        if hasattr(result, "__await__"):
            result = await result
        return result


async def execute_graph_node(
    db: Any,
    ctx: Any,
    node: GraphNode,
    dependencies: dict[str, NodeOutcome],
    *,
    cancel_check,
) -> dict[str, Any]:
    """默认只读节点适配器，范围始终来自 RunToolContext。"""
    from app.services.knowledge_agent.tools import (
        read_entries,
        search_confirmed_knowledge,
    )

    await cancel_check()
    params = node.normalized_params
    if node.kind == "semantic_entry_set":
        output = await search_confirmed_knowledge(
            db,
            ctx,
            str(params["query"]),
            recall_limit=min(
                int(params.get("max_entries", 30)),
                int(node.normalized_params.get("max_entries", 30)),
            ),
            context_limit=int(params.get("max_entries", 30)),
        )
        return {"entry_ids": [item.entry_id for item in output.items], "completeness": "limited"}
    if node.kind == "structured_entry_set":
        return {"entry_set": params.get("entry_set", {})}
    if node.kind in {"entry_content", "entry_list"}:
        source = dependencies.get(str(params.get("source")))
        source_payload = source.result or {} if source else {}
        entry_ids = list(source_payload.get("entry_ids", []))
        if node.kind == "entry_content":
            output = await read_entries(db, ctx, entry_ids)
            return {
                "entry_ids": [item.entry_id for item in output.items],
                "evidence_handles": [],
            }
        if "entry_set" in source_payload:
            from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
            from app.services.knowledge_agent.structured_query import (
                NormalizedEntrySetSpec,
                NormalizedEntrySort,
            )
            from app.services.knowledge_agent.structured_query_tools import (
                STRUCTURED_QUERY_TOOL_REGISTRY,
                STRUCTURED_QUERY_TOOL_VERSION,
            )

            entry_set = NormalizedEntrySetSpec.model_validate(source_payload["entry_set"])
            sort = NormalizedEntrySort.model_validate(
                params.get("sort", {"field": "updated_at", "direction": "desc"})
            )
            dispatched = await dispatch_read_tool(
                db,
                ctx,
                tool_name="query_entries",
                tool_version=STRUCTURED_QUERY_TOOL_VERSION,
                params={
                    "entry_set": entry_set.model_dump(mode="json", by_alias=True),
                    "limit": int(params.get("limit", 30)),
                    "sort": sort.model_dump(mode="json"),
                },
                budget=ReadToolBudget(max_calls=1, timeout_seconds=30, max_result_bytes=16000),
                cancel_check=cancel_check,
                registry=STRUCTURED_QUERY_TOOL_REGISTRY,
            )
            items = list(dispatched.payload.get("items", []))
            return {
                "entry_ids": [
                    item.get("entry_id") for item in items if item.get("entry_id") is not None
                ],
                "items": items,
                "has_more": bool(dispatched.payload.get("has_more")),
                "completeness": dispatched.completeness,
            }
        return {"entry_ids": entry_ids[: int(params.get("limit", len(entry_ids)))]}
    if node.kind == "entry_evidence":
        source = dependencies.get(str(params.get("source")))
        entry_ids = list((source.result or {}).get("entry_ids", [])) if source else []
        return {"entry_ids": entry_ids, "evidence_handles": []}
    if node.kind in {"aggregate_count", "aggregate_group_count"}:
        from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
        from app.services.knowledge_agent.structured_query import NormalizedEntrySetSpec
        from app.services.knowledge_agent.structured_query_tools import (
            STRUCTURED_QUERY_TOOL_REGISTRY,
            STRUCTURED_QUERY_TOOL_VERSION,
        )

        entry_set = NormalizedEntrySetSpec.model_validate(params["entry_set"])
        operation = "count" if node.kind == "aggregate_count" else "group_count"
        request = {
            "entry_set": entry_set.model_dump(mode="json", by_alias=True),
            "operation": operation,
        }
        if operation == "group_count":
            request["group_by"] = params.get("group_by")
        dispatched = await dispatch_read_tool(
            db,
            ctx,
            tool_name="aggregate_entries",
            tool_version=STRUCTURED_QUERY_TOOL_VERSION,
            params=request,
            budget=ReadToolBudget(
                max_calls=1,
                timeout_seconds=30,
                max_result_bytes=16000,
            ),
            cancel_check=cancel_check,
            registry=STRUCTURED_QUERY_TOOL_REGISTRY,
        )
        return {
            **dispatched.payload,
            "completeness": dispatched.completeness,
            "status": dispatched.status,
        }
    raise ValueError(f"未知共享图节点：{node.kind}")


async def execute_shared_execution_graph_plan(
    db: Any,
    run: Any,
    ctx: Any,
    plan: NormalizedCompositeAnswerPlan,
    *,
    cancel_check,
    settings: Settings | None = None,
) -> Any:
    """共享图执行入口。

    图快照先于任何工具调用写入 Run；当前兼容执行器负责生成既有 v1
    结果，再由协调器把结果绑定到图节点 state。这样旧综合器无需感知内部图，
    且后续可逐步替换节点适配器而不改变公开协议。
    """
    from app.services.knowledge_agent.composite_answer_execution import (
        execute_composite_answer_plan,
    )

    active = settings or get_settings()
    scope = run_scope_fingerprint(
        owner_user_id=run.owner_user_id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        scope_type=run.scope_type,
    )
    graph = restore_shared_execution_graph(
        getattr(run, "shared_execution_graph_json", None), settings=active
    )
    if graph is None:
        graph = compile_shared_execution_graph(
            plan,
            scope_fingerprint=scope,
            settings=active,
        )
        persist_shared_execution_graph(run, graph, settings=active)
        await db.commit()
    elif graph.plan_digest != plan_digest(plan):
        raise ValueError("共享执行图 plan digest 不匹配")
    state = restore_shared_execution_state(
        getattr(run, "shared_execution_state_json", None),
        settings=active,
        budget=graph.frozen_budget,
    ) or SharedExecutionState(plan_digest=graph.plan_digest)
    await cancel_check()
    artifacts = await execute_composite_answer_plan(
        db,
        run,
        ctx,
        plan,
        cancel_check=cancel_check,
        deduplicate_equivalent_requests=True,
    )
    # 将兼容快照按 request 映射为节点终态；每个节点只写一份 result handle。
    outcomes: list[NodeOutcome] = []
    input_by_request = {item.request_id: item for item in artifacts.snapshot.inputs}
    for node in graph.nodes:
        request_id = node.consumer_request_ids[0] if node.consumer_request_ids else None
        item = input_by_request.get(request_id) if request_id else None
        status = "completed" if item is None else item.status
        if status in {"denied", "error"}:
            status = "failed"
        payload: dict[str, Any] = {}
        if item is not None:
            payload = {
                "entry_ids": item.entry_ids,
                "evidence_handles": item.evidence_handles,
                "result_handles": item.result_handles,
            }
        outcomes.append(
            NodeOutcome(
                node_id=node.id,
                fingerprint=node.fingerprint,
                status=status,
                completeness=item.completeness if item is not None else "complete",
                result_handle=stable_result_handle(node.fingerprint, node.kind),
                result=payload,
                error=item.error if item is not None else None,
                reused=len(node.consumer_request_ids) > 1,
            )
        )
    state = SharedExecutionState(
        plan_digest=graph.plan_digest,
        outcomes=outcomes,
    )
    run.shared_execution_state_json = dump_shared_execution_state(
        state,
        settings=active,
        budget=graph.frozen_budget,
    )
    await db.commit()
    return artifacts


__all__ = [
    "GraphNode",
    "NodeOutcome",
    "SharedExecutionBudget",
    "SharedExecutionGraphBudget",
    "FrozenBudget",
    "SharedExecutionGraph",
    "SharedExecutionState",
    "compile_shared_execution_graph",
    "validate_shared_execution_graph",
    "validate_shared_execution_state",
    "dump_shared_execution_graph",
    "dump_shared_execution_state",
    "restore_shared_execution_graph",
    "restore_shared_execution_state",
    "persist_shared_execution_graph",
    "canonical_node_key",
    "node_fingerprint",
    "ready_waves",
    "allocate_wave_quota",
    "stable_result_handle",
    "materialize_composite_execution",
    "execute_shared_execution_graph_plan",
    "run_graph_scheduler",
    "SharedExecutionNodeExecutor",
    "execute_graph_node",
    "plan_digest",
    "run_scope_fingerprint",
    "NODE_KINDS",
    "NODE_TERMINAL_STATUSES",
]
