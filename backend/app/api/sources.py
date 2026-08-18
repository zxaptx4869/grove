"""Source 采集、列表、详情、归属与删除 API。"""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, get_current_workspace
from app.models import Attachment, ProcessingTask, Project, Source, Workspace
from app.models.processing import DONE, FAILED, PROCESSING, WAITING
from app.schemas.source import AttachmentOut, SourceOut, SourceUpdate
from app.services.attachment_storage import AttachmentStorage
from app.services.entry_relation import clear_candidate_relations, route_relations
from app.services.routing import clear_candidate_routing, route_source

router = APIRouter(prefix="/api/sources", tags=["sources"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]
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


def _source_out(source: Source, attachments: list[Attachment]) -> SourceOut:
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
    return _source_out(source, list(source.attachments))


@router.get("", response_model=list[SourceOut])
async def list_sources(
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
    unassigned: bool = False,
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

    sources = (await db.execute(query.order_by(Source.created_at.desc()))).scalars().unique().all()
    return [_source_out(source, list(source.attachments)) for source in sources]


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

    if files and text:
        raise HTTPException(status_code=400, detail="一次采集只能包含图片或文字，不能同时提交")
    if not files and not text:
        raise HTTPException(status_code=400, detail="请提供图片或文字")
    if len(files) > MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_IMAGES} 张图片")
    if project_id is not None:
        await _validate_project(db, workspace.id, project_id)

    storage = AttachmentStorage.from_settings()
    attachment_kwargs: list[dict] = []
    saved_paths: list[str] = []
    title = "未命名图片"

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
    else:
        title = _text_title(text)[:255]
        attachment_kwargs.append({"kind": "text", "position": 0, "text_content": text})

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
) -> SourceOut:
    """修改 Source 的说明或项目归属。"""
    source = await _get_owned_source(db, workspace.id, source_id)
    if "note" in payload.model_fields_set:
        source.note = payload.note
    project_changed = (
        "project_id" in payload.model_fields_set
        and payload.project_id != source.project_id
    )
    if project_changed:
        if payload.project_id is not None:
            await _validate_project(db, workspace.id, payload.project_id)
        source.project_id = payload.project_id
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
    attachments = (
        await db.execute(select(Attachment).where(Attachment.source_id == source.id))
    ).scalars().all()
    file_paths = [item.file_path for item in attachments if item.kind == "image" and item.file_path]

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
