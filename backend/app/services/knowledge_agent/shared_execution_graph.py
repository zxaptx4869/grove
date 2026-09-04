"""Knowledge Agent quick 复合回答共享执行图领域模型。

图是服务端从已规范化计划编译出的内部快照。模型与客户端不能提交图控制
字段；所有模型使用 ``extra=forbid``，恢复时也不会扩大历史 JSON 的语义。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import Settings, get_settings
from app.services.knowledge_agent.composite_answer import NormalizedCompositeAnswerPlan

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
    raw: str | None, *, settings: Settings | None = None
) -> SharedExecutionGraph | None:
    """恢复图；旧 Run 的空字段返回 None，损坏快照直接失败。"""
    if raw is None:
        return None
    active = settings or get_settings()
    if len(raw.encode("utf-8")) > active.knowledge_agent_shared_execution_graph_bytes_limit:
        raise ValueError("共享执行图超过 JSON 字节预算")
    try:
        return SharedExecutionGraph.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"共享执行图快照非法：{exc}") from exc


def restore_shared_execution_state(
    raw: str | None,
    *,
    settings: Settings | None = None,
    budget: SharedExecutionBudget | None = None,
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
    "dump_shared_execution_graph",
    "dump_shared_execution_state",
    "restore_shared_execution_graph",
    "restore_shared_execution_state",
    "persist_shared_execution_graph",
    "plan_digest",
    "run_scope_fingerprint",
    "NODE_KINDS",
    "NODE_TERMINAL_STATUSES",
]
