"""项目上下文服务：生成、防抖刷新、失败回退与公共上下文组装。"""

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import ProjectContextCorrections
from app.context.factory import get_project_context_generator
from app.core.config import get_settings
from app.models import Entry, Node, Project, ProjectContext
from app.models.project_context import FAILED, PENDING, READY
from app.schemas.project_context import (
    EntryRecentOut,
    EntrySummaryOut,
    EntryTopNodeCoverageOut,
    ProjectContextCorrectionsOut,
    ProjectContextCorrectionUpdate,
    ProjectContextOut,
)

logger = logging.getLogger(__name__)

MAX_RECENT_ENTRIES = 20
MAX_TOP_LEVEL_NODES = 50
NODE_DESCRIPTION_LIMIT = 200


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


def _parse_entries_summary(raw: str | None) -> EntrySummaryOut | None:
    """把存储的知识覆盖摘要 JSON 解析为响应模型。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return EntrySummaryOut.model_validate(data)


def _parse_recent_themes(raw: str | None) -> list[str]:
    """把存储的近期主题 JSON 解析为列表。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _subtree_node_ids(nodes: list[Node], root_id: int) -> set[int]:
    """收集节点全部后代 id（不含自身）。"""
    children_by_parent: dict[int | None, list[int]] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node.id)
    result: set[int] = set()
    stack = list(children_by_parent.get(root_id, []))
    while stack:
        current = stack.pop()
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


async def _build_entries_summary(
    db: AsyncSession,
    project_id: int,
    nodes: list[Node],
) -> dict:
    """确定性聚合项目内已确认 Entry 的知识覆盖摘要。"""
    type_rows = (
        await db.execute(
            select(Entry.main_type, func.count())
            .where(Entry.project_id == project_id)
            .group_by(Entry.main_type)
        )
    ).all()
    by_type = {main_type: count for main_type, count in type_rows}
    total = sum(by_type.values())

    top_nodes = [node for node in nodes if node.parent_id is None]
    by_top_node: list[EntryTopNodeCoverageOut] = []
    if top_nodes:
        subtree_by_root: dict[int, set[int]] = {}
        all_node_ids: set[int] = set()
        for node in top_nodes:
            ids = _subtree_node_ids(nodes, node.id)
            ids.add(node.id)
            subtree_by_root[node.id] = ids
            all_node_ids.update(ids)

        counts_by_node: dict[int, int] = {}
        if all_node_ids:
            count_rows = (
                await db.execute(
                    select(Entry.node_id, func.count())
                    .where(
                        Entry.project_id == project_id,
                        Entry.node_id.in_(all_node_ids),
                    )
                    .group_by(Entry.node_id)
                )
            ).all()
            counts_by_node = {node_id: count for node_id, count in count_rows}

        for node in top_nodes[:MAX_TOP_LEVEL_NODES]:
            count = sum(counts_by_node.get(node_id, 0) for node_id in subtree_by_root[node.id])
            by_top_node.append(
                EntryTopNodeCoverageOut(node_id=node.id, name=node.name, count=count)
            )

    recent_rows = (
        await db.execute(
            select(Entry.id, Entry.title, Entry.node_id, Entry.updated_at)
            .where(Entry.project_id == project_id)
            .order_by(Entry.updated_at.desc())
            .limit(MAX_RECENT_ENTRIES)
        )
    ).all()
    node_names = {node.id: node.name for node in nodes}
    recent = [
        EntryRecentOut(
            entry_id=entry_id,
            title=title,
            node_name=node_names.get(node_id, ""),
            updated_at=updated_at,
        )
        for entry_id, title, node_id, updated_at in recent_rows
    ]
    return EntrySummaryOut(
        total=total,
        by_type=by_type,
        by_top_node=by_top_node,
        recent=recent,
        truncated_count=max(0, len(top_nodes) - MAX_TOP_LEVEL_NODES),
    ).model_dump(mode="json")


def _build_top_level_nodes(nodes: list[Node], entries_summary: dict) -> list[dict]:
    """组装生成器输入所需的顶级节点信息（名称 + 截断说明 + 覆盖数）。"""
    counts = {
        item["node_id"]: item["count"]
        for item in entries_summary.get("by_top_node", [])
    }
    result: list[dict] = []
    for node in nodes:
        if node.parent_id is not None:
            continue
        description = (node.description or "").strip()
        if len(description) > NODE_DESCRIPTION_LIMIT:
            description = f"{description[:NODE_DESCRIPTION_LIMIT]}…"
        result.append(
            {
                "node_id": node.id,
                "name": node.name,
                "description": description or None,
                "entry_count": counts.get(node.id, 0),
            }
        )
    return result[:MAX_TOP_LEVEL_NODES]


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


async def schedule_refresh(
    db: AsyncSession,
    project_id: int,
    reason: str | None = None,
) -> ProjectContext:
    """安排一次防抖刷新，遵守最小生成间隔；reason 记录最近一次触发来源。"""
    settings = get_settings()
    context = await get_or_create_context(db, project_id)
    if reason:
        context.last_update_reason = reason
    now = datetime.now(UTC)
    due = now + timedelta(seconds=settings.context_refresh_debounce_seconds)
    if context.generated_at is not None:
        generated = context.generated_at
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=UTC)
        min_due = generated + timedelta(
            seconds=settings.context_min_interval_seconds
        )
        due = max(due, min_due)
    context.refresh_due_at = due
    return context


async def refresh_project_context(
    db: AsyncSession,
    project_id: int,
    reason: str | None = None,
) -> ProjectContext:
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
    entries_summary = await _build_entries_summary(db, project_id, list(nodes))
    top_level_nodes = _build_top_level_nodes(list(nodes), entries_summary)

    try:
        draft, meta = await get_project_context_generator().generate(
            db,
            project,
            list(nodes),
            entries_summary,
            top_level_nodes,
            corrections,
        )
        context.project_summary = draft.project_summary
        context.current_focus = draft.current_focus
        # 目录主题保持确定性：始终取顶级节点名称，不依赖模型输出
        topic_names = (
            [item["name"] for item in top_level_nodes]
            if top_level_nodes
            else draft.directory_topics
        )
        context.directory_topics = json.dumps(topic_names, ensure_ascii=False)
        context.entries_summary = json.dumps(entries_summary, ensure_ascii=False)
        context.recent_themes = json.dumps(draft.recent_themes[:5], ensure_ascii=False)
        context.provider = meta.provider
        context.model = meta.model
        context.is_fallback = meta.is_fallback
        if meta.is_fallback:
            logger.warning(
                "项目上下文降级生成：provider=%s，model=%s",
                meta.provider,
                meta.model,
            )
        context.version = (context.version or 0) + 1
        if reason:
            context.last_update_reason = reason
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
    await schedule_refresh(db, project_id, "user_correction")
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
        version=context.version,
        last_update_reason=context.last_update_reason,
        entries_summary=_parse_entries_summary(context.entries_summary),
        recent_themes=_parse_recent_themes(context.recent_themes),
        provider=context.provider,
        model=context.model,
        is_fallback=context.is_fallback,
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
