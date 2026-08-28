"""知识 Agent 连续追问决策服务：有限历史、归一化与安全降级。"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge_context import (
    run_context_decision_agent,
)
from app.models import KnowledgeMessage
from app.models.knowledge_agent import (
    CONTEXT_DECISION_CLARIFY,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_DECISION_NEW_TOPIC,
    CONTEXT_MODE_CONTINUE,
    CONTEXT_MODE_NEW_TOPIC,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    PURPOSE_CONTEXT_DECISION,
)
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

DEFAULT_CLARIFY_QUESTION = (
    "这个问题缺少上下文，请补充你指的是哪个主题或对象"
    "（例如具体的项目、目录或上一轮提到的内容）。"
)
NO_ACTIVE_TOPIC_CLARIFY = (
    "当前没有进行中的主题。请直接提出完整问题，"
    "或先说明你想围绕哪个主题继续提问。"
)


@dataclass
class ContextDecisionResult:
    """应用层归一化后的上下文决策。"""

    decision: str
    standalone_query: str
    topic_label: str | None
    clarify_question: str | None
    degraded: bool
    history_message_ids: list[int]
    meta: StageMeta


def _server_meta(duration_ms: int = 0) -> StageMeta:
    """确定性应用层阶段的元数据（无模型调用）。"""
    return StageMeta(
        purpose=PURPOSE_CONTEXT_DECISION,
        provider="server",
        model=None,
        is_fallback=False,
        error=None,
        duration_ms=duration_ms,
    )


def _derive_topic_label(message: str) -> str:
    """从消息确定性生成主题标签（最多 30 字）。"""
    text = " ".join(message.split())
    return text[:30] + ("…" if len(text) > 30 else "")


async def select_decision_history(
    db: AsyncSession,
    conversation_id: int,
    *,
    exclude_message_id: int | None,
    limit: int,
    message_chars: int,
) -> tuple[list[dict], list[int]]:
    """选择最近有限条用户/助手消息并截断，返回 (消息, 实际消息 ID)。"""
    rows = (
        await db.execute(
            select(KnowledgeMessage)
            .where(
                KnowledgeMessage.conversation_id == conversation_id,
                KnowledgeMessage.role.in_([MESSAGE_ROLE_USER, MESSAGE_ROLE_ASSISTANT]),
            )
            .order_by(
                KnowledgeMessage.created_at.desc(),
                KnowledgeMessage.id.desc(),
            )
            .limit(limit + 1)
        )
    ).scalars().all()
    selected: list[dict] = []
    message_ids: list[int] = []
    for row in rows:
        if exclude_message_id is not None and row.id == exclude_message_id:
            continue
        content = row.content[:message_chars]
        selected.append({"role": row.role, "content": content})
        message_ids.append(row.id)
        if len(selected) >= limit:
            break
    # 恢复时间正序，供决策模型阅读
    selected.reverse()
    message_ids.reverse()
    return selected, message_ids


async def decide_context(
    db: AsyncSession,
    *,
    workspace_id: int,
    conversation_id: int,
    current_message: str,
    request_mode: str,
    active_topic_label: str | None,
    working_set_titles: list[str],
    history_limit: int,
    history_message_chars: int,
    user_message_id: int | None = None,
) -> ContextDecisionResult:
    """执行上下文决策：显式覆盖优先，auto 走决策模型，均做归一化与安全降级。"""
    history, history_ids = await select_decision_history(
        db,
        conversation_id,
        exclude_message_id=user_message_id,
        limit=history_limit,
        message_chars=history_message_chars,
    )

    # ---- 显式 new_topic：绕过分类，直接用当前消息开始独立检索 ----
    if request_mode == CONTEXT_MODE_NEW_TOPIC:
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_NEW_TOPIC,
            standalone_query=current_message,
            topic_label=_derive_topic_label(current_message),
            clarify_question=None,
            degraded=False,
            history_message_ids=history_ids,
            meta=_server_meta(),
        )

    # ---- 显式 continue：固定语义，只改写查询 ----
    if request_mode == CONTEXT_MODE_CONTINUE:
        if not active_topic_label:
            return ContextDecisionResult(
                decision=CONTEXT_DECISION_CLARIFY,
                standalone_query=current_message,
                topic_label=None,
                clarify_question=NO_ACTIVE_TOPIC_CLARIFY,
                degraded=False,
                history_message_ids=history_ids,
                meta=_server_meta(),
            )
        draft, meta = await run_context_decision_agent(
            db,
            workspace_id,
            current_message=current_message,
            active_topic_label=active_topic_label,
            working_set_titles=working_set_titles,
            history=history,
        )
        if meta.is_fallback or draft is None:
            # 安全降级：主题标签 + 原问题形成确定性独立查询
            return ContextDecisionResult(
                decision=CONTEXT_DECISION_CONTINUE,
                standalone_query=f"{active_topic_label}：{current_message}",
                topic_label=active_topic_label,
                clarify_question=None,
                degraded=True,
                history_message_ids=history_ids,
                meta=meta,
            )
        standalone = draft.standalone_query.strip()
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_CONTINUE,
            standalone_query=standalone or f"{active_topic_label}：{current_message}",
            topic_label=active_topic_label,
            clarify_question=None,
            degraded=False,
            history_message_ids=history_ids,
            meta=meta,
        )

    # ---- auto：模型判断 + 应用层归一化 ----
    draft, meta = await run_context_decision_agent(
        db,
        workspace_id,
        current_message=current_message,
        active_topic_label=active_topic_label,
        working_set_titles=working_set_titles,
        history=history,
    )
    if meta.is_fallback or draft is None:
        # 分类失败显式降级为 new_topic，不偷偷沿用旧工作集
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_NEW_TOPIC,
            standalone_query=current_message,
            topic_label=_derive_topic_label(current_message),
            clarify_question=None,
            degraded=True,
            history_message_ids=history_ids,
            meta=meta,
        )

    action = draft.action
    if action == CONTEXT_DECISION_CLARIFY:
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_CLARIFY,
            standalone_query=current_message,
            topic_label=active_topic_label,
            clarify_question=draft.clarify_question.strip() or DEFAULT_CLARIFY_QUESTION,
            degraded=False,
            history_message_ids=history_ids,
            meta=meta,
        )
    if action == CONTEXT_DECISION_NEW_TOPIC:
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_NEW_TOPIC,
            standalone_query=draft.standalone_query.strip() or current_message,
            topic_label=draft.topic_label.strip() or _derive_topic_label(current_message),
            clarify_question=None,
            degraded=False,
            history_message_ids=history_ids,
            meta=meta,
        )
    # continue 但对话没有活动工作集：不猜测历史主题，改为澄清
    if not active_topic_label:
        return ContextDecisionResult(
            decision=CONTEXT_DECISION_CLARIFY,
            standalone_query=current_message,
            topic_label=None,
            clarify_question=NO_ACTIVE_TOPIC_CLARIFY,
            degraded=False,
            history_message_ids=history_ids,
            meta=meta,
        )
    return ContextDecisionResult(
        decision=CONTEXT_DECISION_CONTINUE,
        standalone_query=draft.standalone_query.strip() or current_message,
        topic_label=active_topic_label,
        clarify_question=None,
        degraded=False,
        history_message_ids=history_ids,
        meta=meta,
    )
