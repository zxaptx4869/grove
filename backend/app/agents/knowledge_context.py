"""知识 Agent 上下文决策器：判断继续 / 新话题 / 澄清并补全独立查询。"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models.knowledge_agent import PURPOSE_CONTEXT_DECISION
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

CONTEXT_DECISION_PROMPT_VERSION = "v1"


class ContextDecisionDraft(BaseModel):
    """一次上下文决策的结构化输出。"""

    action: Literal["continue", "new_topic", "clarify"] = "continue"
    standalone_query: str = ""
    topic_label: str = ""
    clarify_question: str = ""
    reason: str = ""


CONTEXT_DECISION_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的上下文决策器，负责判断用户新消息与当前主题的关系。"
    "\n"
    "输入：当前用户消息、活动主题标签、活动工作集涉及的正式知识标题，"
    "以及对话中最近的有限历史消息。"
    "\n"
    "输出规则："
    "\n"
    "1. 只有当前消息与活动主题明显相关，且能从有限历史确定指代对象时，"
    "action 才选择 continue，并用 standalone_query 补全为脱离聊天记录即可检索的独立问题；"
    "\n"
    "2. 当前消息是完整独立的新问题时选择 new_topic；"
    "\n"
    "3. 无法从有限上下文安全确定指代对象时选择 clarify，"
    "clarify_question 必须是具体、可回答的问题；"
    "\n"
    "4. standalone_query 不得包含「它」「那个」「这个方案」等指代，"
    "必须表达明确的检索对象与意图；"
    "\n"
    "5. topic_label 用不超过 20 字的短语概括当前主题；"
    "\n"
    "6. 历史助手回答只用于理解用户意图，不是事实来源，不要复述为知识。"
)


def _format_context(
    current_message: str,
    active_topic_label: str | None,
    working_set_titles: list[str],
    history: list[dict],
) -> str:
    """组装上下文决策输入：限长历史与主题线索。"""
    parts = [f"当前用户消息：{current_message}"]
    if active_topic_label:
        parts.append(f"活动主题标签：{active_topic_label}")
    if working_set_titles:
        parts.append(
            "活动工作集涉及的知识标题："
            + "；".join(working_set_titles[:10])
        )
    parts.append("近期对话消息（只用于理解意图）：")
    for item in history:
        parts.append(f"{item['role']}：{item['content']}")
    parts.append(
        "请输出结构化决策；拿不准时选择 clarify，不要猜测用户指代。"
    )
    return "\n".join(parts)


def _offline_draft() -> ContextDecisionDraft:
    """离线兜底：不携带旧上下文（由应用层按 new_topic 处理）。"""
    return ContextDecisionDraft(action="new_topic", reason="上下文决策模型不可用")


async def run_context_decision_agent(
    db,
    workspace_id: int,
    *,
    current_message: str,
    active_topic_label: str | None,
    working_set_titles: list[str],
    history: list[dict],
) -> tuple[ContextDecisionDraft, StageMeta]:
    """运行上下文决策 Agent，返回 (草稿, 阶段元数据)。"""
    started = perf_counter()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_draft(),
            StageMeta(
                purpose=PURPOSE_CONTEXT_DECISION,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_context(
        current_message,
        active_topic_label,
        working_set_titles,
        history,
    )
    agent = Agent(
        text_model,
        output_type=ContextDecisionDraft,
        system_prompt=CONTEXT_DECISION_SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("上下文决策模型调用失败：%s", exc)
        return (
            _offline_draft(),
            StageMeta(
                purpose=PURPOSE_CONTEXT_DECISION,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_draft(),
            StageMeta(
                purpose=PURPOSE_CONTEXT_DECISION,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_CONTEXT_DECISION,
            provider="llm",
            model=str(model_name),
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
