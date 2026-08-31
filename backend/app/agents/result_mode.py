"""知识 Agent 结果形态路由器：只判断「综合回答」或「结构化 Entry 查找」。

本 Agent 不接触知识内容，只接收服务端形成的独立问题、可信范围标签与受限
主题摘要；不接收 Workspace、Project、Node、Entry 等授权参数或对象 ID，
应用层负责范围、权限与后续执行图选择。
"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.config import get_settings
from app.models.knowledge_agent import (
    PURPOSE_RESULT_MODE_ROUTE,
    RESULT_MODE_ANSWER,
)
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

RESULT_MODE_ROUTE_PROMPT_VERSION = "v1"


class ResultModeRouteDraft(BaseModel):
    """一次结果形态路由的结构化输出：只允许 answer / entries。"""

    mode: Literal["answer", "entries"] = "answer"
    reason: str = ""


RESULT_MODE_ROUTE_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的结果形态路由器，只负责判断一条独立问题需要"
    "「综合回答」还是「列出正式知识 Entry」，不回答知识内容。"
    "\n"
    "输入：独立问题、可信范围标签与受限主题摘要。"
    "\n"
    "输出规则："
    "\n"
    "1. 用户明确要求找、列出、查询、有哪些相关的知识条目/知识/记录，"
    "或希望把匹配对象作为可逐条扫描的列表返回时，选择 entries；"
    "\n"
    "2. 用户要求解释、总结、比较结论、分析原因、给出建议或直接回答问题时，"
    "选择 answer；"
    "\n"
    "3. 拿不准、查询既有理解又有找对象成分时选择 answer，"
    "避免把「找到以后理解它」误判成纯对象列表；"
    "\n"
    "4. 只允许输出 answer 或 entries，不要输出其他模式；"
    "\n"
    "5. reason 用不超过 100 字说明判断依据。"
)


def _offline_route() -> ResultModeRouteDraft:
    """路由不可用时的确定性兜底：固定选择 answer，由应用层记录 fallback。"""
    return ResultModeRouteDraft(
        mode=RESULT_MODE_ANSWER,
        reason="结果形态路由模型不可用",
    )


def _model_name(text_model) -> str:
    """从 Provider 模型对象提取可观测的模型名。"""
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


async def run_result_mode_router(
    db,
    workspace_id: int,
    *,
    objective: str,
    scope_label: str,
    topic_summary: str | None,
) -> tuple[ResultModeRouteDraft, StageMeta]:
    """运行结果形态路由 Agent，返回 (草稿, 阶段元数据)。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_route(),
            StageMeta(
                purpose=PURPOSE_RESULT_MODE_ROUTE,
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
            f"可信范围：{scope_label}",
            f"主题摘要：{topic_summary or '（无）'}",
            "请输出结构化路由结果。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=ResultModeRouteDraft,
        system_prompt=RESULT_MODE_ROUTE_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_result_mode_router_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("结果形态路由模型调用失败：%s", exc)
        return (
            _offline_route(),
            StageMeta(
                purpose=PURPOSE_RESULT_MODE_ROUTE,
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
                purpose=PURPOSE_RESULT_MODE_ROUTE,
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
            purpose=PURPOSE_RESULT_MODE_ROUTE,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
