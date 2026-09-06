"""同范围的有界对话意图线索；与事实工作集、引用权限独立。"""

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAgentRun, KnowledgeConversation, KnowledgeMessage


@dataclass
class DialogueContext:
    history: list[dict] = field(default_factory=list)
    message_ids: list[int] = field(default_factory=list)
    topic_label: str | None = None
    task: dict = field(default_factory=dict)
    result_items: list[dict] = field(default_factory=list)


def _object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


async def load_dialogue_context(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    *,
    limit: int,
    message_chars: int,
) -> DialogueContext:
    """只从当前消息之前的同范围终态读取，显式与自动新话题均切断更旧历史。"""
    context = DialogueContext()
    conversation = await db.get(KnowledgeConversation, run.conversation_id)
    if (
        conversation is None
        or conversation.workspace_id != run.workspace_id
        or conversation.owner_user_id != run.owner_user_id
        or not run.user_message_id
        or run.request_context_mode == "new_topic"
    ):
        return context
    scope_boundary = (
        await db.execute(
            select(func.max(KnowledgeMessage.id)).where(
                KnowledgeMessage.conversation_id == run.conversation_id,
                KnowledgeMessage.message_type == "scope_change",
                KnowledgeMessage.id < run.user_message_id,
            )
        )
    ).scalar() or 0
    predicates = (
        KnowledgeAgentRun.conversation_id == run.conversation_id,
        KnowledgeAgentRun.workspace_id == run.workspace_id,
        KnowledgeAgentRun.owner_user_id == run.owner_user_id,
        KnowledgeAgentRun.scope_type == run.scope_type,
        KnowledgeAgentRun.project_id == run.project_id,
        KnowledgeAgentRun.user_message_id < run.user_message_id,
        KnowledgeAgentRun.user_message_id > scope_boundary,
        KnowledgeAgentRun.run_kind == "answer",
    )
    recent = (
        (
            await db.execute(
                select(KnowledgeAgentRun)
                .where(*predicates)
                .order_by(
                    KnowledgeAgentRun.user_message_id.desc(),
                )
                .limit(max(1, limit))
            )
        )
        .scalars()
        .all()
    )
    selected = []
    for previous in recent:
        if previous.status in {"completed", "partial"}:
            selected.append(previous)
        if previous.context_decision == "new_topic" or previous.request_context_mode == "new_topic":
            break
    if not selected:
        return context
    messages = (
        (
            await db.execute(
                select(KnowledgeMessage)
                .where(
                    KnowledgeMessage.conversation_id == run.conversation_id,
                    KnowledgeMessage.run_id.in_([item.id for item in selected]),
                    KnowledgeMessage.id < run.user_message_id,
                    KnowledgeMessage.role.in_(["user", "assistant"]),
                    KnowledgeMessage.scope_type == run.scope_type,
                    KnowledgeMessage.project_id == run.project_id,
                )
                .order_by(KnowledgeMessage.id.desc())
                .limit(limit + 4)
            )
        )
        .scalars()
        .all()
    )
    for message in reversed([item for item in messages if item.content.strip()][:limit]):
        context.history.append({"role": message.role, "content": message.content[:message_chars]})
        context.message_ids.append(message.id)
    latest = selected[0]
    context.topic_label = next((item.topic_label for item in selected if item.topic_label), None)
    context.task = {
        "previous_query": (latest.standalone_query or "")[:1000],
        "previous_decision": latest.context_decision,
        "pending_question": _object(latest.context_meta_json).get("clarify_question"),
    }
    # 最近一个有列表的任务仅作为对象定位线索，不把历史内容变成事实。
    for previous in selected:
        snapshot = _object(previous.entry_result_json)
        if snapshot:
            context.task.setdefault("entry_set", snapshot.get("set_summary"))
            if not snapshot.get("items") and snapshot.get("sort") is None:
                continue
            context.task["sort"] = snapshot.get("sort")
            items = snapshot.get("items", [])[:50]
            context.result_items = [item if isinstance(item, dict) else {} for item in items]
            context.task["result_list"] = [
                {"position": index, "title": str(item.get("title") or "")[:255]}
                for index, item in enumerate(context.result_items, 1)
            ]
            break
    return context
