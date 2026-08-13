"""项目上下文服务：生成、防抖刷新、失败回退与公共上下文组装。"""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import ProjectContextCorrections
from app.context.factory import get_project_context_generator
from app.core.config import get_settings
from app.models import Node, Project, ProjectContext
from app.models.project_context import FAILED, PENDING, READY
from app.schemas.project_context import (
    ProjectContextCorrectionsOut,
    ProjectContextCorrectionUpdate,
    ProjectContextOut,
)

logger = logging.getLogger(__name__)


def _parse_corrections(raw: str | None) -> ProjectContextCorrections:
    """把存储的 JSON 纠正解析为结构化模型。"""
    if not raw:
        return ProjectContextCorrections()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ProjectContextCorrections()
    return ProjectContextCorrections(
        project_summary=data.get("project_summary") if isinstance(data, dict) else None,
        current_focus=data.get("current_focus") if isinstance(data, dict) else None,
    )


def _dump_corrections(corrections: ProjectContextCorrections) -> str:
    """序列化纠正为 JSON 文本。"""
    return json.dumps(
        {
            "project_summary": corrections.project_summary,
            "current_focus": corrections.current_focus,
        },
        ensure_ascii=False,
    )


def _parse_topics(raw: str | None) -> list[str]:
    """把存储的 JSON 目录主题解析为列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


async def get_or_create_context(db: AsyncSession, project_id: int) -> ProjectContext:
    """按项目读取上下文，不存在时惰性建行。"""
    context = (
        await db.execute(
            select(ProjectContext).where(ProjectContext.project_id == project_id)
        )
    ).scalar_one_or_none()
    if context is None:
        context = ProjectContext(project_id=project_id, status=PENDING)
        db.add(context)
        await db.flush()
    return context


async def schedule_refresh(db: AsyncSession, project_id: int) -> ProjectContext:
    """安排一次防抖刷新：窗口内的重复调用合并为一次生成。"""
    settings = get_settings()
    context = await get_or_create_context(db, project_id)
    context.refresh_due_at = datetime.now(UTC) + timedelta(
        seconds=settings.context_refresh_debounce_seconds
    )
    return context


async def refresh_project_context(db: AsyncSession, project_id: int) -> ProjectContext:
    """生成并写回项目上下文；失败时保留上一份有效快照。"""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    context = await get_or_create_context(db, project_id)
    nodes = (
        await db.execute(
            select(Node).where(Node.project_id == project_id).order_by(Node.position)
        )
    ).scalars().all()
    corrections = _parse_corrections(context.user_corrections)

    try:
        draft = await get_project_context_generator().generate(project, list(nodes), corrections)
        context.project_summary = draft.project_summary
        context.current_focus = draft.current_focus
        context.directory_topics = json.dumps(draft.directory_topics, ensure_ascii=False)
        context.generated_at = datetime.now(UTC)
        context.status = READY
        context.error = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成项目上下文失败")
        context.error = str(exc)
        if context.status != READY or context.project_summary is None:
            context.status = FAILED

    return context


async def apply_corrections(
    db: AsyncSession,
    project_id: int,
    payload: ProjectContextCorrectionUpdate,
) -> ProjectContext:
    """保存用户纠正并安排刷新。"""
    context = await get_or_create_context(db, project_id)
    corrections = _parse_corrections(context.user_corrections)
    if "project_summary" in payload.model_fields_set:
        corrections.project_summary = payload.project_summary
    if "current_focus" in payload.model_fields_set:
        corrections.current_focus = payload.current_focus
    context.user_corrections = _dump_corrections(corrections)
    await schedule_refresh(db, project_id)
    return context


async def _assemble_out(project: Project, context: ProjectContext) -> ProjectContextOut:
    """把 Project 与 ProjectContext 组装为公共上下文响应。"""
    corrections = _parse_corrections(context.user_corrections)
    return ProjectContextOut(
        project_id=project.id,
        user_description=project.description,
        project_summary=corrections.project_summary or context.project_summary,
        current_focus=corrections.current_focus or context.current_focus,
        directory_topics=_parse_topics(context.directory_topics),
        lifecycle_status=project.status,
        generated_at=context.generated_at,
        status=context.status,
        error=context.error,
        corrections=ProjectContextCorrectionsOut(
            project_summary=corrections.project_summary,
            current_focus=corrections.current_focus,
        ),
    )


async def get_project_context_out(
    db: AsyncSession,
    workspace_id: int,
    project_id: int,
) -> ProjectContextOut:
    """公共上下文接口：返回结构化项目上下文，供前端与后续 Agent 共享。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    context = await get_or_create_context(db, project_id)
    if (
        context.refresh_due_at is None
        and context.status == PENDING
        and context.project_summary is None
    ):
        context.refresh_due_at = datetime.now(UTC)
    return await _assemble_out(project, context)
