"""quick 复合回答一次有界覆盖补查的闭合内部协议。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.coverage_repair import (
    COVERAGE_REPAIR_PLAN_PROMPT_VERSION,
    CoverageRepairPlanDraft,
    run_coverage_repair_planner,
)
from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import Settings, get_settings
from app.schemas.knowledge_agent import KnowledgeAnswerBasisOut, KnowledgeAnswerOut
from app.services.knowledge_agent.composite_answer import (
    NormalizedCompositeAnswerPlan,
    NormalizedCompositeRetrievalRequest,
    NormalizedCompositeStructuredRequest,
)
from app.services.knowledge_agent.composite_answer_response import CompositeAnswerResult
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
)
from app.services.knowledge_agent.observability import StageMeta, record_model_invocation
from app.services.knowledge_agent.structured_query import (
    StructuredQueryPlanError,
    normalize_structured_query_plan,
)

COVERAGE_REPAIR_SCHEMA_VERSION = "v1"
_COVERAGE_REPAIR_HARD_JSON_BYTES_LIMIT = 64_000

CoverageRepairStage = Literal[
    "baseline_ready",
    "plan_ready",
    "executing",
    "execution_ready",
    "skipped",
    "completed",
    "failed",
]
CoverageRepairStopReason = Literal[
    "not_needed",
    "not_repairable",
    "no_novel_request",
    "budget_exhausted",
    "planner_failed",
    "execution_failed",
    "synthesis_failed",
    "completed_with_gaps",
    "completed",
]


class StrictCoverageRepairModel(BaseModel):
    """补查持久化协议拒绝未知字段，避免恢复时扩大语义。"""

    model_config = ConfigDict(extra="forbid")


class CoverageRepairBudget(StrictCoverageRepairModel):
    """补查阶段在 planner 前固化的独立总预算。"""

    max_queries: int = Field(default=2, ge=1, le=4)
    max_structured_requests: int = Field(default=1, ge=0, le=2)
    max_nodes: int = Field(default=8, ge=1, le=24)
    max_tool_calls: int = Field(default=6, ge=1, le=24)
    max_entries: int = Field(default=20, ge=1, le=100)
    max_evidence: int = Field(default=20, ge=1, le=100)
    max_buckets: int = Field(default=16, ge=0, le=100)
    max_duration_ms: int = Field(default=15_000, ge=1000, le=60_000)
    max_plan_bytes: int = Field(default=12_000, ge=1000, le=30_000)
    max_graph_bytes: int = Field(default=16_000, ge=1000, le=30_000)
    max_state_bytes: int = Field(default=48_000, ge=1000, le=64_000)
    max_snapshot_bytes: int = Field(default=60_000, ge=1000, le=64_000)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> CoverageRepairBudget:
        active = settings or get_settings()
        return cls(
            max_queries=active.knowledge_agent_coverage_repair_max_queries,
            max_structured_requests=(
                active.knowledge_agent_coverage_repair_max_structured_requests
            ),
            max_nodes=active.knowledge_agent_coverage_repair_max_nodes,
            max_tool_calls=active.knowledge_agent_coverage_repair_max_tool_calls,
            max_entries=active.knowledge_agent_coverage_repair_max_entries,
            max_evidence=active.knowledge_agent_coverage_repair_max_evidence,
            max_buckets=active.knowledge_agent_coverage_repair_max_buckets,
            max_duration_ms=int(
                active.knowledge_agent_coverage_repair_timeout_seconds * 1000
            ),
            max_plan_bytes=active.knowledge_agent_coverage_repair_plan_bytes_limit,
            max_graph_bytes=active.knowledge_agent_coverage_repair_graph_bytes_limit,
            max_state_bytes=active.knowledge_agent_coverage_repair_state_bytes_limit,
            max_snapshot_bytes=(
                active.knowledge_agent_coverage_repair_snapshot_bytes_limit
            ),
        )


class CoverageRepairBaseline(StrictCoverageRepairModel):
    """补查失败时可原样恢复的首次合法结果。"""

    answer: KnowledgeAnswerOut
    coverage: CompositeAnswerCoverageSnapshot
    answer_basis: dict[str, Any]
    run_status: Literal["completed", "partial", "failed"]
    answer_fallback: bool = False
    fallback_summary: str | None = Field(default=None, max_length=4000)


class CoverageRepairSnapshot(StrictCoverageRepairModel):
    """补查控制检查点；它不向客户端投影。"""

    schema_version: Literal["v1"] = COVERAGE_REPAIR_SCHEMA_VERSION
    stage: CoverageRepairStage
    execution_mode: Literal["serial", "shared_graph"]
    frozen_budget: CoverageRepairBudget
    eligible_requirement_ids: list[str] = Field(default_factory=list, max_length=8)
    baseline: CoverageRepairBaseline
    planner_attempted: bool = False
    synthesis_attempted: bool = False
    final_result: CoverageRepairBaseline | None = None
    stop_reason: CoverageRepairStopReason | None = None
    error: str | None = Field(default=None, max_length=500)


class NormalizedCoverageRepairPlan(StrictCoverageRepairModel):
    """只包含新请求的服务端规范化补查计划。"""

    schema_version: Literal["v1"] = COVERAGE_REPAIR_SCHEMA_VERSION
    prompt_version: Literal["v1"] = COVERAGE_REPAIR_PLAN_PROMPT_VERSION
    target_requirement_ids: list[str] = Field(min_length=1, max_length=8)
    retrieval_requests: list[NormalizedCompositeRetrievalRequest] = Field(
        default_factory=list, max_length=4
    )
    structured_requests: list[NormalizedCompositeStructuredRequest] = Field(
        default_factory=list, max_length=2
    )


class CoverageRepairEligibility(StrictCoverageRepairModel):
    """服务端从实际 coverage 和执行派生的可修复目标。"""

    requirement_ids: list[str] = Field(default_factory=list, max_length=8)
    reasons: dict[str, Literal["missing_grove_basis", "limited_input", "input_failure"]] = (
        Field(default_factory=dict)
    )


class CoverageRepairPlanError(ValueError):
    """补查候选无法在不改写首次计划时安全执行。"""


class CoverageRepairNoNovelRequest(CoverageRepairPlanError):
    """候选为空或全部与首次请求等价。"""


def coverage_repair_material_from_result(
    result: CompositeAnswerResult,
) -> CoverageRepairBaseline:
    """把已校验结果固化为可恢复材料，不保存任何内部模型草稿。"""
    return CoverageRepairBaseline(
        answer=result.answer,
        coverage=result.coverage,
        answer_basis=result.answer_basis.model_dump(mode="json"),
        run_status=result.run_status,
        answer_fallback=result.answer_fallback,
    )


def coverage_repair_result_from_material(
    material: CoverageRepairBaseline,
) -> CompositeAnswerResult:
    """从控制快照恢复已校验结果。"""
    return CompositeAnswerResult(
        answer=material.answer,
        coverage=material.coverage,
        answer_basis=KnowledgeAnswerBasisOut.model_validate(material.answer_basis),
        run_status=material.run_status,
        answer_fallback=material.answer_fallback,
    )


def coverage_is_non_regressive(
    baseline: CompositeAnswerCoverageSnapshot,
    candidate: CompositeAnswerCoverageSnapshot,
) -> bool:
    """候选逐义务不得比首次合法 coverage 更差，也不得改变义务集合。"""
    rank = {"failed": 0, "insufficient": 1, "partial": 2, "answered": 3}
    before = {item.requirement_id: item.status for item in baseline.requirements}
    after = {item.requirement_id: item.status for item in candidate.requirements}
    return before.keys() == after.keys() and all(
        rank[after[item]] >= rank[status] for item, status in before.items()
    )


def coverage_repair_has_usable_results(
    execution: CompositeAnswerExecutionSnapshot,
) -> bool:
    """只有补查实际形成合法 Evidence/result 时才值得再次综合。"""
    return bool(
        execution.tool_facts
        or any(
            item.evidence_handles or item.result_handles for item in execution.inputs
        )
    )


class RepairRunStorageAdapter:
    """复用现有执行器，但只读写 Run 的补查检查点列。"""

    def __init__(self, run):
        object.__setattr__(self, "_run", run)

    def __getattr__(self, name: str):
        return getattr(self._run, name)

    @property
    def composite_answer_execution_json(self):
        return self._run.coverage_repair_execution_json

    @composite_answer_execution_json.setter
    def composite_answer_execution_json(self, value):
        self._run.coverage_repair_execution_json = value

    @property
    def shared_execution_graph_json(self):
        return self._run.coverage_repair_graph_json

    @shared_execution_graph_json.setter
    def shared_execution_graph_json(self, value):
        self._run.coverage_repair_graph_json = value

    @property
    def shared_execution_state_json(self):
        return self._run.coverage_repair_graph_state_json

    @shared_execution_state_json.setter
    def shared_execution_state_json(self, value):
        self._run.coverage_repair_graph_state_json = value


def coverage_repair_execution_plan(
    original_plan: NormalizedCompositeAnswerPlan,
    repair_plan: NormalizedCoverageRepairPlan,
) -> NormalizedCompositeAnswerPlan:
    """构造只含新请求的执行视图，不改写首次计划。"""
    return NormalizedCompositeAnswerPlan(
        requirements=original_plan.requirements,
        statement_message_ids=original_plan.statement_message_ids,
        retrieval_requests=repair_plan.retrieval_requests,
        structured_requests=repair_plan.structured_requests,
    )


def _repair_execution_settings(
    settings: Settings,
    budget: CoverageRepairBudget,
) -> Settings:
    """将已冻结补查总预算映射到既有串行/共享图执行器。"""
    return settings.model_copy(
        update={
            "knowledge_agent_composite_answer_execution_bytes_limit": budget.max_state_bytes,
            "knowledge_agent_composite_answer_max_entries": budget.max_entries,
            "knowledge_agent_composite_answer_max_evidence": budget.max_evidence,
            "knowledge_agent_composite_answer_execution_timeout_seconds": (
                budget.max_duration_ms / 1000
            ),
            "knowledge_agent_structured_query_max_tool_calls": budget.max_tool_calls,
            "knowledge_agent_structured_query_execution_timeout_seconds": (
                budget.max_duration_ms / 1000
            ),
            "knowledge_agent_structured_query_result_json_bytes_limit": min(
                settings.knowledge_agent_structured_query_result_json_bytes_limit,
                budget.max_state_bytes,
            ),
            "knowledge_agent_shared_execution_graph_max_nodes": budget.max_nodes,
            "knowledge_agent_shared_execution_graph_max_tool_calls": budget.max_tool_calls,
            "knowledge_agent_shared_execution_graph_max_entries": budget.max_entries,
            "knowledge_agent_shared_execution_graph_max_evidence": budget.max_evidence,
            "knowledge_agent_shared_execution_graph_max_buckets": budget.max_buckets,
            "knowledge_agent_shared_execution_graph_bytes_limit": budget.max_graph_bytes,
            "knowledge_agent_shared_execution_graph_state_bytes_limit": (
                budget.max_state_bytes
            ),
            "knowledge_agent_shared_execution_graph_timeout_seconds": (
                budget.max_duration_ms / 1000
            ),
        }
    )


def restore_coverage_repair_execution(
    raw: str | None,
    snapshot: CoverageRepairSnapshot,
    *,
    settings: Settings | None = None,
) -> CompositeAnswerExecutionSnapshot:
    """使用快照冻结字节预算恢复补查 execution。"""
    from app.services.knowledge_agent.composite_answer_execution import (
        restore_composite_execution,
    )

    active = settings or get_settings()
    bounded = _repair_execution_settings(active, snapshot.frozen_budget)
    return restore_composite_execution(raw, settings=bounded)


async def execute_coverage_repair(
    db,
    run,
    ctx,
    original_plan: NormalizedCompositeAnswerPlan,
    repair_plan: NormalizedCoverageRepairPlan,
    snapshot: CoverageRepairSnapshot,
    *,
    cancel_check,
    settings: Settings | None = None,
) -> tuple[CompositeAnswerExecutionSnapshot, CoverageRepairSnapshot]:
    """按基线固化模式只执行补查新请求并持久化检查点。"""
    active = settings or get_settings()
    bounded_settings = _repair_execution_settings(active, snapshot.frozen_budget)
    adapter = RepairRunStorageAdapter(run)
    execution_plan = coverage_repair_execution_plan(original_plan, repair_plan)
    executing = snapshot.model_copy(update={"stage": "executing"}, deep=True)
    run.coverage_repair_json = dump_coverage_repair_snapshot(
        executing, settings=active
    )
    await db.commit()
    await cancel_check()
    if snapshot.execution_mode == "shared_graph":
        from app.services.knowledge_agent.shared_execution_graph import (
            execute_shared_execution_graph_plan,
        )

        artifacts = await execute_shared_execution_graph_plan(
            db,
            adapter,
            ctx,
            execution_plan,
            cancel_check=cancel_check,
            settings=bounded_settings,
        )
    else:
        from app.services.knowledge_agent.composite_answer_execution import (
            execute_composite_answer_plan,
        )

        artifacts = await execute_composite_answer_plan(
            db,
            adapter,
            ctx,
            execution_plan,
            cancel_check=cancel_check,
            settings=bounded_settings,
            max_tool_calls=snapshot.frozen_budget.max_tool_calls,
        )
    await cancel_check()
    completed = executing.model_copy(update={"stage": "execution_ready"}, deep=True)
    run.coverage_repair_json = dump_coverage_repair_snapshot(completed, settings=active)
    await db.commit()
    return artifacts.snapshot, completed


def merge_composite_execution(
    original_plan: NormalizedCompositeAnswerPlan,
    original: CompositeAnswerExecutionSnapshot,
    repair_plan: NormalizedCoverageRepairPlan,
    repair: CompositeAnswerExecutionSnapshot,
) -> CompositeAnswerExecutionSnapshot:
    """保留首次输入并仅追加补查合法句柄，冲突时拒绝。"""
    original_ids = {
        item.id for item in [*original_plan.retrieval_requests, *original_plan.structured_requests]
    }
    repair_ids = {
        item.id for item in [*repair_plan.retrieval_requests, *repair_plan.structured_requests]
    }
    original_snapshot_ids = [item.request_id for item in original.inputs]
    repair_snapshot_ids = [item.request_id for item in repair.inputs]
    if (
        len(original_snapshot_ids) != len(set(original_snapshot_ids))
        or not set(original_snapshot_ids).issubset(original_ids)
        or len(repair_snapshot_ids) != len(set(repair_snapshot_ids))
        or not set(repair_snapshot_ids).issubset(repair_ids)
        or set(original_snapshot_ids).intersection(repair_snapshot_ids)
    ):
        raise ValueError("首次与补查执行快照的 request id 不一致")
    original_handles = {
        fact.handle for fact in original.tool_facts
    } | {handle for item in original.inputs for handle in item.result_handles}
    repair_handles = {fact.handle for fact in repair.tool_facts} | {
        handle for item in repair.inputs for handle in item.result_handles
    }
    if original_handles.intersection(repair_handles):
        raise ValueError("首次与补查执行快照的 result handle 冲突")
    return CompositeAnswerExecutionSnapshot(
        elapsed_ms=min(600_000, original.elapsed_ms + repair.elapsed_ms),
        inputs=[
            *(item.model_copy(deep=True) for item in original.inputs),
            *(item.model_copy(deep=True) for item in repair.inputs),
        ],
        tool_facts=[
            *(item.model_copy(deep=True) for item in original.tool_facts),
            *(item.model_copy(deep=True) for item in repair.tool_facts),
        ],
    )


def derive_repair_eligibility(
    plan: NormalizedCompositeAnswerPlan,
    execution: CompositeAnswerExecutionSnapshot,
    coverage: CompositeAnswerCoverageSnapshot,
) -> CoverageRepairEligibility:
    """只让能被现有 Grove 只读工具改善的真实缺口准入。"""
    requirement_by_id = {item.id: item for item in plan.requirements}
    inputs_by_requirement = {
        item.id: [row for row in execution.inputs if item.id in row.requirement_ids]
        for item in plan.requirements
    }
    ids: list[str] = []
    reasons: dict[str, str] = {}
    for row in coverage.requirements:
        requirement = requirement_by_id.get(row.requirement_id)
        if (
            requirement is None
            or row.status not in {"partial", "insufficient"}
            or requirement.basis_policy not in {"grove_only", "grove_required"}
        ):
            continue
        inputs = inputs_by_requirement[row.requirement_id]
        if any(item.status in {"partial", "denied", "error", "cancelled"} for item in inputs):
            reason = "input_failure"
        elif any(
            item.status in {"empty", "limited"} or item.completeness != "complete"
            for item in inputs
        ):
            reason = "limited_input"
        elif not row.evidence_handles and not row.result_handles:
            reason = "missing_grove_basis"
        else:
            # 已有完整 Grove 依据却仍 partial 通常是综合表达问题，
            # 现有工具补查不会提供更多可验证信息。
            continue
        ids.append(row.requirement_id)
        reasons[row.requirement_id] = reason
    return CoverageRepairEligibility(requirement_ids=ids, reasons=reasons)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def coverage_repair_request_signature(
    kind: Literal["retrieval", "structured"],
    payload: dict[str, Any],
    *,
    scope_fingerprint: str,
) -> str:
    """只对可证明等价的规范化只读请求生成稳定签名。"""
    raw = json.dumps(
        {
            "version": "coverage-repair-request-v1",
            "kind": kind,
            "payload": payload,
            "scope": scope_fingerprint,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _retrieval_signature(query: str, *, scope_fingerprint: str) -> str:
    return coverage_repair_request_signature(
        "retrieval",
        {"query": _clean_text(query), "completeness": "limited_or_unknown"},
        scope_fingerprint=scope_fingerprint,
    )


def _structured_signature(query_plan, *, scope_fingerprint: str) -> str:
    return coverage_repair_request_signature(
        "structured",
        query_plan.model_dump(mode="json", by_alias=True),
        scope_fingerprint=scope_fingerprint,
    )


def normalize_coverage_repair_plan(
    candidate: CoverageRepairPlanDraft | dict,
    *,
    original_plan: NormalizedCompositeAnswerPlan,
    eligible_requirement_ids: set[str],
    scope_fingerprint: str,
    budget: CoverageRepairBudget,
    settings: Settings | None = None,
) -> NormalizedCoverageRepairPlan:
    """校验目标、B1 结构和精确重复，再生成接续稳定 id。"""
    active = settings or get_settings()
    try:
        draft = (
            candidate
            if isinstance(candidate, CoverageRepairPlanDraft)
            else CoverageRepairPlanDraft.model_validate(candidate)
        )
    except ValidationError as exc:
        raise CoverageRepairPlanError(f"补查计划 schema 非法：{exc}") from exc

    targets = list(dict.fromkeys(draft.target_requirement_ids))
    unknown_targets = sorted(set(targets) - eligible_requirement_ids)
    if unknown_targets:
        raise CoverageRepairPlanError(f"补查引用非准入义务：{unknown_targets}")
    request_count = len(draft.retrieval_requests) + len(draft.structured_requests)
    if request_count == 0:
        raise CoverageRepairNoNovelRequest("模型未提出新补查请求")
    if not targets:
        raise CoverageRepairPlanError("非空补查请求必须声明目标义务")
    if request_count > budget.max_queries:
        raise CoverageRepairPlanError("补查查询数超过冻结预算")
    if len(draft.structured_requests) > budget.max_structured_requests:
        raise CoverageRepairPlanError("补查结构化请求数超过冻结预算")
    raw_ids = [item.id for item in [*draft.retrieval_requests, *draft.structured_requests]]
    if len(raw_ids) != len(set(raw_ids)):
        raise CoverageRepairPlanError("补查请求 id 不得重复")

    retrieval: list[NormalizedCompositeRetrievalRequest] = []
    structured: list[NormalizedCompositeStructuredRequest] = []
    referenced_targets: set[str] = set()
    for index, item in enumerate(
        draft.retrieval_requests, start=len(original_plan.retrieval_requests) + 1
    ):
        query = _clean_text(item.query)
        requirement_ids = list(dict.fromkeys(item.requirement_ids))
        if not query:
            raise CoverageRepairPlanError("补查检索文本不能为空")
        if not set(requirement_ids).issubset(set(targets)):
            raise CoverageRepairPlanError("补查检索引用了未声明目标")
        referenced_targets.update(requirement_ids)
        retrieval.append(
            NormalizedCompositeRetrievalRequest(
                id=f"q{index}", query=query, requirement_ids=requirement_ids
            )
        )
    for index, item in enumerate(
        draft.structured_requests, start=len(original_plan.structured_requests) + 1
    ):
        requirement_ids = list(dict.fromkeys(item.requirement_ids))
        if not set(requirement_ids).issubset(set(targets)):
            raise CoverageRepairPlanError("补查结构化请求引用了未声明目标")
        try:
            query_plan = normalize_structured_query_plan(
                StructuredQueryPlanDraft(
                    entry_set=item.entry_set,
                    outputs=item.outputs,
                    reason="",
                ),
                settings=active,
            )
        except StructuredQueryPlanError as exc:
            raise CoverageRepairPlanError(f"补查结构化请求非法：{exc}") from exc
        referenced_targets.update(requirement_ids)
        structured.append(
            NormalizedCompositeStructuredRequest(
                id=f"s{index}", query_plan=query_plan, requirement_ids=requirement_ids
            )
        )
    if set(targets) != referenced_targets:
        raise CoverageRepairPlanError("每个补查目标义务必须至少关联一份新请求")

    original_signatures = {
        *(
            _retrieval_signature(item.query, scope_fingerprint=scope_fingerprint)
            for item in original_plan.retrieval_requests
        ),
        *(
            _structured_signature(item.query_plan, scope_fingerprint=scope_fingerprint)
            for item in original_plan.structured_requests
        ),
    }
    new_signatures = [
        *(
            _retrieval_signature(item.query, scope_fingerprint=scope_fingerprint)
            for item in retrieval
        ),
        *(
            _structured_signature(item.query_plan, scope_fingerprint=scope_fingerprint)
            for item in structured
        ),
    ]
    duplicate_count = sum(item in original_signatures for item in new_signatures)
    duplicate_count += len(new_signatures) - len(set(new_signatures))
    if duplicate_count:
        if duplicate_count >= len(new_signatures):
            raise CoverageRepairNoNovelRequest("补查请求全部与已完成请求等价")
        raise CoverageRepairPlanError("补查候选混合了重复与新请求")

    plan = NormalizedCoverageRepairPlan(
        target_requirement_ids=targets,
        retrieval_requests=retrieval,
        structured_requests=structured,
    )
    dump_coverage_repair_plan(plan, budget=budget, settings=active)
    return plan


def dump_coverage_repair_snapshot(
    snapshot: CoverageRepairSnapshot, *, settings: Settings | None = None
) -> str:
    """在完整基线无法写入时直接失败，不截断回答。"""
    raw = snapshot.model_dump_json(exclude_none=True)
    limit = min(
        _COVERAGE_REPAIR_HARD_JSON_BYTES_LIMIT,
        snapshot.frozen_budget.max_snapshot_bytes,
    )
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("覆盖补查控制快照超过 JSON 字节预算")
    return raw


def restore_coverage_repair_snapshot(
    raw: str | None, *, settings: Settings | None = None
) -> CoverageRepairSnapshot | None:
    """旧 Run 空字段返回 None，非法历史快照不猜测。"""
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > _COVERAGE_REPAIR_HARD_JSON_BYTES_LIMIT:
        raise ValueError("覆盖补查控制快照超过 JSON 字节预算")
    try:
        snapshot = CoverageRepairSnapshot.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"覆盖补查控制快照非法：{exc}") from exc
    if len(raw.encode("utf-8")) > snapshot.frozen_budget.max_snapshot_bytes:
        raise ValueError("覆盖补查控制快照超过冻结预算")
    return snapshot


def dump_coverage_repair_plan(
    plan: NormalizedCoverageRepairPlan,
    *,
    budget: CoverageRepairBudget,
    settings: Settings | None = None,
) -> str:
    """计划按 planner 前冻结的字节预算固化。"""
    raw = plan.model_dump_json(exclude_none=True)
    if len(raw.encode("utf-8")) > budget.max_plan_bytes:
        raise ValueError("覆盖补查计划超过 JSON 字节预算")
    return raw


def restore_coverage_repair_plan(
    raw: str | None,
    *,
    budget: CoverageRepairBudget,
    settings: Settings | None = None,
) -> NormalizedCoverageRepairPlan | None:
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > budget.max_plan_bytes:
        raise ValueError("覆盖补查计划超过 JSON 字节预算")
    try:
        return NormalizedCoverageRepairPlan.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"覆盖补查计划非法：{exc}") from exc


async def plan_and_persist_coverage_repair(
    db,
    run,
    snapshot: CoverageRepairSnapshot,
    *,
    original_plan: NormalizedCompositeAnswerPlan,
    original_execution: CompositeAnswerExecutionSnapshot,
    current_message: str,
    scope_fingerprint: str,
    cancel_check,
    settings: Settings | None = None,
) -> tuple[NormalizedCoverageRepairPlan | None, CoverageRepairSnapshot]:
    """复用已固化计划或最多调用一次 planner，一并提交审计。"""
    active = settings or get_settings()
    existing = restore_coverage_repair_plan(
        getattr(run, "coverage_repair_plan_json", None),
        budget=snapshot.frozen_budget,
        settings=active,
    )
    if existing is not None:
        return existing, snapshot
    if snapshot.planner_attempted:
        interrupted = snapshot.model_copy(
            update={
                "stage": "failed",
                "stop_reason": "planner_failed",
                "error": snapshot.error or "补查规划未形成可恢复计划",
            },
            deep=True,
        )
        run.coverage_repair_json = dump_coverage_repair_snapshot(
            interrupted, settings=active
        )
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=StageMeta(
                purpose="coverage_repair_plan",
                provider="server",
                model=None,
                is_fallback=True,
                error=interrupted.error,
                duration_ms=0,
            ),
            prompt_version=COVERAGE_REPAIR_PLAN_PROMPT_VERSION,
        )
        await db.commit()
        return None, interrupted

    requirements = [
        {
            "id": item.id,
            "summary": item.summary,
            "kind": item.kind,
            "basis_policy": item.basis_policy,
            "coverage_status": next(
                row.status
                for row in snapshot.baseline.coverage.requirements
                if row.requirement_id == item.id
            ),
            "coverage_note": next(
                row.note
                for row in snapshot.baseline.coverage.requirements
                if row.requirement_id == item.id
            ),
        }
        for item in original_plan.requirements
    ]
    executed_inputs = [
        {
            "request_id": item.request_id,
            "kind": item.kind,
            "requirement_ids": item.requirement_ids,
            "status": item.status,
            "completeness": item.completeness,
            "error": item.error,
        }
        for item in original_execution.inputs
    ]
    await cancel_check()
    attempted = snapshot.model_copy(update={"planner_attempted": True}, deep=True)
    run.coverage_repair_json = dump_coverage_repair_snapshot(
        attempted, settings=active
    )
    await db.commit()
    candidate, meta = await run_coverage_repair_planner(
        db,
        run.workspace_id,
        current_message=current_message,
        requirements=requirements,
        eligible_requirement_ids=snapshot.eligible_requirement_ids,
        executed_inputs=executed_inputs,
        budget=snapshot.frozen_budget.model_dump(mode="json"),
    )
    plan = None
    updated = attempted.model_copy(deep=True)
    if candidate is None:
        updated.stage = "failed"
        updated.stop_reason = "planner_failed"
        updated.error = meta.error or "覆盖补查规划失败"
    else:
        try:
            plan = normalize_coverage_repair_plan(
                candidate,
                original_plan=original_plan,
                eligible_requirement_ids=set(snapshot.eligible_requirement_ids),
                scope_fingerprint=scope_fingerprint,
                budget=snapshot.frozen_budget,
                settings=active,
            )
        except CoverageRepairNoNovelRequest as exc:
            updated.stage = "skipped"
            updated.stop_reason = "no_novel_request"
            updated.error = str(exc)[:500]
        except CoverageRepairPlanError as exc:
            meta = replace(
                meta,
                is_fallback=True,
                error=f"覆盖补查计划校验失败：{exc}",
            )
            updated.stage = "failed"
            updated.stop_reason = "planner_failed"
            updated.error = str(exc)[:500]
    await cancel_check()
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=meta,
        prompt_version=COVERAGE_REPAIR_PLAN_PROMPT_VERSION,
    )
    if plan is not None:
        run.coverage_repair_plan_json = dump_coverage_repair_plan(
            plan, budget=snapshot.frozen_budget, settings=active
        )
        updated.stage = "plan_ready"
        updated.stop_reason = None
        updated.error = None
    run.coverage_repair_json = dump_coverage_repair_snapshot(updated, settings=active)
    await db.commit()
    return plan, updated
