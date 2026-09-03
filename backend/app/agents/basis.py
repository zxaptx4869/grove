"""知识 Agent 依据规划器：只输出受限策略、工具/外部需求与候选用户消息句柄。

本 Agent 不接触知识内容，也不接收 Workspace、Project、Entry、Evidence 等
授权对象句柄；应用层负责显式限制优先、句柄白名单与安全回退。
"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.core.config import get_settings
from app.models.knowledge_agent import (
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    PURPOSE_BASIS_ROUTE,
)
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

BASIS_ROUTE_PROMPT_VERSION = "v2"


class BasisRouteDraft(BaseModel):
    """依据规划器的结构化输出。

    - strategy 只能取五个内部策略之一；
    - user_message_ids 只能从服务端提供的允许用户消息句柄中选取；
    - 规划器不得放宽显式 knowledge_only 限制，也不得指定任何知识对象或写操作。
    """

    strategy: Literal[
        "knowledge_only",
        "knowledge_first",
        "model_first",
        "hybrid",
        "external_needed",
    ] = BASIS_STRATEGY_KNOWLEDGE_ONLY
    reason: str = ""
    user_message_ids: list[int] = []


BASIS_ROUTE_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的依据规划器，只负责为一条独立问题选择受约束的内部"
    "依据策略，不回答知识内容，也不决定检索/调查的执行细节。"
    "\n"
    "应用会同时提供用户原始消息与消除上下文指代后的独立问题；用户原始消息中的"
    "依据要求和限制必须优先，独立问题只用于理解需要回答的知识目标。"
    "\n"
    "内部策略含义："
    "\n"
    "1. knowledge_only：只允许使用知识库正式知识；当用户明确只允许知识库时由"
    "应用直接固化，正常情况下你不会收到这类请求。"
    "\n"
    "2. knowledge_first：以个人/项目已有知识为主，允许用通用能力补充一般概念解释。"
    "\n"
    "3. model_first：通用概念、解释、头脑风暴等无需个人知识或实时资料的问题，"
    "主要使用模型通用能力，不读取知识库也可以回答。"
    "\n"
    "4. hybrid：回答同时需要用户当前陈述的个人前提与知识库记录，并允许通用能力"
    "衔接，例如“结合我的预算情况和项目里的闭水试验记录”。"
    "\n"
    "5. external_needed：核心内容依赖当前生效的政策、价格、专业规则或其他"
    "实时外部材料，而本阶段没有真实外部工具结果；只能给一般框架并明确边界。"
    "\n"
    "判断规则："
    "\n"
    "1. “我的项目/记录/以前决定/我的预算”等个人知识强信号必须选择需要知识库的"
    "策略（knowledge_first/hybrid），不得选 model_first；"
    "\n"
    "2. 通用概念（“什么是”“解释一下”“怎么理解”）无个人前提时选 model_first；"
    "\n"
    "3. 依赖当前实时材料（“最新价格”“现行政策”“当前规定”）时选 external_needed，"
    "绝不声称已经联网或核验当前材料；"
    "\n"
    "4. user_message_ids 只能从下方“允许的用户信息”列表中选择；不知道、跨话题或"
    "不在列表中的消息绝不返回；"
    "\n"
    "5. 不得自行放宽用户限制、指定 Workspace/项目/Entry/Source 句柄或任何写权限。"
)


def _offline_plan() -> BasisRouteDraft:
    """规划器不可用时的确定性兜底：安全回退 Grove-only。"""
    return BasisRouteDraft(
        strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY,
        reason="依据规划模型不可用",
    )


def _model_name(text_model) -> str:
    """从 Provider 模型对象提取可观测模型名。"""
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


def _format_user_statements(statements: list[dict]) -> str:
    """格式化允许的用户信息列表（句柄为纯数字消息 ID，由应用层白名单提供）。"""
    if not statements:
        return "（无）"
    lines = []
    for item in statements:
        lines.append(f"- 消息 {item['message_id']}：{item['content']}")
    return "\n".join(lines)


async def run_basis_planner(
    db,
    workspace_id: int,
    *,
    objective: str,
    current_message: str,
    scope_label: str,
    topic_summary: str | None,
    context_decision: str,
    user_statements: list[dict],
) -> tuple[BasisRouteDraft | None, StageMeta]:
    """运行依据规划 Agent，返回 (草稿, 阶段元数据)。

    TestModel（未配置密钥）与调用异常都返回确定性 knowledge_only 草稿和
    带 is_fallback 的元数据；应用层据此安全回退，不静默开放模型通用知识。
    """
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_plan(),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = "\n".join(
        [
            f"用户原始消息：{current_message}",
            f"独立问题：{objective}",
            f"可信范围：{scope_label}",
            f"主题摘要：{topic_summary or '（无）'}",
            f"上下文决策：{context_decision}",
            "允许的用户信息：",
            _format_user_statements(user_statements),
            "请输出结构化依据规划结果。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=BasisRouteDraft,
        system_prompt=BASIS_ROUTE_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_basis_route_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("依据规划模型调用失败：%s", exc)
        return (
            _offline_plan(),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_plan(),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
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
            purpose=PURPOSE_BASIS_ROUTE,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
