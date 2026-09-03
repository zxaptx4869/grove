"""quick 复合回答候选计划的服务端规范化、固化与显式降级。"""

import json
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.composite_answer import (
    COMPOSITE_ANSWER_PLAN_PROMPT_VERSION,
    CompositeAnswerPlanDraft,
    run_composite_answer_planner,
)
from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import Settings, get_settings
from app.models.knowledge_agent import (
    BASIS_MODE_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_EXTERNAL_NEEDED,
    BASIS_STRATEGY_HYBRID,
    BASIS_STRATEGY_KNOWLEDGE_FIRST,
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_MODEL_FIRST,
    PURPOSE_COMPOSITE_ANSWER_PLAN,
)
from app.services.knowledge_agent.basis import (
    UserStatementCandidate,
    contains_knowledge_only_restriction,
)
from app.services.knowledge_agent.observability import record_model_invocation
from app.services.knowledge_agent.structured_query import (
    NormalizedStructuredQueryPlan,
    StructuredQueryPlanError,
    normalize_structured_query_plan,
)


class CompositeAnswerPlanError(ValueError):
    """候选复合计划无法在不改变核心语义时安全执行。"""


class StrictNormalizedCompositeModel(BaseModel):
    """规范化快照拒绝未知字段，恢复时不扩大历史语义。"""

    model_config = ConfigDict(extra="forbid")


class NormalizedCompositeRequirement(StrictNormalizedCompositeModel):
    """服务端稳定编号的回答义务。"""

    id: str = Field(pattern=r"^r[1-9][0-9]*$")
    order: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=300)
    kind: Literal["explain", "retrieve", "aggregate", "compare", "recommend", "other"]
    basis_policy: Literal[
        "grove_only",
        "grove_required",
        "model_allowed",
        "external_required",
    ]


class NormalizedCompositeRetrievalRequest(StrictNormalizedCompositeModel):
    """稳定编号的 Grove 检索输入。"""

    id: str = Field(pattern=r"^q[1-9][0-9]*$")
    query: str = Field(min_length=1, max_length=500)
    requirement_ids: list[str] = Field(min_length=1, max_length=20)


class NormalizedCompositeStructuredRequest(StrictNormalizedCompositeModel):
    """稳定编号并已通过 B1 校验的结构化输入。"""

    id: str = Field(pattern=r"^s[1-9][0-9]*$")
    query_plan: NormalizedStructuredQueryPlan
    requirement_ids: list[str] = Field(min_length=1, max_length=20)


class NormalizedCompositeAnswerPlan(StrictNormalizedCompositeModel):
    """唯一允许持久化和执行的 CompositeAnswerPlan v1。"""

    schema_version: Literal["v1"] = "v1"
    prompt_version: Literal["v1"] = COMPOSITE_ANSWER_PLAN_PROMPT_VERSION
    requirements: list[NormalizedCompositeRequirement] = Field(min_length=1, max_length=20)
    statement_message_ids: list[int] = Field(default_factory=list, max_length=20)
    retrieval_requests: list[NormalizedCompositeRetrievalRequest] = Field(
        default_factory=list,
        max_length=8,
    )
    structured_requests: list[NormalizedCompositeStructuredRequest] = Field(
        default_factory=list,
        max_length=5,
    )


def _clean_text(value: str) -> str:
    """折叠模型输出空白，避免空语义与指纹漂移。"""
    return " ".join(value.split())


def _mapped_requirement_ids(
    raw_ids: list[str],
    *,
    mapping: dict[str, str],
) -> list[str]:
    """校验并按回答义务自然顺序稳定去重关联。"""
    unknown = sorted({item for item in raw_ids if item not in mapping})
    if unknown:
        raise CompositeAnswerPlanError(f"输入请求引用未知回答义务：{unknown}")
    selected = {mapping[item] for item in raw_ids}
    return sorted(selected, key=lambda item: int(item[1:]))


def _compatibility_basis_strategy(plan: NormalizedCompositeAnswerPlan) -> str:
    """为旧诊断字段生成保守聚合值；它不再是复合执行事实源。"""
    policies = {item.basis_policy for item in plan.requirements}
    if policies == {"grove_only"}:
        return BASIS_STRATEGY_KNOWLEDGE_ONLY
    if "external_required" in policies:
        return BASIS_STRATEGY_EXTERNAL_NEEDED
    uses_grove = bool(policies & {"grove_only", "grove_required"})
    uses_model = bool(policies & {"model_allowed", "grove_required"})
    if uses_grove and uses_model:
        return BASIS_STRATEGY_HYBRID
    if uses_grove:
        return BASIS_STRATEGY_KNOWLEDGE_FIRST
    return BASIS_STRATEGY_MODEL_FIRST


def normalize_composite_answer_plan(
    candidate: CompositeAnswerPlanDraft | dict,
    *,
    allowed_statement_ids: set[int] | None = None,
    knowledge_only: bool = False,
    settings: Settings | None = None,
) -> NormalizedCompositeAnswerPlan:
    """严格校验并稳定化候选计划；任一核心错误都拒绝整份计划。"""
    active_settings = settings or get_settings()
    try:
        draft = (
            candidate
            if isinstance(candidate, CompositeAnswerPlanDraft)
            else CompositeAnswerPlanDraft.model_validate(candidate)
        )
    except ValidationError as exc:
        raise CompositeAnswerPlanError(f"计划 schema 非法：{exc}") from exc

    if len(draft.requirements) > active_settings.knowledge_agent_composite_answer_max_requirements:
        raise CompositeAnswerPlanError("回答义务数超过服务端预算")
    if (
        len(draft.retrieval_requests)
        > active_settings.knowledge_agent_composite_answer_max_retrieval_requests
    ):
        raise CompositeAnswerPlanError("Grove 检索请求数超过服务端预算")
    if (
        len(draft.structured_requests)
        > active_settings.knowledge_agent_composite_answer_max_structured_requests
    ):
        raise CompositeAnswerPlanError("结构化请求数超过服务端预算")

    raw_requirement_ids = [item.id for item in draft.requirements]
    if len(set(raw_requirement_ids)) != len(raw_requirement_ids):
        raise CompositeAnswerPlanError("回答义务 id 不得重复")
    ordered = sorted(enumerate(draft.requirements), key=lambda item: (item[1].order, item[0]))
    mapping = {item.id: f"r{index}" for index, (_, item) in enumerate(ordered, start=1)}
    requirements: list[NormalizedCompositeRequirement] = []
    for index, (_, item) in enumerate(ordered, start=1):
        summary = _clean_text(item.summary)
        if not summary:
            raise CompositeAnswerPlanError("回答义务摘要不能为空")
        requirements.append(
            NormalizedCompositeRequirement(
                id=f"r{index}",
                order=index - 1,
                summary=summary,
                kind=item.kind,
                basis_policy="grove_only" if knowledge_only else item.basis_policy,
            )
        )

    request_ids = [item.id for item in draft.retrieval_requests] + [
        item.id for item in draft.structured_requests
    ]
    if len(set(request_ids)) != len(request_ids):
        raise CompositeAnswerPlanError("输入请求 id 不得重复")

    retrieval_requests: list[NormalizedCompositeRetrievalRequest] = []
    for index, item in enumerate(draft.retrieval_requests, start=1):
        query = _clean_text(item.query)
        if not query:
            raise CompositeAnswerPlanError("Grove 检索问题不能为空")
        retrieval_requests.append(
            NormalizedCompositeRetrievalRequest(
                id=f"q{index}",
                query=query,
                requirement_ids=_mapped_requirement_ids(
                    item.requirement_ids,
                    mapping=mapping,
                ),
            )
        )

    structured_requests: list[NormalizedCompositeStructuredRequest] = []
    for index, item in enumerate(draft.structured_requests, start=1):
        try:
            query_plan = normalize_structured_query_plan(
                StructuredQueryPlanDraft(
                    entry_set=item.entry_set,
                    outputs=item.outputs,
                    reason="",
                ),
                settings=active_settings,
            )
        except StructuredQueryPlanError as exc:
            raise CompositeAnswerPlanError(f"结构化请求非法：{exc}") from exc
        structured_requests.append(
            NormalizedCompositeStructuredRequest(
                id=f"s{index}",
                query_plan=query_plan,
                requirement_ids=_mapped_requirement_ids(
                    item.requirement_ids,
                    mapping=mapping,
                ),
            )
        )

    input_requirement_ids = {
        requirement_id
        for request in [*retrieval_requests, *structured_requests]
        for requirement_id in request.requirement_ids
    }
    for requirement in requirements:
        if (
            requirement.basis_policy in {"grove_only", "grove_required"}
            and requirement.id not in input_requirement_ids
        ):
            raise CompositeAnswerPlanError(
                f"回答义务 {requirement.id} 要求 Grove，但没有关联只读输入"
            )

    allowed = allowed_statement_ids or set()
    statement_message_ids = list(
        dict.fromkeys(item for item in draft.statement_message_ids if item in allowed)
    )
    plan = NormalizedCompositeAnswerPlan(
        requirements=requirements,
        statement_message_ids=statement_message_ids,
        retrieval_requests=retrieval_requests,
        structured_requests=structured_requests,
    )
    if (
        len(plan.model_dump_json(by_alias=True).encode("utf-8"))
        > active_settings.knowledge_agent_composite_answer_plan_bytes_limit
    ):
        raise CompositeAnswerPlanError("规范化复合计划超过 JSON 字节预算")
    return plan


def restore_composite_answer_plan(
    raw: str | None,
    *,
    settings: Settings | None = None,
) -> NormalizedCompositeAnswerPlan | None:
    """恢复已固化计划；旧 Run 为空，非法历史快照不猜测也不执行。"""
    if raw is None:
        return None
    active_settings = settings or get_settings()
    if (
        len(raw.encode("utf-8"))
        > active_settings.knowledge_agent_composite_answer_plan_bytes_limit
    ):
        raise CompositeAnswerPlanError("已固化复合计划超过 JSON 字节预算")
    try:
        return NormalizedCompositeAnswerPlan.model_validate_json(raw)
    except ValidationError as exc:
        raise CompositeAnswerPlanError(f"已固化复合计划非法：{exc}") from exc


def persist_composite_answer_plan(run, plan: NormalizedCompositeAnswerPlan) -> None:
    """首次写入计划并派生旧诊断字段；已有计划只允许原样复用。"""
    if run.composite_answer_plan_json is not None:
        return
    run.composite_answer_plan_json = plan.model_dump_json(by_alias=True)
    run.planned_basis_strategy = _compatibility_basis_strategy(plan)


async def plan_and_persist_composite_answer(
    db,
    run,
    *,
    current_message: str,
    standalone_query: str,
    scope_label: str,
    context_decision: str,
    topic_summary: str | None,
    allowed_statements: list[UserStatementCandidate],
    feature_enabled: bool | None = None,
    cancel_check=None,
) -> NormalizedCompositeAnswerPlan | None:
    """复用首次计划或调用一次 planner；失败只记录，不静默伪造计划。"""
    settings = get_settings()
    enabled = (
        settings.knowledge_agent_composite_answer_enabled
        if feature_enabled is None
        else feature_enabled
    )
    if not enabled:
        return None
    existing = restore_composite_answer_plan(run.composite_answer_plan_json, settings=settings)
    if existing is not None:
        return existing

    knowledge_only = (
        run.request_basis_mode == BASIS_MODE_KNOWLEDGE_ONLY
        or contains_knowledge_only_restriction(current_message, standalone_query)
    )
    candidate, meta = await run_composite_answer_planner(
        db,
        run.workspace_id,
        current_message=current_message,
        standalone_query=standalone_query,
        scope_label=scope_label,
        context_decision=context_decision,
        topic_summary=topic_summary,
        user_statements=[
            {"message_id": item.message_id, "content": item.content}
            for item in allowed_statements
        ],
        knowledge_only=knowledge_only,
    )
    plan = None
    if candidate is not None:
        try:
            plan = normalize_composite_answer_plan(
                candidate,
                allowed_statement_ids={item.message_id for item in allowed_statements},
                knowledge_only=knowledge_only,
                settings=settings,
            )
        except CompositeAnswerPlanError as exc:
            meta = replace(
                meta,
                is_fallback=True,
                error=f"复合回答计划校验失败：{exc}",
            )
    if cancel_check is not None:
        await cancel_check()
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=meta,
        prompt_version=COMPOSITE_ANSWER_PLAN_PROMPT_VERSION,
    )
    if plan is not None:
        persist_composite_answer_plan(run, plan)
    await db.commit()
    return plan


def composite_plan_summary(plan: NormalizedCompositeAnswerPlan) -> dict:
    """返回不含 query、对象句柄和模型 reason 的 API 摘要。"""
    input_kinds: list[str] = []
    if plan.retrieval_requests:
        input_kinds.append("retrieval")
    if plan.structured_requests:
        input_kinds.append("structured")
    return {
        "schema_version": plan.schema_version,
        "requirements": [
            {
                "id": item.id,
                "order": item.order,
                "summary": item.summary,
                "kind": item.kind,
                "basis_policy": item.basis_policy,
            }
            for item in plan.requirements
        ],
        "input_kinds": input_kinds,
    }


def dump_composite_plan(plan: NormalizedCompositeAnswerPlan) -> str:
    """稳定序列化规范化计划，供测试和审计使用。"""
    return json.dumps(plan.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"))


assert PURPOSE_COMPOSITE_ANSWER_PLAN == "composite_answer_plan"
