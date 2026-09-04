"""quick 复合回答一次有界覆盖补查的闭合内部协议。"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings
from app.schemas.knowledge_agent import KnowledgeAnswerOut
from app.services.knowledge_agent.composite_answer import (
    NormalizedCompositeRetrievalRequest,
    NormalizedCompositeStructuredRequest,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
)

COVERAGE_REPAIR_SCHEMA_VERSION = "v1"
COVERAGE_REPAIR_PLAN_PROMPT_VERSION = "v1"

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


def dump_coverage_repair_snapshot(
    snapshot: CoverageRepairSnapshot, *, settings: Settings | None = None
) -> str:
    """在完整基线无法写入时直接失败，不截断回答。"""
    active = settings or get_settings()
    raw = snapshot.model_dump_json(exclude_none=True)
    limit = min(
        active.knowledge_agent_coverage_repair_snapshot_bytes_limit,
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
    active = settings or get_settings()
    if len(raw.encode("utf-8")) > active.knowledge_agent_coverage_repair_snapshot_bytes_limit:
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
    """计划固化前同时校验现行和快照字节上限。"""
    active = settings or get_settings()
    raw = plan.model_dump_json(exclude_none=True)
    limit = min(active.knowledge_agent_coverage_repair_plan_bytes_limit, budget.max_plan_bytes)
    if len(raw.encode("utf-8")) > limit:
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
    active = settings or get_settings()
    if len(raw.encode("utf-8")) > min(
        active.knowledge_agent_coverage_repair_plan_bytes_limit, budget.max_plan_bytes
    ):
        raise ValueError("覆盖补查计划超过 JSON 字节预算")
    try:
        return NormalizedCoverageRepairPlan.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(f"覆盖补查计划非法：{exc}") from exc
