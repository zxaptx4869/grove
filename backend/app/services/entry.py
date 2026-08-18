"""Entry 归档、编辑与证据服务。"""

import json

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Candidate, Entry, EntrySourceEvidence, Node, Source
from app.models.extraction import CANDIDATE_CONFIRMED, CANDIDATE_PENDING
from app.schemas.entry import (
    ApplyRevisionRequest,
    EntryEvidenceOut,
    EntryOut,
    EntryUpdate,
    NewNodeArchiveRequest,
)
from app.services.project_context import schedule_refresh


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
                source_title=item.source.title,
            )
            for item in entry.evidences
        ],
    )


async def archive_candidate(
    db: AsyncSession,
    candidate: Candidate,
    node_id: int,
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

    _add_candidate_evidence_to_entry(db, candidate, entry)

    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await db.flush()
    await schedule_refresh(db, source.project_id, "entry_archived")
    return (
        await db.execute(
            select(Entry).options(*entry_eager_options()).where(Entry.id == entry.id)
        )
    ).scalar_one()


async def add_evidence_to_entry(
    db: AsyncSession,
    candidate: Candidate,
    entry_id: int,
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

    _add_candidate_evidence_to_entry(db, candidate, entry)
    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await db.flush()
    await schedule_refresh(db, source.project_id, "entry_edited")
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

    return await archive_candidate(db, candidate, node.id)


async def edit_entry(
    db: AsyncSession,
    entry: Entry,
    payload: EntryUpdate,
) -> Entry:
    """编辑 Entry 字段与主目录节点。"""
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
    if payload.model_fields_set:
        await schedule_refresh(db, entry.project_id, "entry_edited")
    return entry


async def list_entries_by_node(
    db: AsyncSession,
    project_id: int,
    node_id: int,
    scope: str = "direct",
) -> list[Entry]:
    """返回某项目某节点下的 Entry（直接或严格后代）。"""
    if scope == "descendants":
        node_ids = await _descendant_node_ids(db, project_id, node_id)
    else:
        node_ids = [node_id]
    result = await db.execute(
        select(Entry)
        .options(*entry_eager_options())
        .where(Entry.project_id == project_id, Entry.node_id.in_(node_ids))
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
