"""知识 Agent Run 应用服务：幂等提交、查询、取消与终态写入。"""

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentRun,
    KnowledgeCandidateDraft,
    KnowledgeConversation,
    KnowledgeEntryRevisionDraft,
    KnowledgeMessage,
    Project,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    BASIS_MODE_KNOWLEDGE_ONLY,
    CONTEXT_CLOSE_REASON_NEW_TOPIC,
    CONTEXT_MODE_NEW_TOPIC,
    DRAFT_CANCELLED,
    DRAFT_FAILED,
    DRAFT_TERMINAL_STATUSES,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_TYPE_ASSISTANT,
    MESSAGE_TYPE_USER,
    RESULT_MODE_ANSWER,
    RESULT_MODE_AUTO,
    RESULT_MODE_ENTRIES,
    REVISION_DRAFT_CANCELLED,
    REVISION_DRAFT_CONFIRMING,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_TERMINAL_STATUSES,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_KIND_ANSWER,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_KIND_ENTRY_REVISION,
    RUN_PARTIAL,
    RUN_PROCESSING,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
)
from app.schemas.knowledge_agent import (
    FallbackSummaryOut,
    InvestigationSummaryOut,
    KnowledgeAnswerBasisOut,
    KnowledgeAnswerOut,
    KnowledgeEntryResultSnapshotOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitRequest,
    KnowledgeStructuredQueryPlanOut,
)
from app.services.knowledge_agent.composite_answer_projection import (
    composite_answer_out,
)
from app.services.knowledge_agent.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    active_run_for_conversation,
    answer_basis_out,
)
from app.services.knowledge_agent.working_set import (
    close_active_context_version,
    get_active_context_version,
)

logger = logging.getLogger(__name__)


async def _sync_draft_status(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """把操作 Run 的取消/失败同步到关联 Draft（终态 Draft 不覆盖）。"""
    if run.run_kind != RUN_KIND_DRAFT_CANDIDATE:
        if run.run_kind == RUN_KIND_ENTRY_REVISION:
            # status 来自取消/失败路径，取值 cancelled 或 failed
            revision_status = (
                status
                if status in {REVISION_DRAFT_CANCELLED, REVISION_DRAFT_FAILED}
                else REVISION_DRAFT_FAILED
            )
            await db.execute(
                update(KnowledgeEntryRevisionDraft)
                .where(
                    KnowledgeEntryRevisionDraft.operation_run_id == run.id,
                    KnowledgeEntryRevisionDraft.status.notin_(
                        REVISION_DRAFT_TERMINAL_STATUSES
                    ),
                    # 确认已推进到 confirming 的草稿不能被取消同步覆盖
                    KnowledgeEntryRevisionDraft.status != REVISION_DRAFT_CONFIRMING,
                )
                .values(status=revision_status, error=error)
            )
        return
    await db.execute(
        update(KnowledgeCandidateDraft)
        .where(
            KnowledgeCandidateDraft.operation_run_id == run.id,
            KnowledgeCandidateDraft.status.notin_(DRAFT_TERMINAL_STATUSES),
        )
        .values(status=status, error=error)
    )


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

    message_text = payload.message.strip()
    if payload.source_run_id is None and not message_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="消息不能为空",
        )

    active = await active_run_for_conversation(db, conversation.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再提问",
        )

    context_mode = payload.context_mode
    answer_mode = payload.answer_mode
    result_mode = payload.result_mode
    # 公开依据模式：新客户端显式提交 auto/knowledge_only；旧客户端缺省按
    # knowledge_only 兼容，避免向无法展示依据的旧界面意外开放模型通用回答。
    basis_mode = payload.basis_mode or BASIS_MODE_KNOWLEDGE_ONLY
    source_run: KnowledgeAgentRun | None = None
    if payload.source_run_id is not None:
        source_run = await db.get(KnowledgeAgentRun, payload.source_run_id)
        if (
            source_run is None
            or source_run.conversation_id != conversation.id
            or source_run.workspace_id != conversation.workspace_id
            or source_run.owner_user_id != conversation.owner_user_id
            or source_run.run_kind != RUN_KIND_ANSWER
            or source_run.status not in {RUN_COMPLETED, RUN_PARTIAL}
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="来源 Run 不存在",
            )
        source_result_mode = source_run.actual_result_mode or RESULT_MODE_ANSWER
        if result_mode == RESULT_MODE_AUTO or result_mode == source_result_mode:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="模式纠正必须显式切换结果形式",
            )
        source_message = await db.get(KnowledgeMessage, source_run.user_message_id)
        if (
            source_message is None
            or source_message.conversation_id != conversation.id
            or source_message.message_type != MESSAGE_TYPE_USER
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="来源消息不存在",
            )
        message_text = source_message.content.strip()
        context_mode = source_run.request_context_mode or "auto"
        answer_mode = "auto"
        # 模式纠正继承来源 Run 已固化的依据限制，不允许重试参数放宽
        basis_mode = source_run.request_basis_mode or BASIS_MODE_KNOWLEDGE_ONLY
        scope_type = source_run.scope_type
        project_id = source_run.project_id
        project_name = source_run.project_name
        input_context_version_id = source_run.input_context_version_id
    else:
        scope_type, project_id, project_name = await _scope_snapshot(db, conversation)
        # 固化提交时的输入工作集版本；显式新话题在提交事务立即关闭旧活动版本
        active_version = await get_active_context_version(db, conversation.id)
        input_context_version_id = active_version.id if active_version is not None else None
        if context_mode == CONTEXT_MODE_NEW_TOPIC and active_version is not None:
            await close_active_context_version(
                db,
                conversation.id,
                reason=CONTEXT_CLOSE_REASON_NEW_TOPIC,
            )
    if not message_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="消息不能为空",
        )
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
        request_context_mode=context_mode,
        request_answer_mode=answer_mode,
        request_result_mode=result_mode,
        request_basis_mode=basis_mode,
        input_context_version_id=input_context_version_id,
        status=RUN_WAITING,
        current_step="waiting",
        active_slot=ACTIVE_SLOT,
        max_retries=1,
    )
    if source_run is not None:
        # 模式纠正复用来源 Run 已固化的独立问题与上下文决策，避免后续历史消息
        # 重新影响同一问题的解释；执行器会把这些字段视为可恢复决策而跳过分类模型。
        run.context_decision = source_run.context_decision
        run.standalone_query = source_run.standalone_query
        run.topic_label = source_run.topic_label
        run.history_message_ids_json = source_run.history_message_ids_json
        run.context_meta_json = source_run.context_meta_json
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


def _parse_entry_result(raw: str | None) -> KnowledgeEntryResultSnapshotOut | None:
    """解析 Run 结构化 Entry 结果 JSON；损坏或缺失返回 None。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return KnowledgeEntryResultSnapshotOut.model_validate(data)


def _parse_structured_query_plan(
    raw: str | None,
) -> KnowledgeStructuredQueryPlanOut | None:
    """仅返回严格规范化的 v1 计划摘要；旧 Run 与损坏快照返回 None。"""
    if not raw:
        return None
    try:
        return KnowledgeStructuredQueryPlanOut.model_validate_json(raw)
    except (ValidationError, TypeError, ValueError):
        logger.warning("Run 结构化查询计划快照无法解析，已从公开响应省略")
        return None


def _parse_investigation_summary(
    raw: str | None,
) -> InvestigationSummaryOut | None:
    """解析 Run 调查摘要 JSON。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return InvestigationSummaryOut.model_validate(data)


def run_out(run: KnowledgeAgentRun) -> KnowledgeRunOut:
    """组装 Run 响应。"""
    context_degraded = False
    if run.context_meta_json:
        try:
            meta = json.loads(run.context_meta_json)
            context_degraded = bool(meta.get("is_fallback")) or bool(meta.get("error"))
        except (json.JSONDecodeError, TypeError):
            context_degraded = False
    composite_plan, composite_coverage = composite_answer_out(
        run.composite_answer_plan_json,
        run.composite_answer_coverage_json,
    )
    return KnowledgeRunOut(
        id=run.id,
        conversation_id=run.conversation_id,
        run_kind=run.run_kind,
        source_run_id=run.source_run_id,
        target_entry_id=run.target_entry_id,
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
        request_answer_mode=run.request_answer_mode,
        actual_answer_mode=run.actual_answer_mode,
        request_result_mode=run.request_result_mode,
        actual_result_mode=run.actual_result_mode,
        request_basis_mode=run.request_basis_mode,
        answer_basis=answer_basis_out(run.answer_basis_json),
        current_round=run.current_round,
        input_context_version_id=run.input_context_version_id,
        output_context_version_id=run.output_context_version_id,
        context_degraded=context_degraded,
        fallback_summary=_parse_fallback_summary(run.fallback_summary),
        investigation_summary=_parse_investigation_summary(
            run.investigation_summary
        ),
        structured_query_plan=_parse_structured_query_plan(
            run.structured_query_plan_json
        ),
        composite_answer_plan=composite_plan,
        composite_answer_coverage=composite_coverage,
        answer=_parse_answer(run.answer_json),
        entry_result=_parse_entry_result(run.entry_result_json),
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
    await _sync_draft_status(db, run, status=DRAFT_CANCELLED, error="用户取消")
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
    await _sync_draft_status(db, run, status=DRAFT_FAILED, error=error)
    await db.flush()


async def finalize_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    *,
    answer: KnowledgeAnswerOut,
    status: str,
    fallback_summary: dict,
    answer_basis: KnowledgeAnswerBasisOut | None = None,
) -> None:
    """终态事务提交：助手消息、Run 结果、实际依据与活动槽释放一次性完成。"""
    if run.status in RUN_TERMINAL_STATUSES:
        return
    run.status = status
    run.current_step = None
    run.active_slot = None
    run.answer_json = answer.model_dump_json()
    if answer_basis is not None:
        run.answer_basis_json = answer_basis.model_dump_json()
    run.fallback_summary = json.dumps(fallback_summary, ensure_ascii=False)
    run.error = None
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = answer.answer
    await db.flush()


async def finalize_entry_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    *,
    status: str,
    entry_snapshot: KnowledgeEntryResultSnapshotOut,
    fallback_summary: dict,
    assistant_text: str,
    error: str | None = None,
) -> None:
    """终态事务提交：兼容助手摘要、actual result mode、结果快照与活动槽释放。

    结构化 Entry 查找不生成综合回答/Citation，也不创建输出工作集版本；
    失败/取消路径不得调用本函数，避免提交半份快照。
    """
    if run.status in RUN_TERMINAL_STATUSES:
        return
    run.status = status
    run.current_step = None
    run.active_slot = None
    run.actual_result_mode = RESULT_MODE_ENTRIES
    run.entry_result_json = entry_snapshot.model_dump_json()
    run.answer_json = None
    run.fallback_summary = json.dumps(fallback_summary, ensure_ascii=False)
    run.error = error
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = assistant_text
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
    await _sync_draft_status(
        db, run, status=DRAFT_CANCELLED, error=error or "运行中被取消"
    )
    await db.flush()
