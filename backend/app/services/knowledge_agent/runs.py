"""知识 Agent Run 应用服务：幂等提交、查询、取消与终态写入。"""

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeMessage,
    Project,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_TYPE_ASSISTANT,
    MESSAGE_TYPE_USER,
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
)
from app.schemas.knowledge_agent import (
    FallbackSummaryOut,
    KnowledgeAnswerOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitRequest,
)
from app.services.knowledge_agent.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    active_run_for_conversation,
)

logger = logging.getLogger(__name__)


async def update_run_step(run_id: int, step: str) -> None:
    """用独立短会话更新运行进度步骤；终态后迟到步骤不再覆盖。"""
    async with async_session_factory() as db:
        await db.execute(
            update(KnowledgeAgentRun)
            .where(
                KnowledgeAgentRun.id == run_id,
                KnowledgeAgentRun.status == RUN_PROCESSING,
            )
            .values(current_step=step)
        )
        await db.commit()


async def read_run_cancel_state(run_id: int) -> tuple[bool, str]:
    """用独立短会话读取最新取消状态，MySQL 长事务也能看到其他会话刚提交的取消。"""
    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(
                    KnowledgeAgentRun.cancel_requested,
                    KnowledgeAgentRun.status,
                ).where(KnowledgeAgentRun.id == run_id)
            )
        ).first()
        if row is None:
            return False, ""
        return bool(row.cancel_requested), str(row.status)


async def _scope_snapshot(
    db: AsyncSession,
    conversation: KnowledgeConversation,
) -> tuple[str, int | None, str | None]:
    """读取对话当前范围快照（scope_type, project_id, project_name）。"""
    project_name = None
    if conversation.project_id is not None:
        project = await db.get(Project, conversation.project_id)
        project_name = project.name if project else None
    return conversation.scope_type, conversation.project_id, project_name


async def submit_message(
    db: AsyncSession,
    conversation: KnowledgeConversation,
    payload: KnowledgeRunSubmitRequest,
) -> tuple[KnowledgeMessage, KnowledgeAgentRun]:
    """在同一事务中幂等提交用户消息、助手占位消息与 waiting Run。"""
    message_text = payload.message.strip()
    if not message_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="消息不能为空",
        )

    existing = (
        await db.execute(
            select(KnowledgeMessage).where(
                KnowledgeMessage.conversation_id == conversation.id,
                KnowledgeMessage.client_message_id == payload.client_message_id,
                KnowledgeMessage.message_type == MESSAGE_TYPE_USER,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        run = await _run_by_message(db, existing)
        return existing, run

    active = await active_run_for_conversation(db, conversation.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再提问",
        )

    scope_type, project_id, project_name = await _scope_snapshot(db, conversation)
    user_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_USER,
        message_type=MESSAGE_TYPE_USER,
        content=message_text,
        client_message_id=payload.client_message_id,
        scope_type=scope_type,
        project_id=project_id,
        project_name=project_name,
    )
    db.add(user_message)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        existing = (
            await db.execute(
                select(KnowledgeMessage).where(
                    KnowledgeMessage.conversation_id == conversation.id,
                    KnowledgeMessage.client_message_id == payload.client_message_id,
                    KnowledgeMessage.message_type == MESSAGE_TYPE_USER,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            run = await _run_by_message(db, existing)
            return existing, run
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再提问",
        ) from exc

    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        scope_type=scope_type,
        project_id=project_id,
        project_name=project_name,
        user_message_id=user_message.id,
        request_context_mode=payload.context_mode,
        status=RUN_WAITING,
        current_step="waiting",
        active_slot=ACTIVE_SLOT,
        max_retries=1,
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再提问",
        ) from exc

    assistant_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_ASSISTANT,
        message_type=MESSAGE_TYPE_ASSISTANT,
        content="",
        run_id=run.id,
        scope_type=scope_type,
        project_id=project_id,
        project_name=project_name,
    )
    db.add(assistant_message)
    await db.flush()

    run.assistant_message_id = assistant_message.id
    user_message.run_id = run.id
    if conversation.title == DEFAULT_CONVERSATION_TITLE:
        # 首条问题确定性截断生成标题，不引入额外模型调用
        title = message_text[:30]
        conversation.title = title + ("…" if len(message_text) > 30 else "")
    conversation.last_activity_at = datetime.now(UTC)
    await db.flush()
    # 刷新服务端生成的 updated_at，避免组装响应时在 async 上下文触发惰性加载
    await db.refresh(run)
    return user_message, run


async def _run_by_message(
    db: AsyncSession,
    message: KnowledgeMessage,
) -> KnowledgeAgentRun | None:
    """按用户消息读取其 Run；消息未绑定 Run 时返回 None。"""
    if message.run_id is None:
        return None
    return await db.get(KnowledgeAgentRun, message.run_id)


async def get_owned_run(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    run_id: int,
) -> KnowledgeAgentRun:
    """按用户与 Workspace 读取 Run（经对话归属校验），越权一律 404。"""
    run = await db.get(KnowledgeAgentRun, run_id)
    if run is None or run.workspace_id != workspace_id or run.owner_user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run 不存在")
    conversation = await db.get(KnowledgeConversation, run.conversation_id)
    if (
        conversation is None
        or conversation.workspace_id != workspace_id
        or conversation.owner_user_id != user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run 不存在")
    return run


def _parse_fallback_summary(raw: str | None) -> FallbackSummaryOut | None:
    """解析 Run 降级摘要 JSON。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return FallbackSummaryOut.model_validate(data)


def _parse_answer(raw: str | None) -> KnowledgeAnswerOut | None:
    """解析 Run 结构化回答 JSON。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return KnowledgeAnswerOut.model_validate(data)


def run_out(run: KnowledgeAgentRun) -> KnowledgeRunOut:
    """组装 Run 响应。"""
    context_degraded = False
    if run.context_meta_json:
        try:
            meta = json.loads(run.context_meta_json)
            context_degraded = bool(meta.get("is_fallback")) or bool(meta.get("error"))
        except (json.JSONDecodeError, TypeError):
            context_degraded = False
    return KnowledgeRunOut(
        id=run.id,
        conversation_id=run.conversation_id,
        status=run.status,
        current_step=run.current_step,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        cancel_requested=run.cancel_requested,
        retry_count=run.retry_count,
        max_retries=run.max_retries,
        error=run.error,
        request_context_mode=run.request_context_mode,
        context_decision=run.context_decision,
        standalone_query=run.standalone_query,
        topic_label=run.topic_label,
        input_context_version_id=run.input_context_version_id,
        output_context_version_id=run.output_context_version_id,
        context_degraded=context_degraded,
        fallback_summary=_parse_fallback_summary(run.fallback_summary),
        answer=_parse_answer(run.answer_json),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


async def cancel_run(db: AsyncSession, run: KnowledgeAgentRun) -> KnowledgeAgentRun:
    """取消 Run：waiting 立即终态并释放槽位；processing 标记取消请求。"""
    if run.status in RUN_TERMINAL_STATUSES:
        return run
    run.cancel_requested = True
    if run.status == RUN_WAITING:
        run.status = RUN_CANCELLED
        run.current_step = None
        run.active_slot = None
        run.error = None
    await db.flush()
    await db.refresh(run)
    return run


async def mark_run_failed(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    error: str,
) -> None:
    """把超限或不可恢复的 Run 标记为失败并释放活动槽。"""
    if run.status in RUN_TERMINAL_STATUSES:
        return
    run.status = RUN_FAILED
    run.current_step = None
    run.active_slot = None
    run.error = error
    await db.flush()


async def finalize_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    *,
    answer: KnowledgeAnswerOut,
    status: str,
    fallback_summary: dict,
) -> None:
    """终态事务提交：助手消息、Run 结果与活动槽释放一次性完成。"""
    if run.status in RUN_TERMINAL_STATUSES:
        return
    run.status = status
    run.current_step = None
    run.active_slot = None
    run.answer_json = answer.model_dump_json()
    run.fallback_summary = json.dumps(fallback_summary, ensure_ascii=False)
    run.error = None
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = answer.answer
    await db.flush()


async def finalize_cancelled(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    error: str | None = None,
) -> None:
    """把 Run 标记为取消并释放活动槽；取消后的模型结果不写入正常回答。"""
    if run.status in RUN_TERMINAL_STATUSES:
        return
    run.status = RUN_CANCELLED
    run.current_step = None
    run.active_slot = None
    run.answer_json = None
    run.error = error
    await db.flush()
