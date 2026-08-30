"""知识 Agent API：对话、消息、范围、Run 查询与取消，复用 Session/Bearer 鉴权。"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.api.deps import DbSession, get_current_user, get_current_workspace
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
    KnowledgeMessage,
    Project,
    User,
    Workspace,
)
from app.models.knowledge_agent import (
    MESSAGE_TYPE_USER,
    RUN_ACTIVE_STATUSES,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_KIND_ENTRY_REVISION,
)
from app.schemas.knowledge_agent import (
    KnowledgeCandidateDraftOut,
    KnowledgeConversationCreate,
    KnowledgeConversationOut,
    KnowledgeDraftActionOut,
    KnowledgeDraftActionRequest,
    KnowledgeDraftConfirmOut,
    KnowledgeDraftConfirmRequest,
    KnowledgeDraftEditRequest,
    KnowledgeEntryRevisionDraftOut,
    KnowledgeInvestigationDetailOut,
    KnowledgeInvestigationQueryOut,
    KnowledgeInvestigationRoundOut,
    KnowledgeMessagePageOut,
    KnowledgeModelInvocationOut,
    KnowledgeRevisionActionOut,
    KnowledgeRevisionActionRequest,
    KnowledgeRevisionConfirmOut,
    KnowledgeRevisionConfirmRequest,
    KnowledgeRevisionDraftEditRequest,
    KnowledgeRevisionUndoOut,
    KnowledgeRevisionUndoRequest,
    KnowledgeRunObservabilityOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitOut,
    KnowledgeRunSubmitRequest,
    KnowledgeScopeChangeRequest,
    KnowledgeToolCallOut,
)
from app.services.knowledge_agent.candidate import (
    cancel_draft,
    candidate_receipt,
    confirm_draft,
    drafts_for_runs,
    drafts_out_batch,
    edit_draft,
    get_owned_draft,
    submit_draft_candidate,
)
from app.services.knowledge_agent.conversations import (
    change_scope,
    conversation_out,
    create_conversation,
    get_owned_conversation,
    list_conversations,
    list_messages,
    message_out,
    recent_runs_for_conversations,
)
from app.services.knowledge_agent.entry_revision import (
    cancel_revision_draft,
    confirm_entry_revision,
    edit_revision_draft,
    execution_out,
    get_owned_revision_draft,
    revision_drafts_for_runs,
    revision_drafts_out_batch,
    revision_entry_out,
    submit_entry_revision,
    undo_entry_revision,
)
from app.services.knowledge_agent.runs import (
    cancel_run,
    get_owned_run,
    run_out,
    submit_message,
)
from app.services.knowledge_agent.working_set import active_context_summary

router = APIRouter(prefix="/api/knowledge-agent", tags=["knowledge-agent"])
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


def _json_list(raw: str | None) -> list:
    """解析 JSON 列表摘要；损坏时返回空列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _investigation_detail_out(
    investigation: KnowledgeInvestigation,
    rounds: list[KnowledgeInvestigationRound],
    queries: list[KnowledgeInvestigationQuery],
) -> KnowledgeInvestigationDetailOut:
    """组装逐轮调查详情（只读审计，不含整份原文）。"""
    round_out = []
    for round_row in rounds:
        meta = {}
        if round_row.meta_json:
            try:
                parsed = json.loads(round_row.meta_json)
                if isinstance(parsed, dict):
                    meta = parsed
            except (json.JSONDecodeError, TypeError):
                meta = {}
        round_out.append(
            KnowledgeInvestigationRoundOut(
                id=round_row.id,
                round_number=round_row.round_number,
                status=round_row.status,
                controller_action=round_row.controller_action,
                coverage=_json_list(round_row.coverage_json),
                gaps=_json_list(round_row.gaps_json),
                conflicts=_json_list(round_row.conflicts_json),
                reason=round_row.reason,
                queries_planned=round_row.queries_planned,
                queries_executed=round_row.queries_executed,
                entries_added=round_row.entries_added,
                evidence_added=round_row.evidence_added,
                provider=meta.get("provider"),
                model=meta.get("model"),
                is_fallback=bool(meta.get("is_fallback")),
                error=meta.get("error"),
                duration_ms=int(meta.get("duration_ms", 0)),
                created_at=round_row.created_at,
            )
        )
    query_out = [
        KnowledgeInvestigationQueryOut(
            id=query.id,
            round_number=query.round_number,
            sequence=query.sequence,
            original_query=query.original_query,
            normalized_query_hash=query.normalized_query_hash,
            status=query.status,
            result_counts=json.loads(query.result_counts_json)
            if query.result_counts_json
            else None,
            created_at=query.created_at,
        )
        for query in queries
    ]
    return KnowledgeInvestigationDetailOut(
        investigation_id=investigation.id,
        run_id=investigation.run_id,
        status=investigation.status,
        objective=investigation.objective,
        requested_answer_mode=investigation.requested_answer_mode,
        actual_answer_mode=investigation.actual_answer_mode,
        max_rounds=investigation.max_rounds,
        max_queries_per_round=investigation.max_queries_per_round,
        max_total_queries=investigation.max_total_queries,
        max_entries=investigation.max_entries,
        max_evidence=investigation.max_evidence,
        current_round=investigation.current_round,
        total_queries_executed=investigation.total_queries_executed,
        distinct_entries_found=investigation.distinct_entries_found,
        citable_evidence_count=investigation.citable_evidence_count,
        stop_reason=investigation.stop_reason,
        coverage=_json_list(investigation.coverage_summary),
        gaps=_json_list(investigation.gaps_summary),
        conflicts=_json_list(investigation.conflicts_summary),
        rounds=round_out,
        queries=query_out,
    )


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


async def _draft_action_exists(
    db: DbSession,
    conversation_id: int,
    client_message_id: str,
) -> bool:
    """判断草稿动作幂等键是否已存在（选择 201/200 状态码）。"""
    row = (
        await db.execute(
            select(KnowledgeMessage.id)
            .join(KnowledgeAgentRun, KnowledgeMessage.run_id == KnowledgeAgentRun.id)
            .where(
                KnowledgeMessage.conversation_id == conversation_id,
                KnowledgeMessage.client_message_id == client_message_id,
                KnowledgeMessage.message_type == MESSAGE_TYPE_USER,
                KnowledgeAgentRun.run_kind == RUN_KIND_DRAFT_CANDIDATE,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def _revision_action_exists(
    db: DbSession,
    conversation_id: int,
    client_message_id: str,
) -> bool:
    """判断修订动作幂等键是否已存在（选择 201/200 状态码）。"""
    row = (
        await db.execute(
            select(KnowledgeMessage.id)
            .join(KnowledgeAgentRun, KnowledgeMessage.run_id == KnowledgeAgentRun.id)
            .where(
                KnowledgeMessage.conversation_id == conversation_id,
                KnowledgeMessage.client_message_id == client_message_id,
                KnowledgeMessage.message_type == MESSAGE_TYPE_USER,
                KnowledgeAgentRun.run_kind == RUN_KIND_ENTRY_REVISION,
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
    topic_label, version_id, entry_count = await active_context_summary(
        db, conversation.id
    )
    recent_run = (await recent_runs_for_conversations(db, [conversation.id])).get(
        conversation.id
    )
    return conversation_out(
        conversation,
        project_name,
        active_version_id=version_id,
        active_topic_label=topic_label,
        active_entry_count=entry_count,
        recent_run=recent_run,
    )


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
    run_ids = {row.run_id for row in rows if row.run_id is not None}
    runs_by_id: dict[int, KnowledgeAgentRun] = {}
    if run_ids:
        run_rows = (
            await db.execute(
                select(KnowledgeAgentRun)
                .where(KnowledgeAgentRun.id.in_(run_ids))
                .order_by(KnowledgeAgentRun.id)
            )
        ).scalars().all()
        runs_by_id = {run.id: run for run in run_rows}
    drafts = await drafts_for_runs(db, list(run_ids))
    draft_out_rows = await drafts_out_batch(db, drafts)
    revision_drafts = await revision_drafts_for_runs(db, list(run_ids))
    revision_draft_out_rows = await revision_drafts_out_batch(db, revision_drafts)
    return KnowledgeMessagePageOut(
        items=[
            message_out(row, runs_by_id.get(row.run_id) if row.run_id else None)
            for row in rows
        ],
        next_cursor=next_cursor,
        runs=[run_out(run) for run in runs_by_id.values()],
        candidate_drafts=draft_out_rows,
        entry_revision_drafts=revision_draft_out_rows,
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
    recent_run = (await recent_runs_for_conversations(db, [conversation.id])).get(
        conversation.id
    )
    return conversation_out(conversation, project_name, recent_run=recent_run)


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
        user_message=message_out(user_message, run),
        run=run_out(run),
    )


@router.post(
    "/conversations/{conversation_id}/drafts",
    response_model=KnowledgeDraftActionOut,
)
async def submit_draft_action_endpoint(
    conversation_id: int,
    payload: KnowledgeDraftActionRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    response: Response,
) -> KnowledgeDraftActionOut:
    """显式「整理成知识」：创建可见用户消息、operation Run 与 generating Draft。"""
    conversation = await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    created = not await _draft_action_exists(
        db, conversation.id, payload.client_message_id
    )
    user_message, run, draft = await submit_draft_candidate(db, conversation, payload)
    await db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    draft_out = (await drafts_out_batch(db, [draft]))[0]
    return KnowledgeDraftActionOut(
        user_message=message_out(user_message, run),
        run=run_out(run),
        draft=draft_out,
    )


@router.get("/drafts/{draft_id}", response_model=KnowledgeCandidateDraftOut)
async def get_draft_endpoint(
    draft_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeCandidateDraftOut:
    """读取草稿：owner + Workspace 越权一律 404。"""
    draft = await get_owned_draft(db, workspace.id, user.id, draft_id)
    return (await drafts_out_batch(db, [draft]))[0]


@router.patch("/drafts/{draft_id}", response_model=KnowledgeCandidateDraftOut)
async def edit_draft_endpoint(
    draft_id: int,
    payload: KnowledgeDraftEditRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeCandidateDraftOut:
    """编辑草稿允许字段；目标项目/source Run/Evidence 集合不可编辑。"""
    draft = await get_owned_draft(db, workspace.id, user.id, draft_id)
    await edit_draft(db, draft, payload)
    await db.commit()
    return (await drafts_out_batch(db, [draft]))[0]


@router.post("/drafts/{draft_id}/cancel", response_model=KnowledgeCandidateDraftOut)
async def cancel_draft_endpoint(
    draft_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeCandidateDraftOut:
    """取消未确认草稿；活动 operation Run 一并取消，不创建任何知识对象。"""
    draft = await get_owned_draft(db, workspace.id, user.id, draft_id)
    operation_run = (
        await db.get(KnowledgeAgentRun, draft.operation_run_id)
        if draft.operation_run_id
        else None
    )
    if operation_run is not None and operation_run.status in RUN_ACTIVE_STATUSES:
        await cancel_run(db, operation_run)
    else:
        await cancel_draft(db, draft)
    await db.commit()
    return (await drafts_out_batch(db, [draft]))[0]


@router.post(
    "/conversations/{conversation_id}/entry-revision-drafts",
    response_model=KnowledgeRevisionActionOut,
)
async def submit_revision_action_endpoint(
    conversation_id: int,
    payload: KnowledgeRevisionActionRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
    response: Response,
) -> KnowledgeRevisionActionOut:
    """显式「修订这条知识」：创建可见用户消息、entry_revision Run 与 generating Draft。"""
    conversation = await get_owned_conversation(db, workspace.id, user.id, conversation_id)
    created = not await _revision_action_exists(
        db, conversation.id, payload.client_message_id
    )
    user_message, run, draft = await submit_entry_revision(db, conversation, payload)
    await db.commit()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    draft_out = (await revision_drafts_out_batch(db, [draft]))[0]
    return KnowledgeRevisionActionOut(
        user_message=message_out(user_message, run),
        run=run_out(run),
        draft=draft_out,
    )


@router.get(
    "/entry-revision-drafts/{draft_id}",
    response_model=KnowledgeEntryRevisionDraftOut,
)
async def get_revision_draft_endpoint(
    draft_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeEntryRevisionDraftOut:
    """读取修订草稿：owner + Workspace 越权一律 404。"""
    draft = await get_owned_revision_draft(db, workspace.id, user.id, draft_id)
    return (await revision_drafts_out_batch(db, [draft]))[0]


@router.patch(
    "/entry-revision-drafts/{draft_id}",
    response_model=KnowledgeEntryRevisionDraftOut,
)
async def edit_revision_draft_endpoint(
    draft_id: int,
    payload: KnowledgeRevisionDraftEditRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeEntryRevisionDraftOut:
    """编辑修订草稿允许字段；target Entry/项目/source Run/基线与 Evidence 不可编辑。"""
    draft = await get_owned_revision_draft(db, workspace.id, user.id, draft_id)
    await edit_revision_draft(db, draft, payload)
    await db.commit()
    return (await revision_drafts_out_batch(db, [draft]))[0]


@router.post(
    "/entry-revision-drafts/{draft_id}/cancel",
    response_model=KnowledgeEntryRevisionDraftOut,
)
async def cancel_revision_draft_endpoint(
    draft_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeEntryRevisionDraftOut:
    """取消未应用修订草稿；活动 operation Run 一并取消，不修改正式 Entry。"""
    draft = await get_owned_revision_draft(db, workspace.id, user.id, draft_id)
    operation_run = (
        await db.get(KnowledgeAgentRun, draft.operation_run_id)
        if draft.operation_run_id
        else None
    )
    if operation_run is not None and operation_run.status in RUN_ACTIVE_STATUSES:
        await cancel_run(db, operation_run)
    else:
        await cancel_revision_draft(db, draft)
    await db.commit()
    # 取消会经 ORM UPDATE 过期服务端生成的 updated_at：提交后显式刷新再组装
    await db.refresh(draft)
    return (await revision_drafts_out_batch(db, [draft]))[0]


@router.post(
    "/entry-revision-drafts/{draft_id}/confirm",
    response_model=KnowledgeRevisionConfirmOut,
)
async def confirm_revision_draft_endpoint(
    draft_id: int,
    payload: KnowledgeRevisionConfirmRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeRevisionConfirmOut:
    """确认修订：服务端重验基线/Evidence 后原子更新一条正式 Entry。"""
    draft = await get_owned_revision_draft(db, workspace.id, user.id, draft_id)
    confirmed, execution, entry = await confirm_entry_revision(
        db,
        draft,
        payload.client_operation_id,
    )
    draft_out = (await revision_drafts_out_batch(db, [confirmed]))[0]
    entry_out = await revision_entry_out(
        db, entry, execution.after_version_number
    )
    return KnowledgeRevisionConfirmOut(
        draft=draft_out,
        execution=draft_out.execution or execution_out(execution),
        entry=entry_out,
    )


@router.post(
    "/entry-revision-drafts/{draft_id}/undo",
    response_model=KnowledgeRevisionUndoOut,
)
async def undo_revision_draft_endpoint(
    draft_id: int,
    payload: KnowledgeRevisionUndoRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeRevisionUndoOut:
    """撤销已应用修订：恢复 before 快照、删除本操作新增证据、追加恢复版本。"""
    draft = await get_owned_revision_draft(db, workspace.id, user.id, draft_id)
    undone, execution, entry = await undo_entry_revision(
        db,
        draft,
        payload.client_operation_id,
    )
    draft_out = (await revision_drafts_out_batch(db, [undone]))[0]
    entry_out = await revision_entry_out(
        db, entry, execution.before_version_number
    )
    return KnowledgeRevisionUndoOut(
        draft=draft_out,
        execution=draft_out.execution or execution_out(execution),
        entry=entry_out,
    )


@router.post(
    "/drafts/{draft_id}/confirm",
    response_model=KnowledgeDraftConfirmOut,
)
async def confirm_draft_endpoint(
    draft_id: int,
    payload: KnowledgeDraftConfirmRequest,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeDraftConfirmOut:
    """确认草稿：服务端重验后幂等创建待确认 Candidate，不写正式 Entry。"""
    draft = await get_owned_draft(db, workspace.id, user.id, draft_id)
    confirmed, candidate = await confirm_draft(
        db,
        draft,
        payload.client_operation_id,
    )
    await db.commit()
    draft_out_row = (await drafts_out_batch(db, [confirmed]))[0]
    return KnowledgeDraftConfirmOut(
        draft=draft_out_row,
        candidate=candidate_receipt(candidate),
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
                investigation_id=item.investigation_id,
                round_number=item.round_number,
                query_sequence=item.query_sequence,
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
                investigation_id=item.investigation_id,
                round_number=item.round_number,
                query_sequence=item.query_sequence,
                created_at=item.created_at,
            )
            for item in invocations
        ],
    )


@router.get(
    "/runs/{run_id}/investigation",
    response_model=KnowledgeInvestigationDetailOut,
)
async def get_run_investigation_endpoint(
    run_id: int,
    db: DbSession,
    user: CurrentUser,
    workspace: CurrentWorkspace,
) -> KnowledgeInvestigationDetailOut:
    """读取调查 Run 的逐轮详情（只读审计；越权一律 404）。"""
    run = await get_owned_run(db, workspace.id, user.id, run_id)
    investigation = (
        await db.execute(
            select(KnowledgeInvestigation).where(
                KnowledgeInvestigation.run_id == run.id
            )
        )
    ).scalar_one_or_none()
    if investigation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="调查不存在",
        )
    rounds = (
        await db.execute(
            select(KnowledgeInvestigationRound)
            .where(KnowledgeInvestigationRound.investigation_id == investigation.id)
            .order_by(KnowledgeInvestigationRound.round_number)
        )
    ).scalars().all()
    queries = (
        await db.execute(
            select(KnowledgeInvestigationQuery)
            .where(KnowledgeInvestigationQuery.investigation_id == investigation.id)
            .order_by(
                KnowledgeInvestigationQuery.round_number,
                KnowledgeInvestigationQuery.sequence,
            )
        )
    ).scalars().all()
    return _investigation_detail_out(investigation, list(rounds), list(queries))
