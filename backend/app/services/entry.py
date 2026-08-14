"""Entry 归档、编辑与证据服务。"""

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Candidate, Entry, EntrySourceEvidence, Node, Source
from app.models.extraction import CANDIDATE_CONFIRMED, CANDIDATE_PENDING
from app.schemas.entry import EntryEvidenceOut, EntryOut, EntryUpdate


def _parse_evidence_refs(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [item for item in data if isinstance(item, dict)]


def entry_out(entry: Entry) -> EntryOut:
    """组装 Entry 响应。"""
    return EntryOut(
        id=entry.id,
        project_id=entry.project_id,
        node_id=entry.node_id,
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

    for ref in _parse_evidence_refs(candidate.evidence_refs):
        db.add(
            EntrySourceEvidence(
                entry_id=entry.id,
                source_id=source.id,
                attachment_id=ref.get("attachment_id") if "attachment_id" in ref else None,
                quote=str(ref.get("quote", "")) or None,
            )
        )

    candidate.status = CANDIDATE_CONFIRMED
    candidate.entry_id = entry.id
    await db.flush()
    return (
        await db.execute(
            select(Entry).options(selectinload(Entry.evidences)).where(Entry.id == entry.id)
        )
    ).scalar_one()


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
    return entry


async def list_entries_by_node(
    db: AsyncSession,
    project_id: int,
    node_id: int,
) -> list[Entry]:
    """返回某项目某节点下的 Entry。"""
    result = await db.execute(
        select(Entry)
        .options(selectinload(Entry.evidences))
        .where(Entry.project_id == project_id, Entry.node_id == node_id)
        .order_by(Entry.created_at)
    )
    return list(result.scalars().all())
