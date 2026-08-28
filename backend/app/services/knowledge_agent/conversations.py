"""知识对话与消息服务：所有权、范围、游标分页与范围变更。"""

import base64
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeMessage,
    Project,
)
from app.models.knowledge_agent import (
    MESSAGE_ROLE_SYSTEM,
    MESSAGE_TYPE_SCOPE_CHANGE,
    RUN_ACTIVE_STATUSES,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
    KnowledgeAgentRun,
)
from app.schemas.knowledge_agent import (
    KnowledgeConversationCreate,
    KnowledgeConversationOut,
    KnowledgeMessageOut,
    KnowledgeScopeChangeRequest,
)
from app.services.knowledge_agent.working_set import active_context_summaries

logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_TITLE = "新对话"
_SCOPE_LABELS = {SCOPE_WORKSPACE: "全部知识"}


async def get_owned_conversation(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    conversation_id: int,
) -> KnowledgeConversation:
    """按用户与 Workspace 读取对话；不存在或越权一律 404。"""
    conversation = await db.get(KnowledgeConversation, conversation_id)
    if (
        conversation is None
        or conversation.workspace_id != workspace_id
        or conversation.owner_user_id != user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在")
    return conversation


def _project_label(project_name: str | None) -> str:
    return f"项目：{project_name or '未知项目'}"


def scope_label(scope_type: str, project_name: str | None = None) -> str:
    """把范围类型转换为用户可读标签。"""
    if scope_type == SCOPE_PROJECT:
        return _project_label(project_name)
    return _SCOPE_LABELS.get(scope_type, "全部知识")


async def _validate_project(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None,
) -> Project | None:
    """校验项目属于当前 Workspace；不存在或越权返回 404。"""
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


async def list_conversations(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
) -> list[KnowledgeConversationOut]:
    """按当前 Workspace 与用户列出对话，按最近活动时间排序。"""
    rows = (
        await db.execute(
            select(KnowledgeConversation)
            .where(
                KnowledgeConversation.workspace_id == workspace_id,
                KnowledgeConversation.owner_user_id == user_id,
            )
            .order_by(
                KnowledgeConversation.last_activity_at.desc(),
                KnowledgeConversation.id.desc(),
            )
        )
    ).scalars().all()
    project_names = await _project_name_map(db, workspace_id, [row.project_id for row in rows])
    summaries = await active_context_summaries(db, [row.id for row in rows])
    return [
        conversation_out(
            conversation,
            project_names.get(conversation.project_id),
            *summaries.get(conversation.id, (None, None, 0)),
        )
        for conversation in rows
    ]


async def _project_name_map(
    db: AsyncSession,
    workspace_id: int,
    project_ids: list[int | None],
) -> dict[int, str]:
    """批量读取项目名，避免列表接口 N+1。"""
    ids = {project_id for project_id in project_ids if project_id is not None}
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Project.id, Project.name).where(
                Project.id.in_(ids),
                Project.workspace_id == workspace_id,
            )
        )
    ).all()
    return {project_id: name for project_id, name in rows}


def conversation_out(
    conversation: KnowledgeConversation,
    project_name: str | None = None,
    active_topic_label: str | None = None,
    active_version_id: int | None = None,
    active_entry_count: int = 0,
) -> KnowledgeConversationOut:
    """组装对话响应。"""
    return KnowledgeConversationOut(
        id=conversation.id,
        title=conversation.title,
        scope_type=conversation.scope_type,
        project_id=conversation.project_id,
        project_name=project_name,
        active_topic_label=active_topic_label,
        active_context_version_id=active_version_id,
        active_entry_count=active_entry_count,
        last_activity_at=conversation.last_activity_at,
        created_at=conversation.created_at,
    )


async def create_conversation(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    payload: KnowledgeConversationCreate,
) -> KnowledgeConversation:
    """创建对话：只允许 Workspace「全部知识」或当前 Workspace 内项目范围。"""
    project = await _validate_project(db, workspace_id, payload.project_id)
    if payload.scope_type == SCOPE_PROJECT and project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目范围必须指定当前 Workspace 内的项目",
        )
    if payload.scope_type == SCOPE_WORKSPACE:
        project_id: int | None = None
    else:
        project_id = payload.project_id
    conversation = KnowledgeConversation(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        scope_type=payload.scope_type,
        project_id=project_id,
        title=DEFAULT_CONVERSATION_TITLE,
    )
    db.add(conversation)
    await db.flush()
    return conversation


def _encode_cursor(message_id: int) -> str:
    """把消息 id 编码为不透明游标。"""
    raw = f"id:{message_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> int | None:
    """解析游标；非法游标按无游标处理（从第一页开始）。"""
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    if not raw.startswith("id:"):
        return None
    try:
        return int(raw.removeprefix("id:"))
    except ValueError:
        return None


async def list_messages(
    db: AsyncSession,
    conversation_id: int,
    *,
    cursor: str | None = None,
    limit: int = 30,
) -> tuple[list[KnowledgeMessage], str | None]:
    """按 (created_at, id) 稳定顺序游标分页读取消息。"""
    limit = max(1, min(limit, 100))
    cursor_id = _decode_cursor(cursor)
    stmt = (
        select(KnowledgeMessage)
        .where(KnowledgeMessage.conversation_id == conversation_id)
        .order_by(
            KnowledgeMessage.created_at.asc(),
            KnowledgeMessage.id.asc(),
        )
        .limit(limit + 1)
    )
    if cursor_id is not None:
        stmt = stmt.where(KnowledgeMessage.id > cursor_id)
    rows = (await db.execute(stmt)).scalars().all()
    next_cursor = None
    if len(rows) > limit:
        next_cursor = _encode_cursor(rows[limit - 1].id)
        rows = rows[:limit]
    return list(rows), next_cursor


def message_out(
    message: KnowledgeMessage,
    run: KnowledgeAgentRun | None = None,
) -> KnowledgeMessageOut:
    """组装消息响应。"""
    return KnowledgeMessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        message_type=message.message_type,
        content=message.content,
        client_message_id=message.client_message_id,
        run_id=message.run_id,
        scope_type=message.scope_type,
        project_id=message.project_id,
        project_name=message.project_name,
        request_context_mode=run.request_context_mode if run else None,
        context_decision=run.context_decision if run else None,
        standalone_query=run.standalone_query if run else None,
        topic_label=run.topic_label if run else None,
        input_context_version_id=run.input_context_version_id if run else None,
        output_context_version_id=run.output_context_version_id if run else None,
        created_at=message.created_at,
    )


async def active_run_for_conversation(
    db: AsyncSession,
    conversation_id: int,
) -> KnowledgeAgentRun | None:
    """返回对话当前活动 Run（waiting/processing），不存在返回 None。"""
    return (
        await db.execute(
            select(KnowledgeAgentRun)
            .where(
                KnowledgeAgentRun.conversation_id == conversation_id,
                KnowledgeAgentRun.status.in_(RUN_ACTIVE_STATUSES),
            )
            .order_by(KnowledgeAgentRun.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


def _scope_message_content(
    old_scope_type: str,
    old_project_name: str | None,
    new_scope_type: str,
    new_project_name: str | None,
) -> str:
    """组装范围事件消息文本。"""
    old_label = scope_label(old_scope_type, old_project_name)
    new_label = scope_label(new_scope_type, new_project_name)
    return f"问答范围从「{old_label}」切换为「{new_label}」"


async def change_scope(
    db: AsyncSession,
    conversation: KnowledgeConversation,
    payload: KnowledgeScopeChangeRequest,
) -> tuple[KnowledgeConversation, KnowledgeMessage]:
    """切换对话当前范围；活动 Run 期间返回 409，历史消息与 Run 保留快照。"""
    active = await active_run_for_conversation(db, conversation.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再切换范围",
        )

    project = await _validate_project(db, conversation.workspace_id, payload.project_id)
    if payload.scope_type == SCOPE_PROJECT and project is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目范围必须指定当前 Workspace 内的项目",
        )
    new_project_id = payload.project_id if payload.scope_type == SCOPE_PROJECT else None

    old_scope_type = conversation.scope_type
    old_project_name = None
    if conversation.project_id is not None:
        old_project = await db.get(Project, conversation.project_id)
        old_project_name = old_project.name if old_project else None
    new_project_name = project.name if project else None

    conversation.scope_type = payload.scope_type
    conversation.project_id = new_project_id
    conversation.last_activity_at = datetime.now(UTC)

    message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_SYSTEM,
        message_type=MESSAGE_TYPE_SCOPE_CHANGE,
        content=_scope_message_content(
            old_scope_type,
            old_project_name,
            payload.scope_type,
            new_project_name,
        ),
        scope_type=payload.scope_type,
        project_id=new_project_id,
        project_name=new_project_name,
    )
    db.add(message)
    await db.flush()
    return conversation, message
