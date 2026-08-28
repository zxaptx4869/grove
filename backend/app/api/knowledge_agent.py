"""知识 Agent API：对话、消息、范围、Run 查询与取消，复用 Session/Bearer 鉴权。"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession, get_current_user, get_current_workspace
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentToolCall,
    KnowledgeMessage,
    Project,
    User,
    Workspace,
)
from app.models.knowledge_agent import MESSAGE_TYPE_USER
from app.schemas.knowledge_agent import (
    KnowledgeConversationCreate,
    KnowledgeConversationOut,
    KnowledgeMessagePageOut,
    KnowledgeModelInvocationOut,
    KnowledgeRunObservabilityOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitOut,
    KnowledgeRunSubmitRequest,
    KnowledgeScopeChangeRequest,
    KnowledgeToolCallOut,
)
from app.services.knowledge_agent.conversations import (
    change_scope,
    conversation_out,
    create_conversation,
    get_owned_conversation,
    list_conversations,
    list_messages,
    message_out,
)
from app.services.knowledge_agent.runs import (
    cancel_run,
    get_owned_run,
    run_out,
    submit_message,
)

router = APIRouter(prefix="/api/knowledge-agent", tags=["knowledge-agent"])
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


async def _project_name(
    db: DbSession,
    workspace_id: int,
    project_id: int | None,
) -> str | None:
    """读取项目名；项目不存在或越权返回 None。"""
    if project_id is None:
        return None
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        return None
    return project.name


async def _message_exists(
    db: DbSession,
    conversation_id: int,
    client_message_id: str,
) -> bool:
    """判断幂等键是否已存在（用于选择 201/200 状态码）。"""
    row = (
        await db.execute(
            select(KnowledgeMessage.id).where(
                KnowledgeMessage.conversation_id == conversation_id,
                KnowledgeMessage.client_message_id == client_message_id,
                KnowledgeMessage.message_type == MESSAGE_TYPE_USER,
            )
        )
    ).scalar_one_or_none()
    return row is not None


@router.get("/conversations", response_model=list[KnowledgeConversationOut])
async def list_conversations_endpoint(
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> list[KnowledgeConversationOut]:
    """列出当前用户在当前 Workspace 的知识对话。"""
    return await list_conversations(db, workspace.id, user.id)


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=KnowledgeConversationOut,
)
async def create_conversation_endpoint(
    payload: KnowledgeConversationCreate,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeConversationOut:
    """创建知识对话（Workspace 全部知识或具体项目范围）。"""
    conversation = await create_conversation(db, workspace.id, user.id, payload)
    await db.commit()
    project_name = await _project_name(db, workspace.id, conversation.project_id)
    return conversation_out(conversation, project_name)


@router.get("/conversations/{conversation_id}", response_model=KnowledgeConversationOut)
async def get_conversation_endpoint(
    conversation_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeConversationOut:
    """读取对话详情与当前范围。"""
    conversation = await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    project_name = await _project_name(db, workspace.id, conversation.project_id)
    return conversation_out(conversation, project_name)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=KnowledgeMessagePageOut,
)
async def list_messages_endpoint(
    conversation_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> KnowledgeMessagePageOut:
    """游标分页读取对话消息。"""
    await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    rows, next_cursor = await list_messages(db, conversation_id, cursor=cursor, limit=limit)
    return KnowledgeMessagePageOut(
        items=[message_out(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.patch(
    "/conversations/{conversation_id}/scope",
    response_model=KnowledgeConversationOut,
)
async def change_scope_endpoint(
    conversation_id: int,
    payload: KnowledgeScopeChangeRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeConversationOut:
    """切换对话当前范围；活动 Run 期间返回 409。"""
    conversation = await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    conversation, _event = await change_scope(db, conversation, payload)
    await db.commit()
    project_name = await _project_name(db, workspace.id, conversation.project_id)
    return conversation_out(conversation, project_name)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=KnowledgeRunSubmitOut,
)
async def submit_message_endpoint(
    conversation_id: int,
    payload: KnowledgeRunSubmitRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    response: Response,
) -> KnowledgeRunSubmitOut:
    """提交问题：同一 client_message_id 幂等返回首次消息与 Run。"""
    conversation = await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    created = not await _message_exists(db, conversation.id, payload.client_message_id)
    user_message, run = await submit_message(db, conversation, payload)
    await db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return KnowledgeRunSubmitOut(
        user_message=message_out(user_message),
        run=run_out(run),
    )


@router.get("/runs/{run_id}", response_model=KnowledgeRunOut)
async def get_run_endpoint(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeRunOut:
    """查询 Run：状态、当前步骤、范围快照、降级摘要与终态结果。"""
    run = await get_owned_run(db, workspace.id, user.id, run_id)
    return run_out(run)


@router.post("/runs/{run_id}/cancel", response_model=KnowledgeRunOut)
async def cancel_run_endpoint(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeRunOut:
    """取消 waiting/processing Run；终态 Run 幂等返回当前状态。"""
    run = await get_owned_run(db, workspace.id, user.id, run_id)
    await cancel_run(db, run)
    await db.commit()
    return run_out(run)


@router.get("/runs/{run_id}/observability", response_model=KnowledgeRunObservabilityOut)
async def get_run_observability_endpoint(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeRunObservabilityOut:
    """读取 Run 的分阶段可排障记录（工具调用与模型调用）。"""
    await get_owned_run(db, workspace.id, user.id, run_id)
    tool_calls = (
        await db.execute(
            select(KnowledgeAgentToolCall)
            .where(KnowledgeAgentToolCall.run_id == run_id)
            .order_by(KnowledgeAgentToolCall.sequence)
        )
    ).scalars().all()
    invocations = (
        await db.execute(
            select(KnowledgeAgentModelInvocation)
            .where(KnowledgeAgentModelInvocation.run_id == run_id)
            .order_by(KnowledgeAgentModelInvocation.id)
        )
    ).scalars().all()
    return KnowledgeRunObservabilityOut(
        run_id=run_id,
        tool_calls=[
            KnowledgeToolCallOut(
                id=item.id,
                sequence=item.sequence,
                tool_name=item.tool_name,
                params_summary=item.params_summary,
                result_summary=item.result_summary,
                status=item.status,
                error=item.error,
                duration_ms=item.duration_ms,
                created_at=item.created_at,
            )
            for item in tool_calls
        ],
        model_invocations=[
            KnowledgeModelInvocationOut(
                id=item.id,
                purpose=item.purpose,
                prompt_version=item.prompt_version,
                provider=item.provider,
                model=item.model,
                is_fallback=item.is_fallback,
                error=item.error,
                duration_ms=item.duration_ms,
                usage=json.loads(item.usage_json) if item.usage_json else None,
                created_at=item.created_at,
            )
            for item in invocations
        ],
    )
