"""知识 Agent 结果形态应用层服务：请求/实际形态解析与安全回退。"""

import logging
from dataclasses import dataclass

from app.agents.result_mode import (
    RESULT_MODE_ROUTE_PROMPT_VERSION,
    run_result_mode_router,
)
from app.core.config import get_settings
from app.models.knowledge_agent import (
    PURPOSE_RESULT_MODE_ROUTE,
    RESULT_MODE_ANSWER,
    RESULT_MODE_AUTO,
    RESULT_MODE_ENTRIES,
)
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)


def _server_route_meta(error: str) -> StageMeta:
    """应用层确定性路由阶段元数据（无模型调用）。"""
    return StageMeta(
        purpose=PURPOSE_RESULT_MODE_ROUTE,
        provider="server",
        model=None,
        is_fallback=True,
        error=error,
        duration_ms=0,
    )


@dataclass
class ResultModeResolution:
    """路由结果：实际结果形态、阶段元数据与降级原因。"""

    mode: str
    meta: StageMeta | None = None
    fallback_reason: str | None = None


async def resolve_result_mode(
    db,
    *,
    workspace_id: int,
    request_mode: str,
    objective: str,
    scope_label: str,
    topic_summary: str | None,
) -> ResultModeResolution:
    """按请求形态解析实际结果形态。

    - answer / entries 为显式覆盖，不调用路由模型；
    - auto 走独立结构化路由；路由未配置、失败、非法结构或配置禁用时
      固定回退 answer，并把 provider/model/fallback/error 记录到阶段元数据。
    """
    if request_mode == RESULT_MODE_ANSWER:
        return ResultModeResolution(mode=RESULT_MODE_ANSWER)
    if request_mode == RESULT_MODE_ENTRIES:
        return ResultModeResolution(mode=RESULT_MODE_ENTRIES)
    if request_mode != RESULT_MODE_AUTO:
        # 未知请求形态由 schema 层拦截；此处防御性回退 answer
        return ResultModeResolution(
            mode=RESULT_MODE_ANSWER,
            meta=_server_route_meta(f"非法请求形态：{request_mode}"),
            fallback_reason="invalid_request_mode",
        )

    settings = get_settings()
    if not settings.knowledge_agent_result_mode_router_enabled:
        return ResultModeResolution(
            mode=RESULT_MODE_ANSWER,
            meta=_server_route_meta("结果形态路由已禁用"),
            fallback_reason="router_disabled",
        )
    try:
        draft, meta = await run_result_mode_router(
            db,
            workspace_id,
            objective=objective,
            scope_label=scope_label,
            topic_summary=topic_summary,
        )
    except Exception as exc:  # noqa: BLE001
        return ResultModeResolution(
            mode=RESULT_MODE_ANSWER,
            meta=_server_route_meta(f"路由调用异常：{exc}"),
            fallback_reason="router_error",
        )
    if (
        draft is None
        or meta.is_fallback
        or draft.mode not in {RESULT_MODE_ANSWER, RESULT_MODE_ENTRIES}
    ):
        return ResultModeResolution(
            mode=RESULT_MODE_ANSWER,
            meta=meta,
            fallback_reason=meta.error or "路由结果非法",
        )
    return ResultModeResolution(mode=draft.mode, meta=meta)


def result_mode_route_prompt_version() -> str:
    """返回结果形态路由 prompt 版本（可观测记录复用）。"""
    return RESULT_MODE_ROUTE_PROMPT_VERSION
