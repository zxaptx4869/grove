"""Source 采集、列表、详情、归属与删除 API。"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, get_current_user, get_current_workspace
from app.models import (
    Attachment,
    Candidate,
    EntrySourceEvidence,
    ProcessingTask,
    Project,
    Source,
    User,
    Workspace,
)
from app.models.behavior_signal import SIGNAL_PROJECT_DECISION, BehaviorSignal
from app.models.extraction import CANDIDATE_CONFIRMED, CANDIDATE_PENDING
from app.models.processing import DONE, FAILED, PROCESSING, WAITING
from app.schemas.source import AttachmentOut, SourceOut, SourcePageOut, SourceUpdate
from app.services.attachment_storage import AttachmentStorage
from app.services.behavior_signal import record_behavior_signal
from app.services.entry_relation import clear_candidate_relations, route_relations
from app.services.routing import clear_candidate_routing, route_source

router = APIRouter(prefix="/api/sources", tags=["sources"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]
CurrentUser = Annotated[User, Depends(get_current_user)]
logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 5


def _source_out(
    source: Source,
    attachments: list[Attachment],
    project_locked: bool = False,
    evidence_entry_count: int = 0,
    pending_candidate_count: int = 0,
    candidate_count: int = 0,
) -> SourceOut:
    """把 ORM 对象组装为响应模型。"""
    return SourceOut(
        id=source.id,
        title=source.title,
        note=source.note,
        project_id=source.project_id,
        status=source.status,
        recommended_project_id=source.recommended_project_id,
        project_recommendation_reason=source.project_recommendation_reason,
        created_at=source.created_at,
        updated_at=source.updated_at,
        project_locked=project_locked,
        evidence_entry_count=evidence_entry_count,
        pending_candidate_count=pending_candidate_count,
        candidate_count=candidate_count,
        attachments=[
            AttachmentOut(
                id=item.id,
                kind=item.kind,
                position=item.position,
                mime_type=item.mime_type,
                file_name=item.file_name,
                text_content=item.text_content,
                ocr_text=item.ocr_text,
            )
            for item in attachments
        ],
    )


def _text_title(text: str) -> str:
    """文字 Source 标题取正文首行。"""
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:120] or "未命名文字"


async def _get_owned_source(db: DbSession, workspace_id: int, source_id: int) -> Source:
    """按 Workspace 归属获取 Source，不存在或越权返回 404。"""
    source = await db.get(Source, source_id)
    if source is None or source.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="来源不存在")
    return source


async def _validate_project(db: DbSession, workspace_id: int, project_id: int) -> Project:
    """校验项目属于当前 Workspace，否则 404。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


async def _load_source_out(db: DbSession, source_id: int) -> SourceOut:
    """加载 Source 及其附件并组装响应。"""
    source = (
        await db.execute(
            select(Source).options(selectinload(Source.attachments)).where(Source.id == source_id)
        )
    ).scalar_one()
    locked, counts, pending, total = await _source_state_counts(db, [source.id])
    return _source_out(
        source,
        list(source.attachments),
        source.id in locked,
        counts.get(source.id, 0),
        pending.get(source.id, 0),
        total.get(source.id, 0),
    )


async def _source_state_counts(
    db: DbSession,
    source_ids: list[int],
) -> tuple[set[int], dict[int, int], dict[int, int], dict[int, int]]:
    """批量计算锁定标记、证据计数、待确认候选数与候选总数，避免列表 N+1。"""
    locked: set[int] = set()
    entry_ids_by_source: dict[int, set[int]] = {}
    pending_counts: dict[int, int] = {}
    candidate_counts: dict[int, int] = {}
    if source_ids:
        confirmed = (
            await db.execute(
                select(Candidate.source_id).where(
                    Candidate.source_id.in_(source_ids),
                    Candidate.status == CANDIDATE_CONFIRMED,
                    Candidate.entry_id.is_not(None),
                )
            )
        ).scalars().all()
        locked.update(confirmed)
        rows = (
            await db.execute(
                select(EntrySourceEvidence.source_id, EntrySourceEvidence.entry_id).where(
                    EntrySourceEvidence.source_id.in_(source_ids)
                )
            )
        ).all()
        for source_id, entry_id in rows:
            locked.add(source_id)
            entry_ids_by_source.setdefault(source_id, set()).add(entry_id)
        pending_rows = (
            await db.execute(
                select(Candidate.source_id, func.count())
                .where(
                    Candidate.source_id.in_(source_ids),
                    Candidate.status == CANDIDATE_PENDING,
                )
                .group_by(Candidate.source_id)
            )
        ).all()
        pending_counts = {source_id: count for source_id, count in pending_rows}
        total_rows = (
            await db.execute(
                select(Candidate.source_id, func.count())
                .where(Candidate.source_id.in_(source_ids))
                .group_by(Candidate.source_id)
            )
        ).all()
        candidate_counts = {source_id: count for source_id, count in total_rows}
    counts = {source_id: len(entries) for source_id, entries in entry_ids_by_source.items()}
    return locked, counts, pending_counts, candidate_counts


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
    unassigned: bool = False,
    limit: int | None = Query(default=None, ge=1, le=100),
) -> list[SourceOut]:
    """列出当前 Workspace 的 Source，可按项目或未归属筛选。"""
    query = (
        select(Source)
        .options(selectinload(Source.attachments))
        .where(Source.workspace_id == workspace.id)
    )
    if project_id is not None:
        await _validate_project(db, workspace.id, project_id)
        query = query.where(Source.project_id == project_id)
    elif unassigned:
        query = query.where(Source.project_id.is_(None))

    ordered = query.order_by(Source.created_at.desc())
    if limit is not None:
        ordered = ordered.limit(limit)
    sources = (await db.execute(ordered)).scalars().unique().all()
    locked, counts, pending, candidate_total = await _source_state_counts(
        db, [source.id for source in sources]
    )
    return [
        _source_out(
            source,
            list(source.attachments),
            source.id in locked,
            counts.get(source.id, 0),
            pending.get(source.id, 0),
            candidate_total.get(source.id, 0),
        )
        for source in sources
    ]


@router.get("/query", response_model=SourcePageOut)
async def query_sources(
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
    unassigned: bool = False,
    source_status: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SourcePageOut:
    """全量来源历史查询：筛选、搜索与分页。"""
    base = select(Source).where(Source.workspace_id == workspace.id)
    if project_id is not None:
        await _validate_project(db, workspace.id, project_id)
        base = base.where(Source.project_id == project_id)
    elif unassigned:
        base = base.where(Source.project_id.is_(None))
    if source_status:
        base = base.where(Source.status == source_status)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        base = base.where(Source.title.ilike(keyword) | Source.note.ilike(keyword))

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    result = await db.execute(
        base.options(selectinload(Source.attachments))
        .order_by(Source.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sources = result.scalars().unique().all()
    locked, counts, pending, candidate_total = await _source_state_counts(
        db, [source.id for source in sources]
    )
    return SourcePageOut(
        items=[
            _source_out(
                source,
                list(source.attachments),
                source.id in locked,
                counts.get(source.id, 0),
                pending.get(source.id, 0),
                candidate_total.get(source.id, 0),
            )
            for source in sources
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SourceOut)
async def create_source(
    db: DbSession,
    workspace: CurrentWorkspace,
    files: Annotated[list[UploadFile] | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    project_id: Annotated[int | None, Form()] = None,
    note: Annotated[str | None, Form()] = None,
) -> SourceOut:
    """采集图片或文字创建 Source。"""
    files = files or []
    text = (text or "").strip() or None
    note = (note or "").strip() or None

    if not files and not text:
        raise HTTPException(status_code=400, detail="请提供图片或文字")
    if len(files) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_IMAGES} 张图片")
    if project_id is not None:
        await _validate_project(db, workspace.id, project_id)

    storage = AttachmentStorage.from_settings()
    attachment_kwargs: list[dict] = []
    saved_paths: list[str] = []
    title = "未命名文字"

    if files:
        title = Path(files[0].filename or "图片").name[:255] or "未命名图片"
        for position, file in enumerate(files):
            data = await file.read()
            if len(data) > MAX_IMAGE_BYTES:
                for path in saved_paths:
                    storage.delete(path)
                raise HTTPException(status_code=400, detail="单张图片不能超过 10MB")

            extension = IMAGE_EXTENSIONS.get(file.content_type or "")
            if extension is None:
                suffix = Path(file.filename or "").suffix.lower()
                if suffix not in ALLOWED_SUFFIXES:
                    for path in saved_paths:
                        storage.delete(path)
                    raise HTTPException(status_code=400, detail="仅支持 png、jpg、webp 图片")
                extension = suffix

            relative_path = storage.save(data, extension)
            saved_paths.append(relative_path)
            attachment_kwargs.append(
                {
                    "kind": "image",
                    "position": position,
                    "mime_type": file.content_type or None,
                    "file_name": Path(file.filename or "图片").name[:255],
                    "file_path": relative_path,
                }
            )
    if text:
        attachment_kwargs.append({"kind": "text", "position": len(files), "text_content": text})
    if not files:
        title = _text_title(text)[:255] or "未命名文字"

    source = Source(
        workspace_id=workspace.id,
        project_id=project_id,
        title=title,
        note=note,
    )
    db.add(source)
    await db.flush()
    for kwargs in attachment_kwargs:
        db.add(Attachment(source_id=source.id, **kwargs))
    await db.commit()

    return await _load_source_out(db, source.id)


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> SourceOut:
    """获取 Source 详情（含附件）。"""
    await _get_owned_source(db, workspace.id, source_id)
    return await _load_source_out(db, source_id)


@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: int,
    payload: SourceUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
    user: CurrentUser,
) -> SourceOut:
    """修改 Source 的说明或项目归属。"""
    source = await _get_owned_source(db, workspace.id, source_id)
    recommended_project_id = source.recommended_project_id
    if "note" in payload.model_fields_set:
        source.note = payload.note
    project_changed = (
        "project_id" in payload.model_fields_set
        and payload.project_id != source.project_id
    )
    if project_changed:
        if payload.project_id is not None:
            await _validate_project(db, workspace.id, payload.project_id)
        locked, _, _, _ = await _source_state_counts(db, [source.id])
        if source.id in locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该来源已被正式知识引用，如需移动请先处理关联 Entry",
            )
        if source.status == PROCESSING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="来源正在处理中，不能修改归属",
            )
        source.project_id = payload.project_id
        await record_behavior_signal(
            db,
            workspace_id=workspace.id,
            user_id=user.id,
            signal_type=SIGNAL_PROJECT_DECISION,
            recommended={"project_id": recommended_project_id},
            final={"project_id": payload.project_id},
            accepted=(
                payload.project_id == recommended_project_id
                if recommended_project_id is not None
                else None
            ),
            project_id=payload.project_id or recommended_project_id,
            source_id=source.id,
        )
        await clear_candidate_routing(db, source.id)
        await clear_candidate_relations(db, source.id)
    await db.commit()
    if project_changed:
        try:
            await route_source(db, source.id)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("路由来源失败：%s", source.id)
            await db.rollback()
        try:
            await route_relations(db, source.id)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("关系判断来源失败：%s", source.id)
            await db.rollback()
    return await _load_source_out(db, source_id)


@router.post("/{source_id}/process", response_model=SourceOut)
async def trigger_processing(
    source_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> SourceOut:
    """触发处理：创建或复位处理任务到等待处理。"""
    source = await _get_owned_source(db, workspace.id, source_id)
    task = (
        await db.execute(
            select(ProcessingTask).where(ProcessingTask.source_id == source.id)
        )
    ).scalar_one_or_none()

    if task is None:
        task = ProcessingTask(source_id=source.id, status=WAITING, retry_count=0)
        db.add(task)
    elif task.status == PROCESSING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="来源正在处理中")
    elif task.status == DONE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="来源已处理完成")
    else:
        if task.status == FAILED:
            task.retry_count += 1
        task.status = WAITING
        task.error = None
        task.step = None

    source.status = WAITING
    await db.commit()
    return await _load_source_out(db, source_id)


@router.delete("/{source_id}")
async def delete_source(
    source_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> dict[str, bool]:
    """删除 Source 并级联清理附件与本地文件。"""
    source = await _get_owned_source(db, workspace.id, source_id)
    referenced_entry_ids = (
        await db.execute(
            select(EntrySourceEvidence.entry_id).where(
                EntrySourceEvidence.source_id == source.id
            )
        )
    ).scalars().all()
    if referenced_entry_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该来源已被正式知识引用，不能删除；请先处理关联 Entry",
        )
    if source.status == PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="来源正在处理中，不能删除",
        )

    attachments = (
        await db.execute(select(Attachment).where(Attachment.source_id == source.id))
    ).scalars().all()
    file_paths = [item.file_path for item in attachments if item.kind == "image" and item.file_path]

    # 显式删除来源证据行：SQLite 默认不启用外键级联，需与 MySQL 行为保持一致
    await db.execute(
        delete(EntrySourceEvidence).where(EntrySourceEvidence.source_id == source.id)
    )
    # 行为信号保留：删除前把来源与候选引用置空（SQLite 外键级联不生效，显式处理）
    candidate_ids = (
        await db.execute(select(Candidate.id).where(Candidate.source_id == source.id))
    ).scalars().all()
    await db.execute(
        update(BehaviorSignal)
        .where(BehaviorSignal.source_id == source.id)
        .values(source_id=None)
    )
    if candidate_ids:
        await db.execute(
            update(BehaviorSignal)
            .where(BehaviorSignal.candidate_id.in_(candidate_ids))
            .values(candidate_id=None)
        )
    await db.delete(source)
    await db.commit()

    storage = AttachmentStorage.from_settings()
    for path in file_paths:
        storage.delete(path)
    return {"ok": True}


@router.get("/{source_id}/attachments/{attachment_id}/file")
async def get_attachment_file(
    source_id: int,
    attachment_id: int,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> FileResponse:
    """返回图片附件文件，校验归属后访问。"""
    source = await _get_owned_source(db, workspace.id, source_id)
    attachment = (
        await db.execute(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.source_id == source.id,
            )
        )
    ).scalar_one_or_none()
    if attachment is None or attachment.kind != "image" or not attachment.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件不存在")

    path = AttachmentStorage.from_settings().resolve(attachment.file_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="附件文件不存在")
    return FileResponse(path, media_type=attachment.mime_type or "application/octet-stream")
