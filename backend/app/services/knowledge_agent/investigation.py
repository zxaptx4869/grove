"""知识 Agent 调查应用层服务：回答模式解析与控制器输出校验。

模型只提供结构化建议；范围、工具链、预算与停止条件全部由本层控制。
"""

import logging
from dataclasses import dataclass, field

from app.agents.investigation import (
    InvestigationControllerDraft,
    run_answer_mode_router,
)
from app.core.config import get_settings
from app.models.knowledge_agent import (
    ANSWER_MODE_INVESTIGATE,
    ANSWER_MODE_QUICK,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_ACTIONS,
    PURPOSE_ANSWER_MODE_ROUTE,
)
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)


def _server_route_meta(error: str) -> StageMeta:
    """应用层确定性路由阶段元数据（无模型调用）。"""
    return StageMeta(
        purpose=PURPOSE_ANSWER_MODE_ROUTE,
        provider="server",
        model=None,
        is_fallback=True,
        error=error,
        duration_ms=0,
    )


@dataclass
class AnswerModeResolution:
    """路由结果：实际回答模式、阶段元数据与降级原因。"""

    mode: str
    meta: StageMeta | None = None
    fallback_reason: str | None = None


async def resolve_answer_mode(
    db,
    *,
    workspace_id: int,
    request_mode: str,
    objective: str,
    topic_summary: str | None,
) -> AnswerModeResolution:
    """按请求模式解析实际回答模式。

    - quick / investigate 为显式覆盖，不调用路由模型；
    - auto 走独立结构化路由；路由未配置、失败、非法结构或配置禁用时
      固定选择 quick，并把 provider/model/fallback/error 记录到阶段元数据。
    """
    if request_mode == ANSWER_MODE_QUICK:
        return AnswerModeResolution(mode=ANSWER_MODE_QUICK)
    if request_mode == ANSWER_MODE_INVESTIGATE:
        return AnswerModeResolution(mode=ANSWER_MODE_INVESTIGATE)

    settings = get_settings()
    if not settings.knowledge_agent_answer_mode_router_enabled:
        return AnswerModeResolution(
            mode=ANSWER_MODE_QUICK,
            meta=_server_route_meta("回答模式路由已禁用"),
            fallback_reason="router_disabled",
        )
    try:
        draft, meta = await run_answer_mode_router(
            db,
            workspace_id,
            objective=objective,
            topic_summary=topic_summary,
        )
    except Exception as exc:  # noqa: BLE001
        return AnswerModeResolution(
            mode=ANSWER_MODE_QUICK,
            meta=_server_route_meta(f"路由调用异常：{exc}"),
            fallback_reason="router_error",
        )
    if draft is None or meta.is_fallback or draft.mode not in {
        ANSWER_MODE_QUICK,
        ANSWER_MODE_INVESTIGATE,
    }:
        return AnswerModeResolution(
            mode=ANSWER_MODE_QUICK,
            meta=meta,
            fallback_reason=meta.error or "路由结果非法",
        )
    return AnswerModeResolution(mode=draft.mode, meta=meta)


@dataclass
class ControllerPlan:
    """应用层校验后的控制器计划：只含合法动作与受控文本查询。"""

    action: str = INVESTIGATION_ACTION_INSUFFICIENT
    queries: list[str] = field(default_factory=list)
    coverage: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    reason: str = ""
    invalid: bool = False
    rejection_note: str | None = None


def _truncate_items(
    values: list[str] | None,
    *,
    max_items: int,
    max_chars: int,
) -> list[str]:
    """清空空白并按长度确定性截断摘要条目。"""
    result: list[str] = []
    for value in values or []:
        text = " ".join(str(value).split())
        if not text:
            continue
        result.append(text[:max_chars])
        if len(result) >= max_items:
            break
    return result


def validate_controller_output(
    draft: InvestigationControllerDraft | None,
    *,
    max_queries: int,
    query_chars: int,
    summary_items: int,
    summary_item_chars: int,
    reason_chars: int,
) -> ControllerPlan:
    """校验控制器输出：忽略越权字段、去空白、限查询数与长度、确定性截断摘要。"""
    if draft is None or draft.action not in INVESTIGATION_ACTIONS:
        return ControllerPlan(
            invalid=True,
            rejection_note="控制器输出非法：动作不在允许范围",
        )
    queries: list[str] = []
    for raw in draft.queries or []:
        text = " ".join(str(raw).split())
        if not text or text in queries:
            continue
        queries.append(text[:query_chars])
        if len(queries) >= max_queries:
            break
    return ControllerPlan(
        action=draft.action,
        queries=queries,
        coverage=_truncate_items(
            draft.coverage,
            max_items=summary_items,
            max_chars=summary_item_chars,
        ),
        gaps=_truncate_items(
            draft.gaps,
            max_items=summary_items,
            max_chars=summary_item_chars,
        ),
        conflicts=_truncate_items(
            draft.conflicts,
            max_items=summary_items,
            max_chars=summary_item_chars,
        ),
        reason=(" ".join((draft.reason or "").split()))[:reason_chars],
    )


def controller_plan_defaults() -> dict:
    """返回控制器校验使用的服务端默认参数（便于测试与应用层复用）。"""
    settings = get_settings()
    return {
        "max_queries": settings.knowledge_agent_investigation_max_queries_per_round,
        "query_chars": settings.knowledge_agent_investigation_query_chars,
        "summary_items": settings.knowledge_agent_investigation_summary_items,
        "summary_item_chars": settings.knowledge_agent_investigation_summary_item_chars,
        "reason_chars": settings.knowledge_agent_investigation_reason_chars,
    }


def action_requests_search(action: str) -> bool:
    """控制器动作是否为补查。"""
    return action == INVESTIGATION_ACTION_SEARCH


def action_requests_answer(action: str) -> bool:
    """控制器动作是否为回答/不足（两者都进入最终综合或不足说明）。"""
    return action in {INVESTIGATION_ACTION_ANSWER, INVESTIGATION_ACTION_INSUFFICIENT}
