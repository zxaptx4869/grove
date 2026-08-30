"""候选草稿操作服务：来源 Run、Evidence 复验、提交流程与幂等确认。

边界：
- 所有对象按 owner + Workspace + Conversation 隔离，越权一律 404；
- 目标项目与 Evidence 只由服务端从 source Run 最终 citations 解析与重验，
  客户端对象 ID / quote / Evidence handle 不进入可信输入；
- 模型只生成 Draft；Source/Attachment/Extraction/Candidate 只在用户确认后
  由应用服务创建，任何路径不创建或修改正式 Entry；
- 普通 answer Run、旧 Reader 与移动只读流程不受影响。
"""

import json
import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.candidate_draft import (
    CANDIDATE_DRAFT_PROMPT_VERSION,
    run_candidate_draft_agent,
    seed_draft_from_answer,
)
from app.models import (
    Attachment,
    Candidate,
    Entry,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeCandidateDraft,
    KnowledgeMessage,
    Project,
    Source,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    DRAFT_CANCELLED,
    DRAFT_CONFIRMED,
    DRAFT_DRAFT,
    DRAFT_FAILED,
    DRAFT_GENERATING,
    DRAFT_TERMINAL_STATUSES,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    MESSAGE_TYPE_ASSISTANT,
    MESSAGE_TYPE_USER,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_KIND_ANSWER,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_PARTIAL,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_PROJECT,
    STEP_DRAFT_GENERATE,
    STEP_DRAFT_VALIDATE,
    STEP_DRAFT_VERIFY_EVIDENCE,
)
from app.schemas.knowledge_agent import (
    CandidateReceiptOut,
    KnowledgeCandidateDraftOut,
    KnowledgeDraftActionRequest,
    KnowledgeDraftEditRequest,
    KnowledgeDraftEvidenceOut,
)
from app.services.candidate_creation import (
    SOURCE_KIND_KNOWLEDGE_AGENT,
    build_knowledge_agent_attachment_text,
    create_candidate_from_answer,
)
from app.services.entry_relation import route_relations
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
    record_model_invocation,
    run_fallback_summary,
)
from app.services.knowledge_agent.runner import RunCancelled
from app.services.knowledge_agent.runs import (
    read_run_cancel_state,
    update_run_step,
)
from app.services.knowledge_agent.tools import record_tool_result
from app.services.routing import route_source

logger = logging.getLogger(__name__)


class DraftEvidenceInvalid(Exception):
    """当前 Evidence 无法重新核验：不得用历史快照创建新 Candidate。"""


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


async def get_source_run_for_draft(
    db: AsyncSession,
    conversation,
    source_run_id: int,
) -> tuple[KnowledgeAgentRun, object]:
    """校验来源回答 Run 归属与可整理性；返回 (Run, 最终回答)。"""
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
            detail="只能从普通知识问答回答发起整理",
        )
    if run.status not in {RUN_COMPLETED, RUN_PARTIAL}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答尚未完成或不可整理",
        )
    answer = _parse_answer_json(run)
    if answer is None or not answer.citations:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答没有最终有效引用，无法整理成知识",
        )
    return run, answer


async def available_target_projects(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    answer,
) -> tuple[list[Project], bool]:
    """按来源 Run 范围与最终 citations 解析可选目标项目。

    项目范围回答固定为该项目；Workspace 回答按引用命中项目统计，
    多项目时客户端必须先选择目标项目。
    """
    if run.scope_type == SCOPE_PROJECT:
        project = await db.get(Project, run.project_id) if run.project_id else None
        if project is None or project.workspace_id != run.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="来源回答的项目当前不可用",
            )
        return [project], True

    handles = _final_citation_handles(answer)
    rows = await evidence_rows_for_handles(db, run.id, handles)
    project_ids = {row.project_id for row in rows if row.project_id is not None}
    if not project_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答的引用没有可归属项目，无法整理",
        )
    projects = (
        (
            await db.execute(
                select(Project).where(
                    Project.id.in_(project_ids),
                    Project.workspace_id == run.workspace_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not projects:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答的引用项目当前不可用，无法整理",
        )
    return list(projects), len(projects) == 1


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


async def validate_draft_evidence_set(
    db: AsyncSession,
    draft: KnowledgeCandidateDraft,
) -> list[KnowledgeAgentEvidence]:
    """重验 Draft 采用的全部 Evidence；任一条失效即抛 DraftEvidenceInvalid。"""
    if draft.source_run_id is None or draft.target_project_id is None:
        raise DraftEvidenceInvalid("草稿的来源 Run 或目标项目已不可用")
    handles = _load_handles(draft.evidence_handles_json)
    rows = await evidence_rows_for_handles(db, draft.source_run_id, handles)
    by_handle = {row.handle: row for row in rows}
    valid: list[KnowledgeAgentEvidence] = []
    for handle in handles:
        row = by_handle.get(handle)
        if row is None:
            raise DraftEvidenceInvalid(f"Evidence 句柄已失效：{handle}")
        if not await _validate_evidence_current(
            db,
            workspace_id=draft.workspace_id,
            target_project_id=draft.target_project_id,
            evidence=row,
        ):
            raise DraftEvidenceInvalid(f"Evidence 当前无法重新核验：{handle}")
        valid.append(row)
    if not valid:
        raise DraftEvidenceInvalid("草稿没有当前可核验的证据")
    return valid


async def validate_citations_evidence_for_project(
    db: AsyncSession,
    *,
    source_run: KnowledgeAgentRun,
    answer,
    target_project_id: int,
) -> list[KnowledgeAgentEvidence]:
    """校验目标项目内至少一条最终 citation 当前仍可核验（提交前检查）。"""
    handles = _final_citation_handles(answer)
    rows = await evidence_rows_for_handles(db, source_run.id, handles)
    valid = [
        row
        for row in rows
        if await _validate_evidence_current(
            db,
            workspace_id=source_run.workspace_id,
            target_project_id=target_project_id,
            evidence=row,
        )
    ]
    return valid


def _load_handles(raw: str | None) -> list[str]:
    """解析 Evidence 句柄 JSON；损坏返回空列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in data if isinstance(item, str)] if isinstance(data, list) else []


async def get_owned_draft(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    draft_id: int,
) -> KnowledgeCandidateDraft:
    """按用户与 Workspace 读取 Draft；越权一律 404。"""
    draft = await db.get(KnowledgeCandidateDraft, draft_id)
    if (
        draft is None
        or draft.workspace_id != workspace_id
        or draft.owner_user_id != user_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="草稿不存在")
    return draft


def _draft_action_message_text(project_name: str) -> str:
    """组装可见用户操作消息文本。"""
    return f"整理成知识（目标项目：{project_name}）"


async def submit_draft_candidate(
    db: AsyncSession,
    conversation,
    payload: KnowledgeDraftActionRequest,
) -> tuple[KnowledgeMessage, KnowledgeAgentRun, KnowledgeCandidateDraft]:
    """在同一事务创建可见用户消息、助手占位、operation Run 与 generating Draft。"""
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
        if run is None or run.run_kind != RUN_KIND_DRAFT_CANDIDATE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该幂等键已用于普通问答消息",
            )
        draft = (
            await db.execute(
                select(KnowledgeCandidateDraft).where(
                    KnowledgeCandidateDraft.operation_run_id == run.id
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
            detail="对话存在进行中的问答，请等待完成或取消后再整理",
        )

    source_run, answer = await get_source_run_for_draft(
        db, conversation, payload.source_run_id
    )
    projects, _fixed = await available_target_projects(db, source_run, answer)
    project_ids = {project.id for project in projects}

    if conversation.scope_type == SCOPE_PROJECT:
        target_project = (
            await db.get(Project, conversation.project_id)
            if conversation.project_id
            else None
        )
        if target_project is None or target_project.id not in project_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="来源回答的引用不属于当前项目范围，无法整理",
            )
    else:
        if payload.target_project_id is None:
            if len(projects) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="回答命中多个项目，请先选择目标项目",
                )
            target_project = projects[0]
        else:
            target_project = await db.get(Project, payload.target_project_id)
            if (
                target_project is None
                or target_project.workspace_id != conversation.workspace_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="目标项目不存在",
                )
            if target_project.id not in project_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="目标项目不在来源回答的可整理范围内",
                )
    valid = await validate_citations_evidence_for_project(
        db,
        source_run=source_run,
        answer=answer,
        target_project_id=target_project.id,
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="目标项目当前没有可核验的来源证据，无法生成草稿",
        )

    user_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_USER,
        message_type=MESSAGE_TYPE_USER,
        content=_draft_action_message_text(target_project.name),
        client_message_id=payload.client_message_id,
        scope_type=SCOPE_PROJECT,
        project_id=target_project.id,
        project_name=target_project.name,
    )
    db.add(user_message)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已存在相同整理请求，请刷新后重试",
        ) from exc

    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        run_kind=RUN_KIND_DRAFT_CANDIDATE,
        source_run_id=source_run.id,
        scope_type=SCOPE_PROJECT,
        project_id=target_project.id,
        project_name=target_project.name,
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
            detail="对话存在进行中的问答，请等待完成或取消后再整理",
        ) from exc

    assistant_message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=MESSAGE_ROLE_ASSISTANT,
        message_type=MESSAGE_TYPE_ASSISTANT,
        content="",
        run_id=run.id,
        scope_type=SCOPE_PROJECT,
        project_id=target_project.id,
        project_name=target_project.name,
    )
    db.add(assistant_message)
    await db.flush()

    draft = KnowledgeCandidateDraft(
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        conversation_id=conversation.id,
        operation_run_id=run.id,
        source_run_id=source_run.id,
        target_project_id=target_project.id,
        target_project_name=target_project.name,
        status=DRAFT_GENERATING,
    )
    db.add(draft)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已存在相同整理请求，请刷新后重试",
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


async def _check_cancelled(run_id: int) -> None:
    """步骤边界检查取消请求：用独立短会话读取最新状态。"""
    cancel_requested, status_value = await read_run_cancel_state(run_id)
    if cancel_requested and status_value == RUN_PROCESSING:
        raise RunCancelled()


async def _source_question(db: AsyncSession, source_run: KnowledgeAgentRun) -> str:
    """读取来源回答的问题文本。"""
    if source_run.user_message_id is None:
        return ""
    message = await db.get(KnowledgeMessage, source_run.user_message_id)
    return message.content if message is not None else ""


async def execute_draft_candidate_run(db: AsyncSession, run: KnowledgeAgentRun) -> None:
    """Worker 执行受控草稿操作：Evidence 复验 → 生成 → 句柄白名单 → 终态提交。

    不执行上下文决策、回答模式路由、搜索、调查或工作集推进。
    """
    draft = (
        await db.execute(
            select(KnowledgeCandidateDraft).where(
                KnowledgeCandidateDraft.operation_run_id == run.id
            )
        )
    ).scalar_one_or_none()
    if draft is None:
        run.status = RUN_FAILED
        run.active_slot = None
        run.error = "操作 Run 缺少关联草稿"
        await db.flush()
        return

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_DRAFT_VERIFY_EVIDENCE)
    source_run = (
        await db.get(KnowledgeAgentRun, draft.source_run_id) if draft.source_run_id else None
    )
    if source_run is None:
        await _fail_draft_run(db, run, draft, "来源回答 Run 已不可用")
        return
    answer = _parse_answer_json(source_run)
    if answer is None or not answer.citations:
        await _fail_draft_run(db, run, draft, "来源回答没有最终有效引用")
        return
    try:
        valid = await validate_citations_evidence_for_project(
            db,
            source_run=source_run,
            answer=answer,
            target_project_id=draft.target_project_id,
        )
    except DraftEvidenceInvalid as exc:
        await _fail_draft_run(db, run, draft, f"证据当前无法重新核验：{exc}")
        return
    if not valid:
        await _fail_draft_run(db, run, draft, "目标项目当前没有可核验的来源证据")
        return
    await record_tool_result(
        db,
        run_id=run.id,
        tool_name="draft_verify_evidence",
        params={"draft_id": draft.id, "target_project_id": draft.target_project_id},
        result={
            "total": len(valid),
            "handles": [row.handle for row in valid],
        },
        duration_ms=0,
    )
    await db.commit()

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_DRAFT_GENERATE)
    question = await _source_question(db, source_run)
    original_answer = answer.answer if answer else ""
    evidences = [
        {
            "handle": row.handle,
            "source_title": row.source_title or "已删除来源",
            "quote": row.quote,
        }
        for row in valid
    ]
    draft_output, meta = await run_candidate_draft_agent(
        db,
        run.workspace_id,
        question=question,
        original_answer=original_answer,
        target_project_label=draft.target_project_name or "项目",
        evidences=evidences,
    )
    await record_model_invocation(
        db,
        run_id=run.id,
        meta=meta,
        prompt_version=CANDIDATE_DRAFT_PROMPT_VERSION,
    )

    allowed = {row.handle for row in valid}
    if draft_output is None:
        # 模型不可用/失败：使用确定性 seed，仅绑定有效 Evidence，显式标记降级
        draft_output = seed_draft_from_answer(
            question=question,
            original_answer=original_answer,
            handles=sorted(allowed),
        )
    selected = list(
        dict.fromkeys(
            handle for handle in draft_output.selected_evidence_handles if handle in allowed
        )
    )
    if not selected:
        await _fail_draft_run(
            db,
            run,
            draft,
            "草稿生成未返回任何有效证据句柄，未创建无来源草稿",
        )
        return
    await db.commit()

    await _check_cancelled(run.id)
    await update_run_step(run.id, STEP_DRAFT_VALIDATE)
    draft.title = draft_output.title
    draft.content = draft_output.content
    draft.main_type = draft_output.main_type
    draft.info_nature = draft_output.info_nature
    draft.evidence_handles_json = json.dumps(selected, ensure_ascii=False)
    draft.generation_meta_json = json.dumps(
        {
            "purpose": meta.purpose,
            "prompt_version": CANDIDATE_DRAFT_PROMPT_VERSION,
            "provider": meta.provider,
            "model": meta.model,
            "is_fallback": meta.is_fallback,
            "error": meta.error,
            "duration_ms": meta.duration_ms,
        },
        ensure_ascii=False,
    )
    draft.status = DRAFT_DRAFT
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
            assistant.content = "已生成可编辑的候选草稿，请检查并确认。"
    await db.flush()


async def _fail_draft_run(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    draft: KnowledgeCandidateDraft,
    error: str,
) -> None:
    """草稿操作失败：Run 与 Draft 同步进入失败终态，不创建任何知识对象。"""
    if run.status not in {
        RUN_COMPLETED,
        RUN_PARTIAL,
        RUN_FAILED,
        "cancelled",
    }:
        run.status = RUN_FAILED
        run.current_step = None
        run.active_slot = None
        run.error = error
    if draft.status not in DRAFT_TERMINAL_STATUSES:
        draft.status = DRAFT_FAILED
        draft.error = error
    if run.assistant_message_id is not None:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant is not None:
            assistant.content = "草稿生成失败，请返回对话重试。"
    await db.flush()
    await db.commit()


async def edit_draft(
    db: AsyncSession,
    draft: KnowledgeCandidateDraft,
    payload: KnowledgeDraftEditRequest,
) -> KnowledgeCandidateDraft:
    """编辑允许字段；confirmed/cancelled/failed 与受保护字段拒绝。"""
    if draft.status == DRAFT_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿已确认，无法编辑",
        )
    if draft.status == DRAFT_CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿已取消，无法编辑",
        )
    if draft.status == DRAFT_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿已失败，请重新发起整理",
        )
    if draft.status != DRAFT_DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿仍在生成中，暂不可编辑",
        )
    if payload.title is not None:
        draft.title = payload.title.strip()
    if payload.content is not None:
        draft.content = payload.content.strip()
    if payload.main_type is not None:
        draft.main_type = payload.main_type
    if payload.info_nature is not None:
        draft.info_nature = payload.info_nature
    await db.flush()
    return draft


async def cancel_draft(
    db: AsyncSession,
    draft: KnowledgeCandidateDraft,
) -> KnowledgeCandidateDraft:
    """取消未确认草稿：只改状态，不创建 Source/Candidate。"""
    if draft.status == DRAFT_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿已确认，无法取消",
        )
    if draft.status in DRAFT_TERMINAL_STATUSES:
        return draft
    draft.status = DRAFT_CANCELLED
    await db.flush()
    return draft


def _meta_dict(draft: KnowledgeCandidateDraft) -> dict:
    """解析生成元数据 JSON。"""
    if not draft.generation_meta_json:
        return {}
    try:
        data = json.loads(draft.generation_meta_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _candidate_receipt(candidate: Candidate) -> CandidateReceiptOut:
    """组装待确认 Candidate 回执。"""
    return CandidateReceiptOut(
        id=candidate.id,
        title=candidate.title,
        status=candidate.status,
        source_id=candidate.source_id,
        routing_status=candidate.routing_status,
        recommended_node_id=candidate.recommended_node_id,
        relation_status=candidate.relation_status,
        relation_target_entry_id=candidate.relation_target_entry_id,
        created_at=candidate.created_at,
    )


def draft_out(
    draft: KnowledgeCandidateDraft,
    evidence_by_handle: dict[str, KnowledgeAgentEvidence] | None = None,
) -> KnowledgeCandidateDraftOut:
    """组装草稿响应；evidence_by_handle 由调用方批量预加载避免 N+1。"""
    handles = _load_handles(draft.evidence_handles_json)
    meta = _meta_dict(draft)
    summaries: list[KnowledgeDraftEvidenceOut] = []
    if evidence_by_handle is not None:
        for handle in handles:
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
    return KnowledgeCandidateDraftOut(
        id=draft.id,
        conversation_id=draft.conversation_id,
        operation_run_id=draft.operation_run_id,
        source_run_id=draft.source_run_id,
        target_project_id=draft.target_project_id,
        target_project_name=draft.target_project_name,
        status=draft.status,
        title=draft.title,
        content=draft.content,
        main_type=draft.main_type,
        info_nature=draft.info_nature,
        evidence_handles=handles,
        evidence_summaries=summaries,
        generation_degraded=bool(meta.get("is_fallback")),
        generation_error=meta.get("error"),
        confirmed_candidate_id=draft.confirmed_candidate_id,
        error=draft.error,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


async def confirm_draft(
    db: AsyncSession,
    draft: KnowledgeCandidateDraft,
    client_operation_id: str,
) -> tuple[KnowledgeCandidateDraft, Candidate]:
    """确认草稿：原子创建虚拟 Source/Attachment/Extraction/pending Candidate。

    幂等：confirmed Draft 或相同幂等键重放返回同一 Candidate；
    并发：状态过渡 UPDATE 加唯一约束保证最多创建一个 Candidate；
    Evidence 失效返回 409，Draft 保持可编辑状态，不用历史快照写入。
    """
    if draft.status == DRAFT_CONFIRMED and draft.confirmed_candidate_id is not None:
        candidate = await db.get(Candidate, draft.confirmed_candidate_id)
        if candidate is not None:
            return draft, candidate
    if draft.status != DRAFT_DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只有可编辑草稿可以确认",
        )
    if not draft.title or not draft.content:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿标题或内容为空，无法确认",
        )

    locked = (
        await db.execute(
            update(KnowledgeCandidateDraft)
            .where(
                KnowledgeCandidateDraft.id == draft.id,
                KnowledgeCandidateDraft.status == DRAFT_DRAFT,
                KnowledgeCandidateDraft.confirmed_candidate_id.is_(None),
            )
            .values(
                status="confirming",
                client_operation_id=client_operation_id,
            )
        )
    ).rowcount
    if locked != 1:
        await db.rollback()
        fresh = await db.get(KnowledgeCandidateDraft, draft.id)
        if (
            fresh is not None
            and fresh.status == DRAFT_CONFIRMED
            and fresh.confirmed_candidate_id is not None
        ):
            candidate = await db.get(Candidate, fresh.confirmed_candidate_id)
            if candidate is not None:
                return fresh, candidate
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="草稿正在确认或已进入终态，请刷新后重试",
        )

    try:
        valid = await validate_draft_evidence_set(db, draft)
    except DraftEvidenceInvalid as exc:
        # 只恢复本 Draft 的状态，不整会话回滚（避免过期其他已加载对象）
        await db.execute(
            update(KnowledgeCandidateDraft)
            .where(KnowledgeCandidateDraft.id == draft.id)
            .values(status=DRAFT_DRAFT, client_operation_id=None)
        )
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"证据当前无法重新核验，请重新生成草稿：{exc}",
        ) from exc

    source_run = (
        await db.get(KnowledgeAgentRun, draft.source_run_id) if draft.source_run_id else None
    )
    if source_run is None:
        await db.execute(
            update(KnowledgeCandidateDraft)
            .where(KnowledgeCandidateDraft.id == draft.id)
            .values(status=DRAFT_DRAFT, client_operation_id=None)
        )
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源回答 Run 已不可用，无法确认",
        )
    answer = _parse_answer_json(source_run)
    original_answer = answer.answer if answer else ""
    question = await _source_question(db, source_run)
    evidence_refs = [
        {
            "attachment_id": row.attachment_id,
            "quote": row.quote,
        }
        for row in valid
    ]
    attachment_text = build_knowledge_agent_attachment_text(
        question=question,
        original_answer=original_answer,
        edited_content=draft.content,
        source_run_id=source_run.id,
    )
    try:
        candidate = await create_candidate_from_answer(
            db,
            workspace_id=draft.workspace_id,
            project_id=draft.target_project_id,
            question=question,
            title=draft.title,
            content=draft.content,
            main_type=draft.main_type,
            info_nature=draft.info_nature,
            evidence_refs=evidence_refs,
            provider="knowledge_agent",
            model="draft_confirmed",
            prompt_version=CANDIDATE_DRAFT_PROMPT_VERSION,
            source_kind=SOURCE_KIND_KNOWLEDGE_AGENT,
            source_run_id=source_run.id,
            attachment_text=attachment_text,
            reason="来自知识 Agent 对话整理",
        )
        draft.confirmed_candidate_id = candidate.id
        draft.status = DRAFT_CONFIRMED
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        fresh = await db.get(KnowledgeCandidateDraft, draft.id)
        if (
            fresh is not None
            and fresh.status == DRAFT_CONFIRMED
            and fresh.confirmed_candidate_id is not None
        ):
            candidate = await db.get(Candidate, fresh.confirmed_candidate_id)
            if candidate is not None:
                return fresh, candidate
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="确认请求冲突，请刷新后重试",
        ) from exc

    # Candidate 已创建：目录推荐/关系判断失败不影响待确认 Candidate，
    # 只暴露真实 pending 或失败状态，不把辅助阶段伪装为正常。
    try:
        await route_source(db, candidate.source_id)
        await route_relations(db, candidate.source_id)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.warning("候选确认后路由/关系判断失败，Candidate 保持待确认：%s", exc)
    await db.refresh(draft)
    return draft, candidate
