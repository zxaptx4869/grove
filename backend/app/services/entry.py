"""Entry 归档、编辑与证据服务。"""

import hashlib
import json
import logging

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.revision import RevisionReplyDraft, run_revision_agent
from app.models import (
    Attachment,
    Candidate,
    Entry,
    EntrySourceEvidence,
    EntryVersion,
    Extraction,
    Node,
    Project,
    Source,
)
from app.models.behavior_signal import (
    SIGNAL_NODE_DECISION,
    SIGNAL_RELATION_DECISION,
)
from app.models.entry import (
    VERSION_AI_REVISION,
    VERSION_CREATED,
    VERSION_EDITED,
    VERSION_KNOWLEDGE_AGENT_REVISION,
    VERSION_RESTORED,
)
from app.models.extraction import CANDIDATE_CONFIRMED, CANDIDATE_PENDING, EXTRACTION_ACTIVE
from app.schemas.entry import (
    ApplyRevisionRequest,
    ApplyRevisionSuggestionRequest,
    EntryEvidenceOut,
    EntryOut,
    EntryUpdate,
    EntryVersionOut,
    NewNodeArchiveRequest,
    RevisionChatMessage,
    RevisionDraftPayload,
    RevisionRefineRequest,
    RevisionSuggestionOut,
    RevisionSuggestionRequest,
)
from app.services.behavior_signal import acceptance, record_behavior_signal
from app.services.project_context import schedule_refresh
from app.services.vector_store import mark_entry_embedding_pending

logger = logging.getLogger(__name__)

MAX_ENTRY_VERSIONS = 10
MAX_REVISION_MESSAGES = 20
MAX_REVISION_MESSAGE_CHARS = 2000
_REQUIRED_FIELDS = ("title", "content", "main_type")
_NULLABLE_FIELDS = ("info_nature", "applicable_condition", "note")
_BASELINE_FIELDS = (
    "title",
    "content",
    "main_type",
    "info_nature",
    "applicable_condition",
    "note",
    "node_id",
)


def entry_baseline(entry: Entry) -> dict:
    """提取 Entry 可变字段与 node id 的不可变基线快照（供并发校验复用）。"""
    return {field: getattr(entry, field) for field in _BASELINE_FIELDS}


def entry_fingerprint(baseline: dict) -> str:
    """按规范化 JSON 计算稳定指纹（排序键、紧凑分隔符）。"""
    canonical = json.dumps(
        baseline,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def entry_eager_options():
    """返回组装 Entry 响应所需的预加载选项。"""
    return (
        selectinload(Entry.node),
        selectinload(Entry.evidences).selectinload(EntrySourceEvidence.source),
    )


def _parse_evidence_refs(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in data if isinstance(item, dict)]


def _add_candidate_evidence_to_entry(db, candidate: Candidate, entry: Entry) -> None:
    """把候选的证据引用转换为目标 Entry 的来源证据。"""
    for ref in _parse_evidence_refs(candidate.evidence_refs):
        db.add(
            EntrySourceEvidence(
                entry_id=entry.id,
                source_id=candidate.source_id,
                attachment_id=ref.get("attachment_id") if "attachment_id" in ref else None,
                quote=str(ref.get("quote", "")) or None,
            )
        )


def entry_out(entry: Entry) -> EntryOut:
    """组装 Entry 响应。"""
    return EntryOut(
        id=entry.id,
        project_id=entry.project_id,
        node_id=entry.node_id,
        node_name=entry.node.name,
        title=entry.title,
        content=entry.content,
        main_type=entry.main_type,
        info_nature=entry.info_nature,
        applicable_condition=entry.applicable_condition,
        note=entry.note,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        evidences=[
            EntryEvidenceOut(
                id=item.id,
                source_id=item.source_id,
                attachment_id=item.attachment_id,
                quote=item.quote,
                source_title=item.source.title if item.source else "已删除来源",
            )
            for item in entry.evidences
        ],
    )


async def _snapshot_entry_version(
    db: AsyncSession,
    entry: Entry,
    change_type: str,
    change_summary: str | None = None,
) -> EntryVersion:
    """为 Entry 追加快照版本，并滚动丢弃超过保留上限的最旧版本。"""
    max_number = (
        await db.execute(
            select(func.max(EntryVersion.version_number)).where(
                EntryVersion.entry_id == entry.id
            )
        )
    ).scalar_one()
    next_number = (max_number or 0) + 1
    version = EntryVersion(
        entry_id=entry.id,
        version_number=next_number,
        title=entry.title,
        content=entry.content,
        main_type=entry.main_type,
        info_nature=entry.info_nature,
        applicable_condition=entry.applicable_condition,
        note=entry.note,
        node_id=entry.node_id,
        change_type=change_type,
        change_summary=change_summary,
    )
    db.add(version)
    await db.flush()
    if next_number > MAX_ENTRY_VERSIONS:
        await db.execute(
            delete(EntryVersion).where(
                EntryVersion.entry_id == entry.id,
                EntryVersion.version_number <= next_number - MAX_ENTRY_VERSIONS,
            )
        )
    return version


def _apply_revision_fields(entry: Entry, values: dict) -> bool:
    """按字段值字典更新 Entry，返回是否有实际变化。

    title/content/main_type 传 None 表示不修改；可空字段传 None 或空串表示清空。
    """
    changed = False
    for field in _REQUIRED_FIELDS:
        if field not in values or values[field] is None:
            continue
        value = values[field]
        if getattr(entry, field) != value:
            setattr(entry, field, value)
            changed = True
    for field in _NULLABLE_FIELDS:
        if field not in values:
            continue
        value = None if values[field] == "" else values[field]
        if getattr(entry, field) != value:
            setattr(entry, field, value)
            changed = True
    return changed


async def archive_candidate(
    db: AsyncSession,
    candidate: Candidate,
    node_id: int,
    *,
    signal_user_id: int | None = None,
) -> Entry:
    """采纳候选并原子创建 Entry 与证据。"""
    if candidate.status != CANDIDATE_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选已处理")
    source = await db.get(Source, candidate.source_id)
    if source is None or source.project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源尚未归属项目")

    node = await db.get(Node, node_id)
    if node is None or node.project_id != source.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="目录节点不属于当前项目"
        )

    entry = Entry(
        project_id=source.project_id,
        node_id=node_id,
        title=candidate.title,
        content=candidate.content,
        main_type=candidate.main_type,
        info_nature=candidate.info_nature,
        applicable_condition=candidate.applicable_condition,
        note=candidate.note,
    )
    db.add(entry)
    await db.flush()
    await _snapshot_entry_version(db, entry, VERSION_CREATED)

    _add_candidate_evidence_to_entry(db, candidate, entry)

    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await record_behavior_signal(
        db,
        workspace_id=source.workspace_id,
        user_id=signal_user_id,
        signal_type=SIGNAL_NODE_DECISION,
        recommended={
            "node_id": candidate.recommended_node_id,
            "routing_status": candidate.routing_status,
        },
        final={"node_id": node_id, "created_new_node": False},
        accepted=acceptance(candidate.recommended_node_id, node_id),
        project_id=source.project_id,
        source_id=candidate.source_id,
        candidate_id=candidate.id,
    )
    await db.flush()
    await schedule_refresh(db, source.project_id, "entry_archived")
    await mark_entry_embedding_pending(db, entry)
    return (
        await db.execute(
            select(Entry).options(*entry_eager_options()).where(Entry.id == entry.id)
        )
    ).scalar_one()


async def add_evidence_to_entry(
    db: AsyncSession,
    candidate: Candidate,
    entry_id: int,
    *,
    signal_user_id: int | None = None,
) -> Entry:
    """把候选来源证据补充到已有 Entry，并锁定候选。"""
    if candidate.status != CANDIDATE_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选已处理")
    source = await db.get(Source, candidate.source_id)
    if source is None or source.project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源尚未归属项目")

    entry = await db.get(Entry, entry_id)
    if entry is None or entry.project_id != source.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="目标 Entry 不属于当前项目"
        )

    _add_candidate_evidence_to_entry(db, candidate, entry)
    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await record_behavior_signal(
        db,
        workspace_id=source.workspace_id,
        user_id=signal_user_id,
        signal_type=SIGNAL_RELATION_DECISION,
        recommended={
            "relation_status": candidate.relation_status,
            "target_entry_id": candidate.relation_target_entry_id,
        },
        final={"action": "supplement_evidence", "entry_id": entry_id},
        accepted=acceptance(
            None if candidate.relation_status == "pending" else candidate.relation_status,
            "duplicate",
        ),
        project_id=source.project_id,
        source_id=candidate.source_id,
        candidate_id=candidate.id,
    )
    await db.flush()
    return (
        await db.execute(
            select(Entry).options(*entry_eager_options()).where(Entry.id == entry.id)
        )
    ).scalar_one()


async def apply_revision_to_entry(
    db: AsyncSession,
    candidate: Candidate,
    payload: ApplyRevisionRequest,
    *,
    signal_user_id: int | None = None,
) -> Entry:
    """把候选修订草稿应用到已有 Entry，并补充来源证据、锁定候选。"""
    if candidate.status != CANDIDATE_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选已处理")
    source = await db.get(Source, candidate.source_id)
    if source is None or source.project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源尚未归属项目")

    entry = await db.get(Entry, payload.entry_id)
    if entry is None or entry.project_id != source.project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="目标 Entry 不属于当前项目"
        )

    values = {field: getattr(payload, field) for field in payload.model_fields_set}
    changed = _apply_revision_fields(entry, values)

    _add_candidate_evidence_to_entry(db, candidate, entry)
    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await record_behavior_signal(
        db,
        workspace_id=source.workspace_id,
        user_id=signal_user_id,
        signal_type=SIGNAL_RELATION_DECISION,
        recommended={
            "relation_status": candidate.relation_status,
            "target_entry_id": candidate.relation_target_entry_id,
        },
        final={"action": "apply_revision", "entry_id": payload.entry_id},
        accepted=acceptance(
            None if candidate.relation_status == "pending" else candidate.relation_status,
            "supplement",
        ),
        project_id=source.project_id,
        source_id=candidate.source_id,
        candidate_id=candidate.id,
    )
    await db.flush()
    if changed:
        await _snapshot_entry_version(db, entry, VERSION_AI_REVISION, payload.change_summary)
    await schedule_refresh(db, source.project_id, "entry_edited")
    await mark_entry_embedding_pending(db, entry)
    return (
        await db.execute(
            select(Entry).options(*entry_eager_options()).where(Entry.id == entry.id)
        )
    ).scalar_one()


async def _find_or_create_node(
    db: AsyncSession,
    project_id: int,
    parent_id: int | None,
    name: str,
    description: str | None,
) -> tuple[Node, bool]:
    """查找同名同父节点，不存在时创建；返回 (节点, 是否新建)。"""
    normalized_name = name.strip().casefold()
    siblings = (
        await db.execute(
            select(Node).where(
                Node.project_id == project_id,
                Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id,
            )
        )
    ).scalars().all()
    for node in siblings:
        if (node.name or "").strip().casefold() == normalized_name:
            return node, False

    sibling_count = (
        await db.execute(
            select(func.count())
            .select_from(Node)
            .where(
                Node.project_id == project_id,
                Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id,
            )
        )
    ).scalar_one()
    node = Node(
        project_id=project_id,
        parent_id=parent_id,
        name=name.strip(),
        description=description,
        position=int(sibling_count),
    )
    db.add(node)
    await db.flush()
    return node, True


async def archive_candidate_with_new_node(
    db: AsyncSession,
    candidate: Candidate,
    payload: NewNodeArchiveRequest,
    *,
    signal_user_id: int | None = None,
) -> Entry:
    """创建或复用节点，并在同一事务内归档候选。"""
    if candidate.status != CANDIDATE_PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="候选已处理")

    source = await db.get(Source, candidate.source_id)
    if source is None or source.project_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="来源尚未归属项目")

    parent_id = payload.parent_id
    if parent_id is not None:
        parent = await db.get(Node, parent_id)
        if parent is None or parent.project_id != source.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="父节点不属于当前项目"
            )

    node, created = await _find_or_create_node(
        db,
        source.project_id,
        parent_id,
        payload.name,
        payload.description,
    )
    if created:
        await schedule_refresh(db, source.project_id)

    entry = await archive_candidate(db, candidate, node.id, signal_user_id=None)
    # 新节点归档：推荐通常无真实节点，单独记录 AI 新节点建议与用户最终动作
    await record_behavior_signal(
        db,
        workspace_id=source.workspace_id,
        user_id=signal_user_id,
        signal_type=SIGNAL_NODE_DECISION,
        recommended={
            "node_id": candidate.recommended_node_id,
            "routing_status": candidate.routing_status,
            "new_node_name": candidate.new_node_name,
        },
        final={"node_id": node.id, "created_new_node": created},
        accepted=acceptance(candidate.recommended_node_id, node.id),
        detail=f"新节点：{payload.name}",
        project_id=source.project_id,
        source_id=candidate.source_id,
        candidate_id=candidate.id,
    )
    return entry


async def edit_entry(
    db: AsyncSession,
    entry: Entry,
    payload: EntryUpdate,
) -> Entry:
    """编辑 Entry 字段与主目录节点。"""
    before = {
        field: getattr(entry, field)
        for field in (
            "title",
            "content",
            "main_type",
            "info_nature",
            "applicable_condition",
            "note",
            "node_id",
        )
    }
    fields = payload.model_fields_set
    if "title" in fields and payload.title is not None:
        entry.title = payload.title
    if "content" in fields and payload.content is not None:
        entry.content = payload.content
    if "main_type" in fields and payload.main_type is not None:
        entry.main_type = payload.main_type
    if "info_nature" in fields:
        entry.info_nature = payload.info_nature
    if "applicable_condition" in fields:
        entry.applicable_condition = payload.applicable_condition
    if "note" in fields:
        entry.note = payload.note
    if "node_id" in fields and payload.node_id is not None and payload.node_id != entry.node_id:
        node = await db.get(Node, payload.node_id)
        if node is None or node.project_id != entry.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="目录节点不属于当前项目"
            )
        entry.node_id = payload.node_id
        entry.node = node
    changed = any(getattr(entry, field) != before[field] for field in before)
    if changed:
        await _snapshot_entry_version(db, entry, VERSION_EDITED)
        await schedule_refresh(db, entry.project_id, "entry_edited")
        await mark_entry_embedding_pending(db, entry)
    return entry


async def list_entries_by_node(
    db: AsyncSession,
    project_id: int,
    node_id: int,
    scope: str = "direct",
) -> list[Entry]:
    """返回某项目某节点下的 Entry（仅本节点、严格后代或包含子树）。"""
    if scope == "descendants":
        node_ids = await _descendant_node_ids(db, project_id, node_id)
    elif scope == "subtree":
        node_ids = [node_id, *await _descendant_node_ids(db, project_id, node_id)]
    else:
        node_ids = [node_id]
    result = await db.execute(
        select(Entry)
        .options(*entry_eager_options())
        .where(Entry.project_id == project_id, Entry.node_id.in_(node_ids))
        .order_by(Entry.created_at.desc())
    )
    return list(result.scalars().all())


async def list_project_entries(db: AsyncSession, project_id: int) -> list[Entry]:
    """返回某项目全部已确认 Entry（按创建时间倒序，思维导图项目总根使用）。"""
    result = await db.execute(
        select(Entry)
        .options(*entry_eager_options())
        .where(Entry.project_id == project_id)
        .order_by(Entry.created_at.desc())
    )
    return list(result.scalars().all())


async def _descendant_node_ids(
    db: AsyncSession,
    project_id: int,
    node_id: int,
) -> list[int]:
    """收集节点全部严格后代的 id（不含自身）。"""
    nodes = (
        await db.execute(select(Node).where(Node.project_id == project_id))
    ).scalars().all()
    children_by_parent: dict[int | None, list[int]] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node.id)
    result: list[int] = []
    stack = list(children_by_parent.get(node_id, []))
    while stack:
        current = stack.pop()
        result.append(current)
        stack.extend(children_by_parent.get(current, []))
    return result


async def list_entry_versions(db: AsyncSession, entry_id: int) -> list[EntryVersion]:
    """返回 Entry 的保留版本，按版本号从新到旧排序。"""
    result = await db.execute(
        select(EntryVersion)
        .where(EntryVersion.entry_id == entry_id)
        .order_by(EntryVersion.version_number.desc())
    )
    return list(result.scalars().all())


async def entry_version_out_list(
    db: AsyncSession,
    versions: list[EntryVersion],
) -> list[EntryVersionOut]:
    """组装版本响应，批量解析目录名避免 N+1。"""
    node_ids = {version.node_id for version in versions}
    node_names: dict[int, str] = {}
    if node_ids:
        rows = await db.execute(select(Node.id, Node.name).where(Node.id.in_(node_ids)))
        node_names = {node_id: name for node_id, name in rows}
    return [
        EntryVersionOut(
            id=version.id,
            version_number=version.version_number,
            title=version.title,
            content=version.content,
            main_type=version.main_type,
            info_nature=version.info_nature,
            applicable_condition=version.applicable_condition,
            note=version.note,
            node_id=version.node_id,
            node_name=node_names.get(version.node_id, "已删除节点"),
            change_type=version.change_type,
            change_summary=version.change_summary,
            created_at=version.created_at,
        )
        for version in versions
    ]


async def restore_entry_version(
    db: AsyncSession,
    entry: Entry,
    version_id: int,
) -> Entry:
    """把 Entry 恢复到指定版本快照，追加恢复版本，不删除后续历史。"""
    version = await db.get(EntryVersion, version_id)
    if version is None or version.entry_id != entry.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")

    values = {
        "title": version.title,
        "content": version.content,
        "main_type": version.main_type,
        "info_nature": version.info_nature,
        "applicable_condition": version.applicable_condition,
        "note": version.note,
    }
    changed = _apply_revision_fields(entry, values)
    if version.node_id != entry.node_id:
        node = await db.get(Node, version.node_id)
        if node is None or node.project_id != entry.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="版本目录节点无效"
            )
        entry.node_id = version.node_id
        entry.node = node
        changed = True
    if changed:
        await _snapshot_entry_version(
            db,
            entry,
            VERSION_RESTORED,
            f"恢复到版本 {version.version_number}",
        )
        await schedule_refresh(db, entry.project_id, "entry_restored")
        await mark_entry_embedding_pending(db, entry)
    return entry


def _revision_suggestion_out(
    reply: RevisionReplyDraft,
    provider: str,
    model: str | None,
    is_fallback: bool,
    error: str | None,
) -> RevisionSuggestionOut:
    """把 Agent 回复组装为响应。"""
    reply = _normalize_revision_reply(reply)
    draft = None
    if reply.draft is not None:
        draft = RevisionDraftPayload(**reply.draft.model_dump())
    return RevisionSuggestionOut(
        intent=reply.intent,
        reply_text=reply.reply_text,
        draft=draft,
        provider=provider,
        model=model,
        is_fallback=is_fallback,
        error=error,
    )


def _normalize_revision_reply(reply: RevisionReplyDraft) -> RevisionReplyDraft:
    """按显式意图归一化：discuss 忽略草稿；propose 缺草稿降级为 discuss。"""
    if reply.intent == "discuss":
        if reply.draft is not None:
            logger.warning("修订建议意图为 discuss 却携带草稿，丢弃草稿")
            reply.draft = None
    elif reply.draft is None:
        logger.warning("修订建议意图为 propose 却缺少草稿，降级为 discuss")
        reply.intent = "discuss"
    return reply


async def generate_revision_suggestion(
    db: AsyncSession,
    workspace_id: int,
    entry: Entry,
    request: RevisionSuggestionRequest,
) -> RevisionSuggestionOut:
    """生成 AI 修订建议草稿。"""
    reply, provider, model, is_fallback, error = await run_revision_agent(
        db,
        workspace_id,
        entry,
        request.instruction,
        [],
        None,
    )
    return _revision_suggestion_out(reply, provider, model, is_fallback, error)


async def refine_revision_suggestion(
    db: AsyncSession,
    workspace_id: int,
    entry: Entry,
    request: RevisionRefineRequest,
) -> RevisionSuggestionOut:
    """基于完整对话历史与当前草稿继续调整修订建议。"""
    messages = request.messages[-MAX_REVISION_MESSAGES:]
    messages = [
        RevisionChatMessage(role=message.role, content=message.content[:MAX_REVISION_MESSAGE_CHARS])
        for message in messages
    ]
    current = request.draft.model_dump(exclude_none=True) if request.draft else None
    reply, provider, model, is_fallback, error = await run_revision_agent(
        db,
        workspace_id,
        entry,
        request.instruction,
        messages,
        current,
    )
    return _revision_suggestion_out(reply, provider, model, is_fallback, error)


async def apply_ai_revision_to_entry(
    db: AsyncSession,
    entry: Entry,
    payload: ApplyRevisionSuggestionRequest,
) -> Entry:
    """应用确认后的 AI 修订草稿，并追加 ai_revision 版本。"""
    values = {field: getattr(payload, field) for field in payload.model_fields_set}
    changed = _apply_revision_fields(entry, values)
    if changed:
        await _snapshot_entry_version(db, entry, VERSION_AI_REVISION, payload.change_summary)
        await schedule_refresh(db, entry.project_id, "entry_edited")
        await mark_entry_embedding_pending(db, entry)
        if payload.external_supplemented:
            await _create_revision_source(db, entry, payload)
    return entry


async def _create_revision_source(
    db: AsyncSession,
    entry: Entry,
    payload: ApplyRevisionSuggestionRequest,
) -> None:
    """把确认后的 AI 修订建议沉淀为虚拟 Source，并加入 Entry 来源证据。"""
    project = await db.get(Project, entry.project_id)
    if project is None:
        return
    title_part = (entry.title or "").strip()[:80] or "未命名知识"
    source = Source(
        workspace_id=project.workspace_id,
        project_id=entry.project_id,
        title=f"AI 修订建议：{title_part}"[:255],
        note=payload.instruction,
        status="done",
    )
    db.add(source)
    await db.flush()
    reply_text = payload.ai_reply or payload.change_summary or ""
    attachment = Attachment(
        source_id=source.id,
        kind="text",
        position=0,
        text_content=reply_text,
    )
    db.add(attachment)
    await db.flush()
    extraction = Extraction(
        source_id=source.id,
        provider=payload.provider or "revision",
        model=payload.model or "unknown",
        prompt_version="v1",
        status=EXTRACTION_ACTIVE,
        discarded_count=0,
    )
    db.add(extraction)
    await db.flush()
    db.add(
        EntrySourceEvidence(
            entry_id=entry.id,
            source_id=source.id,
            attachment_id=attachment.id,
            quote=payload.change_summary or payload.reason,
        )
    )


def _quote_key(quote: str | None) -> str:
    """规范化 quote 用于等价去重：压缩空白并忽略大小写。"""
    return " ".join((quote or "").split()).casefold()


async def add_deduped_evidence_to_entry(
    db: AsyncSession,
    *,
    entry_id: int,
    source_id: int,
    attachment_id: int | None,
    quote: str | None,
) -> EntrySourceEvidence | None:
    """去重补充 Entry 来源证据：等价关系已存在时复用，否则创建并返回新关系。

    等价判定使用 (source_id, attachment_id, 规范化 quote)；该策略与 SQLite/MySQL
    均可工作，不依赖数据库唯一索引。
    """
    existing_rows = (
        (
            await db.execute(
                select(EntrySourceEvidence).where(
                    EntrySourceEvidence.entry_id == entry_id,
                    EntrySourceEvidence.source_id == source_id,
                    EntrySourceEvidence.attachment_id
                    == (attachment_id if attachment_id is not None else None),
                )
            )
        )
        .scalars()
        .all()
    )
    target_key = _quote_key(quote)
    for row in existing_rows:
        if _quote_key(row.quote) == target_key:
            return None
    relation = EntrySourceEvidence(
        entry_id=entry_id,
        source_id=source_id,
        attachment_id=attachment_id,
        quote=quote,
    )
    db.add(relation)
    await db.flush()
    return relation


async def apply_knowledge_agent_revision(
    db: AsyncSession,
    entry: Entry,
    *,
    values: dict,
    change_summary: str | None,
    evidence_refs: list[dict],
    refresh_reason: str = "entry_edited",
) -> tuple[EntryVersion, list[int]]:
    """原子应用 Knowledge Agent 修订：更新字段、追加快照、去重补充证据并调度刷新。

    返回 (追加的版本, 本次真实新增的 EntrySourceEvidence id 列表)。
    调用方必须先完成基线/版本并发校验；本函数不校验归属。
    """
    changed = _apply_revision_fields(entry, values)
    added_ids: list[int] = []
    for ref in evidence_refs:
        relation = await add_deduped_evidence_to_entry(
            db,
            entry_id=entry.id,
            source_id=ref["source_id"],
            attachment_id=ref.get("attachment_id"),
            quote=ref.get("quote"),
        )
        if relation is not None:
            added_ids.append(relation.id)
    if changed:
        version = await _snapshot_entry_version(
            db,
            entry,
            VERSION_KNOWLEDGE_AGENT_REVISION,
            change_summary,
        )
    else:
        # 无实际字段变化：不制造空版本，返回 None 由调用方转为稳定冲突
        version = None
    await schedule_refresh(db, entry.project_id, refresh_reason)
    await mark_entry_embedding_pending(db, entry)
    return version, added_ids


async def restore_entry_from_snapshot(
    db: AsyncSession,
    entry: Entry,
    *,
    snapshot: dict,
    change_summary: str,
) -> EntryVersion | None:
    """按不可变快照恢复 Entry 字段与主目录，追加 restored 版本并调度刷新。

    撤销语义复用：调用方必须先完成并发校验；快照来自 Execution 的 before
    字段，不依赖可能被滚动清理的旧 EntryVersion。
    """
    values = {
        field: snapshot.get(field) for field in (*_REQUIRED_FIELDS, *_NULLABLE_FIELDS)
    }
    changed = _apply_revision_fields(entry, values)
    new_node_id = snapshot.get("node_id")
    if new_node_id is not None and new_node_id != entry.node_id:
        node = await db.get(Node, new_node_id)
        if node is None or node.project_id != entry.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="版本目录节点无效",
            )
        entry.node_id = new_node_id
        entry.node = node
        changed = True
    version = None
    if changed:
        version = await _snapshot_entry_version(
            db,
            entry,
            VERSION_RESTORED,
            change_summary,
        )
    await schedule_refresh(db, entry.project_id, "entry_restored")
    await mark_entry_embedding_pending(db, entry)
    return version
