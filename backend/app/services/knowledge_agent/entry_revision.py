"""知识 Agent 单 Entry 修订服务：目标校验、Evidence 约束、基线快照与幂等提交。

边界：
- 所有对象按 owner + Workspace + Conversation 隔离，越权一律 404；
- 修订只能从来源回答最终 citations 中明确选择的 Entry 发起，普通 Composer
  不因文本内容自动进入写分支；
- 允许 Evidence 只来自最终回答实际采用的句柄（citations + conflicts），
  不加载整轮 Run 未采用的可引用 Evidence；
- 草稿固化不可变 base snapshot 与 fingerprint，客户端不可编辑受保护字段；
- 模型只生成草稿，Entry 字段更新、版本追加与 Evidence 补充只在用户确认后
  由应用服务在事务内执行。
"""

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.entry_revision import (
    ENTRY_REVISION_PROMPT_VERSION,
    run_entry_revision_agent,
)
from app.models import (
    Attachment,
    Entry,
    EntryVersion,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeEntryRevisionDraft,
    KnowledgeEntryRevisionExecution,
    KnowledgeMessage,
    Node,
    Project,
    Source,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_TYPE_ASSISTANT,
    MESSAGE_TYPE_USER,
    REVISION_DRAFT_APPLIED,
    REVISION_DRAFT_CANCELLED,
    REVISION_DRAFT_DRAFT,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_GENERATING,
    REVISION_DRAFT_TERMINAL_STATUSES,
    REVISION_DRAFT_UNDONE,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_KIND_ANSWER,
    RUN_KIND_ENTRY_REVISION,
    RUN_PARTIAL,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_PROJECT,
    STEP_REVISION_GENERATE,
    STEP_REVISION_VALIDATE,
    STEP_REVISION_VERIFY_EVIDENCE,
)
from app.schemas.knowledge_agent import (
    KnowledgeDraftEvidenceOut,
    KnowledgeEntryRevisionDraftOut,
    KnowledgeRevisionExecutionOut,
    KnowledgeRevisionFieldDiffOut,
)
from app.services.entry import entry_baseline, entry_fingerprint
from app.services.knowledge_agent.conversations import (
    DEFAULT_CONVERSATION_TITLE,
    active_run_for_conversation,
)
from app.services.knowledge_agent.evidence import (
    attachment_fingerprint,
    available_attachment_text,
    locate_verified_quote,
)
from app.services.knowledge_agent.observability import (
    next_tool_sequence,
    record_model_invocation,
    record_tool_call,
    run_fallback_summary,
)
from app.services.knowledge_agent.runner import RunCancelled
from app.services.knowledge_agent.runs import (
    read_run_cancel_state,
    update_run_step,
)

logger = logging.getLogger(__name__)

_ENTRY_FIELDS = (
    "title",
    "content",
    "main_type",
    "info_nature",
    "applicable_condition",
    "note",
)

_FIELD_LABELS = {
    "title": "标题",
    "content": "核心内容",
    "main_type": "主类型",
    "info_nature": "信息性质",
    "applicable_condition": "适用条件",
    "note": "补充说明",
}


class RevisionEvidenceInvalid(Exception):
    """当前 Evidence 无法重新核验：不得用历史快照更新正式 Entry。"""


def _parse_answer_json(run: KnowledgeAgentRun):
    """解析 Run 结构化回答；损坏或缺失返回 None。"""
    if not run.answer_json:
        return None
    try:
        data = json.loads(run.answer_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    from app.schemas.knowledge_agent import KnowledgeAnswerOut

    return KnowledgeAnswerOut.model_validate(data)


def _final_citation_handles(answer) -> list[str]:
    """收集最终回答采用的 Evidence 句柄（引用 + 冲突双方，去重）。"""
    handles = [citation.evidence_handle for citation in answer.citations]
    for conflict in answer.conflicts:
        if conflict.citation_a is not None:
            handles.append(conflict.citation_a.evidence_handle)
        if conflict.citation_b is not None:
            handles.append(conflict.citation_b.evidence_handle)
    return list(dict.fromkeys(handles))


def _final_citation_entry_ids(answer) -> set[int]:
    """收集最终回答引用涉及的全部 Entry id（含冲突双方）。"""
    ids = {citation.entry_id for citation in answer.citations if citation.entry_id}
    for conflict in answer.conflicts:
        if conflict.citation_a is not None and conflict.citation_a.entry_id:
            ids.add(conflict.citation_a.entry_id)
        if conflict.citation_b is not None and conflict.citation_b.entry_id:
            ids.add(conflict.citation_b.entry_id)
    return ids


async def evidence_rows_for_handles(
    db: AsyncSession,
    source_run_id: int,
    handles: list[str],
) -> list[KnowledgeAgentEvidence]:
    """按来源 Run 与句柄加载 Evidence；只接受可引用行。"""
    unique = list(dict.fromkeys(handles))
    if not unique:
        return []
    rows = (
        (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == source_run_id,
                    KnowledgeAgentEvidence.handle.in_(unique),
                    KnowledgeAgentEvidence.is_citable.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_owned_revision_draft(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    draft_id: int,
) -> KnowledgeEntryRevisionDraft:
    """按用户与 Workspace 读取修订草稿；越权一律 404。"""
    draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
    if (
        draft is None
        or draft.workspace_id != workspace_id
        or draft.owner_user_id != user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="修订草稿不存在")
    return draft


async def get_source_run_for_revision(
    db: AsyncSession,
    conversation: KnowledgeConversation,
    source_run_id: int,
) -> tuple[KnowledgeAgentRun, object]:
    """校验来源回答 Run 归属与可修订性；返回 (Run, 最终回答)。"""
    run = await db.get(KnowledgeAgentRun, source_run_id)
    if (
        run is None
        or run.conversation_id != conversation.id
        or run.workspace_id != conversation.workspace_id
        or run.owner_user_id != conversation.owner_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="来源回答不存在",
        )
    if run.run_kind != RUN_KIND_ANSWER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能从普通知识问答回答发起修订",
        )
    if run.status not in {RUN_COMPLETED, RUN_PARTIAL}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答尚未完成或不可修订",
        )
    answer = _parse_answer_json(run)
    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答没有最终有效内容，无法修订",
        )
    return run, answer


async def validate_revision_target(
    db: AsyncSession,
    conversation: KnowledgeConversation,
    source_run: KnowledgeAgentRun,
    answer,
    target_entry_id: int,
) -> Entry:
    """校验目标 Entry：归属当前 Workspace 项目且出现在最终 citations 中。"""
    entry = await db.get(Entry, target_entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="目标知识不存在",
        )
    project = await db.get(Project, entry.project_id)
    if (
        project is None
        or project.workspace_id != conversation.workspace_id
        or project.workspace_id != source_run.workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="目标知识不存在",
        )
    if entry.id not in _final_citation_entry_ids(answer):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标知识不在来源回答的最终引用中，无法修订",
        )
    return entry


async def _validate_evidence_current(
    db: AsyncSession,
    *,
    workspace_id: int,
    target_project_id: int,
    evidence: KnowledgeAgentEvidence,
) -> bool:
    """同步校验单条 Evidence 当前仍可核验；不可用返回 False。"""
    entry = await db.get(Entry, evidence.entry_id) if evidence.entry_id else None
    if entry is None or entry.project_id != target_project_id:
        return False
    source = await db.get(Source, evidence.source_id) if evidence.source_id else None
    if (
        source is None
        or source.workspace_id != workspace_id
        or source.project_id != target_project_id
    ):
        return False
    attachment = (
        await db.get(Attachment, evidence.attachment_id)
        if evidence.attachment_id
        else None
    )
    if attachment is None or attachment.source_id != source.id:
        return False
    text = available_attachment_text(attachment)
    if not text:
        return False
    if attachment_fingerprint(text) != evidence.content_fingerprint:
        return False
    if locate_verified_quote(text, evidence.quote) is None:
        return False
    return True


async def allowed_evidence_for_target(
    db: AsyncSession,
    *,
    source_run: KnowledgeAgentRun,
    answer,
    target_entry: Entry,
) -> list[KnowledgeAgentEvidence]:
    """只从最终 answer points/citations/conflicts 收集目标项目内当前有效 Evidence。"""
    handles = _final_citation_handles(answer)
    rows = await evidence_rows_for_handles(db, source_run.id, handles)
    valid = [
        row
        for row in rows
        if row.project_id == target_entry.project_id
        and await _validate_evidence_current(
            db,
            workspace_id=source_run.workspace_id,
            target_project_id=target_entry.project_id,
            evidence=row,
        )
    ]
    return valid


async def latest_entry_version(
    db: AsyncSession,
    entry_id: int,
) -> tuple[int | None, int | None]:
    """返回 Entry 最新版本 (id, number)；旧 Entry 无版本时返回 (None, None)。"""
    row = (
        await db.execute(
            select(EntryVersion.id, EntryVersion.version_number)
            .where(EntryVersion.entry_id == entry_id)
            .order_by(EntryVersion.version_number.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None
    return int(row[0]), int(row[1])


def _load_handles(raw: str | None) -> list[str]:
    """解析 Evidence 句柄 JSON；损坏返回空列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in data if isinstance(item, str)] if isinstance(data, list) else []


def _revision_action_message_text(entry_title: str, instruction: str) -> str:
    """组装可见用户操作消息文本。"""
    return f"修订《{entry_title}》：{instruction}"


async def submit_entry_revision(
    db: AsyncSession,
    conversation: KnowledgeConversation,
    payload,
) -> tuple[KnowledgeMessage, KnowledgeAgentRun, KnowledgeEntryRevisionDraft]:
    """在同一事务创建可见用户消息、助手占位、entry_revision Run 与 generating Draft。"""
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="修订指令不能为空",
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
        run = await db.get(KnowledgeAgentRun, existing.run_id) if existing.run_id else None
        if run is None or run.run_kind != RUN_KIND_ENTRY_REVISION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该幂等键已用于普通问答消息",
            )
        draft = (
            await db.execute(
                select(KnowledgeEntryRevisionDraft).where(
                    KnowledgeEntryRevisionDraft.operation_run_id == run.id
                )
            )
        ).scalar_one_or_none()
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="操作 Run 缺少关联草稿，请刷新后重试",
            )
        return existing, run, draft

    active = await active_run_for_conversation(db, conversation.id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="对话存在进行中的问答，请等待完成或取消后再修订",
        )

    source_run, answer = await get_source_run_for_revision(
        db, conversation, payload.source_run_id
    )
    target_entry = await validate_revision_target(
        db,
        conversation,
        source_run,
        answer,
        payload.target_entry_id,
    )
    valid = await allowed_evidence_for_target(
        db,
        source_run=source_run,
        answer=answer,
        target_entry=target_entry,
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标知识当前没有可核验的来源证据，无法生成修订草稿",
        )

    baseline = entry_baseline(target_entry)
    fingerprint = entry_fingerprint(baseline)
    version_id, version_number = await latest_entry_version(db, target_entry.id)

    user_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_USER,
        message_type=MESSAGE_TYPE_USER,
        content=_revision_action_message_text(target_entry.title, instruction),
        client_message_id=payload.client_message_id,
        scope_type=SCOPE_PROJECT,
        project_id=target_entry.project_id,
        project_name=None,
    )
    project = await db.get(Project, target_entry.project_id)
    if project is not None:
        user_message.project_name = project.name
    db.add(user_message)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已存在相同修订请求，请刷新后重试",
        ) from exc

    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        run_kind=RUN_KIND_ENTRY_REVISION,
        source_run_id=source_run.id,
        target_entry_id=target_entry.id,
        scope_type=SCOPE_PROJECT,
        project_id=target_entry.project_id,
        project_name=project.name if project is not None else None,
        user_message_id=user_message.id,
        status=RUN_WAITING,
        current_step=RUN_WAITING,
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
            detail="对话存在进行中的问答，请等待完成或取消后再修订",
        ) from exc

    assistant_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_ASSISTANT,
        message_type=MESSAGE_TYPE_ASSISTANT,
        content="",
        run_id=run.id,
        scope_type=SCOPE_PROJECT,
        project_id=target_entry.project_id,
        project_name=project.name if project is not None else None,
    )
    db.add(assistant_message)
    await db.flush()

    draft = KnowledgeEntryRevisionDraft(
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        conversation_id=conversation.id,
        operation_run_id=run.id,
        source_run_id=source_run.id,
        target_entry_id=target_entry.id,
        target_project_id=target_entry.project_id,
        target_project_name=project.name if project is not None else None,
        instruction=instruction,
        base_entry_json=json.dumps(baseline, ensure_ascii=False),
        base_entry_fingerprint=fingerprint,
        base_version_id=version_id,
        base_version_number=version_number,
        allowed_evidence_handles_json=json.dumps(
            [row.handle for row in valid], ensure_ascii=False
        ),
        status=REVISION_DRAFT_GENERATING,
    )
    db.add(draft)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已存在相同修订请求，请刷新后重试",
        ) from exc

    run.assistant_message_id = assistant_message.id
    user_message.run_id = run.id
    if conversation.title == DEFAULT_CONVERSATION_TITLE:
        conversation.title = (
            user_message.content[:30]
            + ("…" if len(user_message.content) > 30 else "")
        )
    conversation.last_activity_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(run)
    return user_message, run, draft


def _parse_base_entry(raw: str | None) -> dict:
    """解析不可变基线快照 JSON。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_field_value(value: str | None) -> str | None:
    """候选字段清洗：空串视为 None，与 Entry 可空字段语义一致。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def changed_fields_for_draft(
    draft: KnowledgeEntryRevisionDraft,
) -> list[KnowledgeRevisionFieldDiffOut]:
    """按 base snapshot 与当前草稿确定性计算字段差异；未变字段不返回。"""
    if draft.status == REVISION_DRAFT_GENERATING:
        # 生成中尚无候选内容：不把空候选字段误报为用户“清空”差异
        return []
    base = _parse_base_entry(draft.base_entry_json)
    diffs: list[KnowledgeRevisionFieldDiffOut] = []
    for field in _ENTRY_FIELDS:
        before = _normalize_field_value(base.get(field))
        after = _normalize_field_value(getattr(draft, field, None))
        if before != after:
            diffs.append(
                KnowledgeRevisionFieldDiffOut(
                    field=field,
                    label=_FIELD_LABELS.get(field, field),
                    before=before,
                    after=after,
                )
            )
    return diffs


def execution_out(
    execution: KnowledgeEntryRevisionExecution | None,
) -> KnowledgeRevisionExecutionOut | None:
    """组装执行摘要；不暴露内部快照与幂等键。"""
    if execution is None:
        return None
    added_ids = _load_handles(execution.added_evidence_ids_json)
    return KnowledgeRevisionExecutionOut(
        id=execution.id,
        draft_id=execution.draft_id,
        entry_id=execution.entry_id,
        status=execution.status,
        before_version_number=execution.before_version_number,
        after_version_number=execution.after_version_number,
        added_evidence_count=len(added_ids),
        error=execution.error,
        undone_at=execution.undone_at,
        created_at=execution.created_at,
        updated_at=execution.updated_at,
    )


def _generation_meta(draft: KnowledgeEntryRevisionDraft) -> dict:
    """解析生成元数据 JSON。"""
    if not draft.generation_meta_json:
        return {}
    try:
        data = json.loads(draft.generation_meta_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def revision_draft_out(
    draft: KnowledgeEntryRevisionDraft,
    evidence_by_handle: dict[str, KnowledgeAgentEvidence] | None = None,
    execution: KnowledgeEntryRevisionExecution | None = None,
) -> KnowledgeEntryRevisionDraftOut:
    """组装修订草稿响应；evidence_by_handle 由调用方批量预加载避免 N+1。"""
    selected = _load_handles(draft.selected_evidence_handles_json)
    meta = _generation_meta(draft)
    summaries: list[KnowledgeDraftEvidenceOut] = []
    if evidence_by_handle is not None:
        for handle in selected:
            row = evidence_by_handle.get(handle)
            if row is None:
                continue
            summaries.append(
                KnowledgeDraftEvidenceOut(
                    handle=row.handle,
                    entry_id=row.entry_id or 0,
                    entry_title=row.entry_title or "已删除 Entry",
                    source_id=row.source_id or 0,
                    source_title=row.source_title or "已删除来源",
                    quote=row.quote,
                )
            )
    return KnowledgeEntryRevisionDraftOut(
        id=draft.id,
        conversation_id=draft.conversation_id,
        operation_run_id=draft.operation_run_id,
        source_run_id=draft.source_run_id,
        target_entry_id=draft.target_entry_id,
        target_project_id=draft.target_project_id,
        target_project_name=draft.target_project_name,
        instruction=draft.instruction,
        status=draft.status,
        title=draft.title,
        content=draft.content,
        main_type=draft.main_type,
        info_nature=draft.info_nature,
        applicable_condition=draft.applicable_condition,
        note=draft.note,
        change_summary=draft.change_summary,
        reason=draft.reason,
        selected_evidence_handles=selected,
        evidence_summaries=summaries,
        changed_fields=changed_fields_for_draft(draft),
        generation_degraded=bool(meta.get("is_fallback")),
        generation_error=meta.get("error"),
        execution=execution_out(execution),
        error=draft.error,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


async def revision_drafts_out_batch(
    db: AsyncSession,
    drafts: list[KnowledgeEntryRevisionDraft],
) -> list[KnowledgeEntryRevisionDraftOut]:
    """批量组装修订草稿响应：一次查询加载全部 Evidence 与 Execution，避免 N+1。"""
    if not drafts:
        return []
    all_handles: set[str] = set()
    for draft in drafts:
        all_handles.update(_load_handles(draft.selected_evidence_handles_json))
    rows: list[KnowledgeAgentEvidence] = []
    if all_handles:
        rows = (
            (
                await db.execute(
                    select(KnowledgeAgentEvidence).where(
                        KnowledgeAgentEvidence.handle.in_(all_handles)
                    )
                )
            )
            .scalars()
            .all()
        )
    by_handle = {row.handle: row for row in rows}
    execution_ids = {
        draft.execution_id for draft in drafts if draft.execution_id is not None
    }
    executions_by_id: dict[int, KnowledgeEntryRevisionExecution] = {}
    if execution_ids:
        execution_rows = (
            (
                await db.execute(
                    select(KnowledgeEntryRevisionExecution).where(
                        KnowledgeEntryRevisionExecution.id.in_(execution_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        executions_by_id = {row.id: row for row in execution_rows}
    return [
        revision_draft_out(
            draft,
            by_handle,
            executions_by_id.get(draft.execution_id)
            if draft.execution_id is not None
            else None,
        )
        for draft in drafts
    ]


async def revision_drafts_for_runs(
    db: AsyncSession,
    run_ids: list[int],
) -> list[KnowledgeEntryRevisionDraft]:
    """按 operation Run id 批量读取修订草稿（消息页归并使用）。"""
    ids = list(dict.fromkeys(run_ids))
    if not ids:
        return []
    return list(
        (
            await db.execute(
                select(KnowledgeEntryRevisionDraft).where(
                    KnowledgeEntryRevisionDraft.operation_run_id.in_(ids)
                )
            )
        )
        .scalars()
        .all()
    )


async def get_execution_for_draft(
    db: AsyncSession,
    draft: KnowledgeEntryRevisionDraft,
) -> KnowledgeEntryRevisionExecution | None:
    """按草稿读取其唯一 Execution。"""
    if draft.execution_id is None:
        return None
    return await db.get(KnowledgeEntryRevisionExecution, draft.execution_id)


def _load_evidence_ids(raw: str | None) -> list[int]:
    """解析新增 Evidence id 列表 JSON。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [int(item) for item in data if isinstance(item, (int, str)) and str(item).isdigit()]


async def node_name_map(db: AsyncSession, node_ids: list[int]) -> dict[int, str]:
    """批量读取目录名，避免逐节点 N+1。"""
    ids = {node_id for node_id in node_ids if node_id is not None}
    if not ids:
        return {}
    rows = await db.execute(select(Node.id, Node.name).where(Node.id.in_(ids)))
    return {node_id: name for node_id, name in rows}


async def edit_revision_draft(
    db: AsyncSession,
    draft: KnowledgeEntryRevisionDraft,
    payload,
) -> KnowledgeEntryRevisionDraft:
    """编辑允许字段；applied/undone/cancelled/failed 与受保护字段拒绝。"""
    if draft.status == REVISION_DRAFT_APPLIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订已应用，无法编辑",
        )
    if draft.status == REVISION_DRAFT_UNDONE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订已撤销，无法编辑",
        )
    if draft.status == REVISION_DRAFT_CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订草稿已取消，无法编辑",
        )
    if draft.status == REVISION_DRAFT_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订草稿已失败，请重新发起修订",
        )
    if draft.status != REVISION_DRAFT_DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订草稿仍在生成中，暂不可编辑",
        )
    fields = payload.model_fields_set
    if "title" in fields:
        title = (payload.title or "").strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="修订标题不能为空",
            )
        draft.title = title
    if "content" in fields:
        content = (payload.content or "").strip()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="修订核心内容不能为空",
            )
        draft.content = content
    if "main_type" in fields:
        draft.main_type = payload.main_type
    if "info_nature" in fields:
        draft.info_nature = payload.info_nature
    if "applicable_condition" in fields:
        draft.applicable_condition = _normalize_field_value(payload.applicable_condition)
    if "note" in fields:
        draft.note = _normalize_field_value(payload.note)
    if "change_summary" in fields:
        summary = (payload.change_summary or "").strip()
        if not summary:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="变更摘要不能为空",
            )
        draft.change_summary = summary
    await db.flush()
    await db.refresh(draft)
    return draft


async def cancel_revision_draft(
    db: AsyncSession,
    draft: KnowledgeEntryRevisionDraft,
) -> KnowledgeEntryRevisionDraft:
    """取消未应用修订草稿：只改状态，不修改 Entry/版本/来源。"""
    if draft.status == REVISION_DRAFT_APPLIED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="修订已应用，无法取消",
        )
    if draft.status in REVISION_DRAFT_TERMINAL_STATUSES:
        return draft
    draft.status = REVISION_DRAFT_CANCELLED
    draft.error = None
    await db.flush()
    await db.refresh(draft)
    return draft


async def _check_cancelled(run_id: int) -> None:
    """步骤边界检查取消请求：用独立短会话读取最新状态。"""
    cancel_requested, status = await read_run_cancel_state(run_id)
    if cancel_requested and status == RUN_PROCESSING:
        raise RunCancelled()


async def _source_question(db: AsyncSession, source_run: KnowledgeAgentRun) -> str:
    """读取来源回答的用户问题。"""
    if source_run.user_message_id is None:
        return ""
    message = await db.get(KnowledgeMessage, source_run.user_message_id)
    return message.content if message is not None else ""


async def _fail_revision_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    draft: KnowledgeEntryRevisionDraft,
    error: str,
    *,
    meta: dict | None = None,
) -> None:
    """修订操作失败：Run 与 Draft 同步进入失败终态，保留可重试入口。"""
    if run.status not in {
        RUN_COMPLETED,
        RUN_PARTIAL,
        RUN_FAILED,
        RUN_CANCELLED,
    }:
        run.status = RUN_FAILED
        run.current_step = None
        run.active_slot = None
        run.error = error
        run.fallback_summary = json.dumps(
            {
                "has_fallback": True,
                "stages": [
                    {
                        "purpose": "entry_revision",
                        "is_fallback": True,
                        "provider": None,
                        "model": None,
                        "error": error,
                    }
                ],
            },
            ensure_ascii=False,
        )
    if draft.status not in REVISION_DRAFT_TERMINAL_STATUSES:
        draft.status = REVISION_DRAFT_FAILED
        draft.error = error
        if meta is not None:
            draft.generation_meta_json = json.dumps(meta, ensure_ascii=False)
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = "修订草稿生成失败，请返回对话重试。"
    await db.flush()
    await db.commit()


def _normalize_output_field(value: str | None) -> str | None:
    """候选字段清洗：空串视为 None，与 Entry 可空字段语义一致。"""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _revision_has_actual_change(
    base: dict,
    *,
    title: str,
    content: str,
    main_type: str,
    info_nature: str | None,
    applicable_condition: str | None,
    note: str | None,
) -> bool:
    """归一化后候选字段与基线完全一致时视为无实际差异。"""
    return not (
        _normalize_output_field(title) == _normalize_output_field(base.get("title"))
        and _normalize_output_field(content)
        == _normalize_output_field(base.get("content"))
        and _normalize_output_field(main_type)
        == _normalize_output_field(base.get("main_type"))
        and _normalize_output_field(info_nature)
        == _normalize_output_field(base.get("info_nature"))
        and _normalize_output_field(applicable_condition)
        == _normalize_output_field(base.get("applicable_condition"))
        and _normalize_output_field(note) == _normalize_output_field(base.get("note"))
    )


async def execute_entry_revision_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
) -> None:
    """执行一次 entry_revision 操作 Run：复验目标与 Evidence、调用模型、原子终态。

    本分支不执行 answer 搜索/调查，也不推进 Conversation 工作集；取消在步骤
    边界识别并丢弃模型结果。
    """
    draft = (
        await db.execute(
            select(KnowledgeEntryRevisionDraft).where(
                KnowledgeEntryRevisionDraft.operation_run_id == run.id
            )
        )
    ).scalar_one_or_none()
    if draft is None or run.status != RUN_PROCESSING:
        return

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_REVISION_VERIFY_EVIDENCE)
    target_entry = (
        await db.get(Entry, draft.target_entry_id)
        if draft.target_entry_id
        else None
    )
    if target_entry is None or target_entry.project_id != draft.target_project_id:
        await _fail_revision_run(
            db,
            run,
            draft,
            "目标知识当前不可用，无法生成修订草稿",
        )
        return
    allowed = await _current_allowed_evidence(db, draft)
    if not allowed:
        await _fail_revision_run(
            db,
            run,
            draft,
            "修订采用的来源证据当前无法核验，请重新发起修订",
        )
        return
    sequence = await next_tool_sequence(db, run.id)
    await record_tool_call(
        db,
        run_id=run.id,
        sequence=sequence,
        tool_name="revision_verify_evidence",
        status="ok",
        params_summary=json.dumps(
            {
                "draft_id": draft.id,
                "target_entry_id": target_entry.id,
                "target_project_id": draft.target_project_id,
            },
            ensure_ascii=False,
        ),
        result_summary=json.dumps(
            {
                "total": len(allowed),
                "handles": [row.handle for row in allowed],
            },
            ensure_ascii=False,
        ),
        duration_ms=0,
    )
    await db.commit()

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_REVISION_GENERATE)
    base = _parse_base_entry(draft.base_entry_json)
    source_run = (
        await db.get(KnowledgeAgentRun, draft.source_run_id)
        if draft.source_run_id
        else None
    )
    answer = _parse_answer_json(source_run) if source_run is not None else None
    evidences = [
        {
            "handle": row.handle,
            "source_title": row.source_title or "已删除来源",
            "quote": row.quote,
        }
        for row in allowed
    ]
    output, meta = await run_entry_revision_agent(
        db,
        run.workspace_id,
        entry=base,
        instruction=draft.instruction,
        question=await _source_question(db, source_run) if source_run is not None else "",
        original_answer=answer.answer if answer is not None else "",
        evidences=evidences,
    )
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=meta,
        prompt_version=ENTRY_REVISION_PROMPT_VERSION,
    )
    if output is None:
        meta_dict = {
            "purpose": meta.purpose,
            "prompt_version": ENTRY_REVISION_PROMPT_VERSION,
            "provider": meta.provider,
            "model": meta.model,
            "is_fallback": meta.is_fallback,
            "error": meta.error,
            "duration_ms": meta.duration_ms,
        }
        await _fail_revision_run(
            db,
            run,
            draft,
            meta.error or "修订模型不可用，未生成伪草稿",
            meta=meta_dict,
        )
        return
    allowed_handles = {row.handle for row in allowed}
    selected = list(
        dict.fromkeys(
            handle for handle in output.selected_evidence_handles if handle in allowed_handles
        )
    )
    if not selected:
        await _fail_revision_run(
            db,
            run,
            draft,
            "修订草稿未返回任何有效证据句柄，未生成无来源草稿",
        )
        return
    await db.commit()

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_REVISION_VALIDATE)
    if not _revision_has_actual_change(
        base,
        title=output.title,
        content=output.content,
        main_type=output.main_type,
        info_nature=_normalize_output_field(output.info_nature),
        applicable_condition=_normalize_output_field(output.applicable_condition),
        note=_normalize_output_field(output.note),
    ):
        await _fail_revision_run(
            db,
            run,
            draft,
            "修订草稿与当前知识没有实际差异，未生成可执行草稿",
        )
        return

    draft.title = output.title
    draft.content = output.content
    draft.main_type = output.main_type
    draft.info_nature = _normalize_output_field(output.info_nature)
    draft.applicable_condition = _normalize_output_field(output.applicable_condition)
    draft.note = _normalize_output_field(output.note)
    draft.change_summary = output.change_summary
    draft.reason = output.reason
    draft.selected_evidence_handles_json = json.dumps(selected, ensure_ascii=False)
    draft.generation_meta_json = json.dumps(
        {
            "purpose": meta.purpose,
            "prompt_version": ENTRY_REVISION_PROMPT_VERSION,
            "provider": meta.provider,
            "model": meta.model,
            "is_fallback": meta.is_fallback,
            "error": meta.error,
            "duration_ms": meta.duration_ms,
        },
        ensure_ascii=False,
    )
    draft.status = REVISION_DRAFT_DRAFT
    draft.error = None
    summary = await run_fallback_summary(db, run.id)
    run.status = RUN_COMPLETED
    run.current_step = None
    run.active_slot = None
    run.fallback_summary = json.dumps(summary, ensure_ascii=False)
    run.error = None
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = "已生成可编辑的修订草稿，请检查并确认。"
    await db.flush()


async def _current_allowed_evidence(
    db: AsyncSession,
    draft: KnowledgeEntryRevisionDraft,
) -> list[KnowledgeAgentEvidence]:
    """按草稿允许句柄重新核验当前有效 Evidence（目标项目内）。"""
    handles = _load_handles(draft.allowed_evidence_handles_json)
    if not handles or draft.source_run_id is None or draft.target_project_id is None:
        return []
    rows = await evidence_rows_for_handles(db, draft.source_run_id, handles)
    return [
        row
        for row in rows
        if row.project_id == draft.target_project_id
        and await _validate_evidence_current(
            db,
            workspace_id=draft.workspace_id,
            target_project_id=draft.target_project_id,
            evidence=row,
        )
    ]
