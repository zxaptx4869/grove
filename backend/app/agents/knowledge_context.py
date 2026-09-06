"""知识 Agent 上下文决策器：判断继续 / 新话题 / 澄清并补全独立查询。"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models.knowledge_agent import PURPOSE_CONTEXT_DECISION
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

CONTEXT_DECISION_PROMPT_VERSION = "v2"


class ContextDecisionDraft(BaseModel):
    """一次上下文决策的结构化输出。"""

    action: Literal["continue", "new_topic", "clarify"] = "continue"
    standalone_query: str = ""
    topic_label: str = ""
    clarify_question: str = ""
    reason: str = ""
    result_position: int | None = Field(default=None, ge=1, le=100)


CONTEXT_DECISION_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的上下文决策器，负责判断用户新消息与当前主题的关系。"
    "\n"
    "输入：当前用户消息、活动主题标签、活动工作集涉及的正式知识标题，"
    "以及对话中最近的有限历史消息。"
    "\n"
    "输出规则："
    "\n"
    "1. 当前消息承接近期任务或回复澄清，且能从历史确定意图时，"
    "action 才选择 continue，并用 standalone_query 补全为脱离聊天记录即可检索的独立问题；"
    "\n"
    "2. 当前消息是完整独立的新问题时选择 new_topic；"
    "\n"
    "3. 只有缺少完成任务的必要信息，且当前范围与历史均无法补全时才选择 clarify，"
    "clarify_question 必须是具体、可回答的问题；"
    "\n"
    "4. standalone_query 不得包含「它」「那个」「这个方案」等指代，"
    "必须表达明确的检索对象与意图；"
    "\n"
    "5. topic_label 用不超过 20 字的短语概括当前主题；"
    "\n"
    "6. 历史助手回答只用于理解用户意图，不是事实来源，不要复述为知识。"
    "\n7. 当前范围已经由界面选定；当前项目、当前范围、全部知识默认指该范围，"
    "不得再追问范围名称。没有事实工作集也能正常统计、讨论和继续话题。"
    "\n8. 结合历史合并本轮任务，保留未改变的项目/筛选条件，用户新条件覆盖旧条件。"
    "已经明确总数、分组维度或补充答案时直接生成独立问题，不问重复确认问题。"
    "\n9. Grove 中项目是正式记录的归属，不是知识类型。泛称知识/记录包含全部类型；"
    "只有明确说知识类型才限定 knowledge。普通完整问题即使没有活动主题也选择 new_topic。"
    "\n10. standalone_query 保留用户的全部任务与依据限制，例如不查知识库、只用通用知识；"
    "继续讨论时也保留尚未撤销的限制。"
    "\n11. 对最近展示列表的序号指代，在 result_position 返回从 1 开始的位置，"
    "standalone_query 用对应标题补全；不存在有效列表时澄清，不编造对象。其他问题返回 null。"
)


def _format_context(
    current_message: str,
    active_topic_label: str | None,
    working_set_titles: list[str],
    history: list[dict],
    scope_label: str | None = None,
    task_context: dict | None = None,
) -> str:
    """组装上下文决策输入：限长历史与主题线索。"""
    parts = [f"当前用户消息：{current_message}"]
    if scope_label:
        parts.append(f"当前可信范围（已经选定，无需用户补充）：{scope_label}")
    if task_context:
        import json

        parts.append(
            "服务端提供的近期任务线索（仅理解意图）："
            + json.dumps(task_context, ensure_ascii=False)
        )
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
    parts.append("请结合已知范围与近期任务直接理解用户意图；只追问真正缺少的必要信息。")
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
    scope_label: str | None = None,
    task_context: dict | None = None,
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
        scope_label,
        task_context,
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
