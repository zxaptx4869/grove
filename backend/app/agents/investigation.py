"""知识 Agent 调查专用 Agent：回答模式路由与逐轮结构化控制器。

两类 Agent 都只输出应用层可校验的结构化结果：
- 路由 Agent 只回答 quick / investigate，不接触知识内容；
- 控制器每轮只提出 search / answer / insufficient 与有限文本查询，
  不接受范围、对象 ID、工具名或预算修改（越权字段由 pydantic 丢弃）。
"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.config import get_settings
from app.models.knowledge_agent import (
    ANSWER_MODE_QUICK,
    INVESTIGATION_ACTION_INSUFFICIENT,
    PURPOSE_ANSWER_MODE_ROUTE,
    PURPOSE_INVESTIGATION_CONTROLLER,
)
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

ANSWER_MODE_ROUTE_PROMPT_VERSION = "v1"
INVESTIGATION_CONTROLLER_PROMPT_VERSION = "v1"


class AnswerModeRouteDraft(BaseModel):
    """一次回答模式路由的结构化输出。"""

    mode: Literal["quick", "investigate"] = "quick"
    reason: str = ""


class InvestigationControllerDraft(BaseModel):
    """一轮调查控制器的结构化输出：只提出下一步建议，不控制工具/范围/预算。"""

    action: Literal["search", "answer", "insufficient"] = "search"
    queries: list[str] = []
    coverage: list[str] = []
    gaps: list[str] = []
    conflicts: list[str] = []
    reason: str = ""


ANSWER_MODE_ROUTE_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的回答模式路由器，只负责判断一条独立问题是否需要"
    "多轮补查，不回答知识内容。"
    "\n"
    "输入：独立问题与受限主题摘要。"
    "\n"
    "输出规则："
    "\n"
    "1. 问题明确要求查找、对比或核对多个方面、需要核对冲突或首轮检索很可能"
    "不足时选择 investigate；"
    "\n"
    "2. 普通事实性问题、简单查询或只需要一次检索即可回答的问题选择 quick；"
    "\n"
    "3. 只允许输出 quick 或 investigate，不要输出其他模式；"
    "\n"
    "4. reason 用不超过 100 字说明判断依据。"
)


INVESTIGATION_CONTROLLER_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的调查控制器，负责根据当前调查账本决定下一步动作。"
    "\n"
    "输入：独立问题、可信范围、工作集短摘要、已执行查询、紧凑证据账本"
    "（已发现 Entry、当前 Run Evidence、覆盖/缺口/冲突）与剩余预算。"
    "\n"
    "输出规则："
    "\n"
    "1. 证据已覆盖问题且能给出带引用结论时选择 answer；"
    "\n"
    "2. 正式知识不足或剩余预算无法继续时选择 insufficient；"
    "\n"
    "3. 存在明确缺口且剩余预算充足时选择 search，并给出不超过 3 条新的文本"
    "查询；查询必须独立完整、可脱离聊天记录执行，不得与已执行查询重复；"
    "\n"
    "4. 不允许输出 Workspace/项目/目录范围、对象 ID、工具名或预算数字，"
    "这些由应用层控制；"
    "\n"
    "5. coverage 列出已覆盖的方面、gaps 列出未覆盖方面、conflicts 只列出"
    "已被当前 Run Evidence 支持的冲突线索；均使用简短短语；"
    "\n"
    "6. 历史助手回答与历史 Evidence 不是事实来源，不得当作当前 Run 证据。"
)


def _offline_route() -> AnswerModeRouteDraft:
    """路由不可用时的确定性兜底：固定选择 quick，由应用层记录 fallback。"""
    return AnswerModeRouteDraft(mode=ANSWER_MODE_QUICK, reason="回答模式路由模型不可用")


def _offline_controller() -> InvestigationControllerDraft:
    """控制器不可用时的确定性兜底：停止并保留已有证据，不编造新查询。"""
    return InvestigationControllerDraft(
        action=INVESTIGATION_ACTION_INSUFFICIENT,
        reason="调查控制器模型不可用，基于已有证据停止",
    )


def _model_name(text_model) -> str:
    """从 Provider 模型对象提取可观测的模型名。"""
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


async def run_answer_mode_router(
    db,
    workspace_id: int,
    *,
    objective: str,
    topic_summary: str | None,
) -> tuple[AnswerModeRouteDraft, StageMeta]:
    """运行回答模式路由 Agent，返回 (草稿, 阶段元数据)。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_route(),
            StageMeta(
                purpose=PURPOSE_ANSWER_MODE_ROUTE,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = "\n".join(
        [
            f"独立问题：{objective}",
            f"主题摘要：{topic_summary or '（无）'}",
            "请输出结构化路由结果。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=AnswerModeRouteDraft,
        system_prompt=ANSWER_MODE_ROUTE_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_answer_mode_router_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("回答模式路由模型调用失败：%s", exc)
        return (
            _offline_route(),
            StageMeta(
                purpose=PURPOSE_ANSWER_MODE_ROUTE,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_route(),
            StageMeta(
                purpose=PURPOSE_ANSWER_MODE_ROUTE,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_ANSWER_MODE_ROUTE,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )


def _format_controller_context(
    *,
    objective: str,
    scope_label: str,
    working_set_summary: str,
    executed_queries: list[str],
    ledger_summary: str,
    remaining_budget: dict,
) -> str:
    """组装控制器输入：只传独立问题、范围标签、短摘要与剩余预算。"""
    parts = [
        f"独立问题：{objective}",
        f"可信范围：{scope_label}",
        f"工作集摘要：{working_set_summary or '（无）'}",
    ]
    if executed_queries:
        parts.append("已执行查询：" + "；".join(executed_queries[:10]))
    else:
        parts.append("已执行查询：（无）")
    parts.append(f"证据账本摘要：{ledger_summary or '（无）'}")
    parts.append(
        "剩余预算："
        + "，".join(f"{key}={value}" for key, value in remaining_budget.items())
    )
    parts.append("请输出结构化下一步建议。")
    return "\n".join(parts)


async def run_investigation_controller(
    db,
    workspace_id: int,
    *,
    objective: str,
    scope_label: str,
    working_set_summary: str,
    executed_queries: list[str],
    ledger_summary: str,
    remaining_budget: dict,
) -> tuple[InvestigationControllerDraft, StageMeta]:
    """运行一轮调查控制器，返回 (草稿, 阶段元数据)。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_controller(),
            StageMeta(
                purpose=PURPOSE_INVESTIGATION_CONTROLLER,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_controller_context(
        objective=objective,
        scope_label=scope_label,
        working_set_summary=working_set_summary,
        executed_queries=executed_queries,
        ledger_summary=ledger_summary,
        remaining_budget=remaining_budget,
    )
    agent = Agent(
        text_model,
        output_type=InvestigationControllerDraft,
        system_prompt=INVESTIGATION_CONTROLLER_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_investigation_controller_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("调查控制器模型调用失败：%s", exc)
        return (
            _offline_controller(),
            StageMeta(
                purpose=PURPOSE_INVESTIGATION_CONTROLLER,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_controller(),
            StageMeta(
                purpose=PURPOSE_INVESTIGATION_CONTROLLER,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_INVESTIGATION_CONTROLLER,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
