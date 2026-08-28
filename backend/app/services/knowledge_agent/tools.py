"""知识 Agent 可信只读工具：服务端注入范围并受已发现对象集合约束。"""

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.semantic import run_semantic_agent
from app.models import Attachment, Entry, Project, Source
from app.models.knowledge_agent import (
    PURPOSE_RERANK,
    SCOPE_PROJECT,
    TOOL_DENIED,
    TOOL_EMPTY,
    TOOL_OK,
    TOOL_PARTIAL,
    TOOL_UNAVAILABLE,
)
from app.services.entry import entry_eager_options
from app.services.knowledge_agent.evidence import (
    available_attachment_text,
    build_node_path_map,
    create_answer_evidence,
    locate_verified_quote,
)
from app.services.knowledge_agent.observability import (
    StageMeta,
    next_tool_sequence,
    record_tool_call,
)
from app.services.vector_search import hybrid_recall_by_query_with_meta

logger = logging.getLogger(__name__)


@dataclass
class RunToolContext:
    """Run 的不可信来源与可信范围：模型无法自行指定 Workspace/项目。"""

    run_id: int
    workspace_id: int
    owner_user_id: int
    scope_type: str
    project_id: int | None
    project_name: str | None
    discovered_entry_ids: set[int] = field(default_factory=set)


class SearchResultItem(BaseModel):
    """搜索命中的正式 Entry 摘要（项目归属 + 目录定位）。"""

    entry_id: int
    title: str
    project_name: str
    node_path: str
    summary: str
    source_count: int


class SearchToolOutput(BaseModel):
    """搜索工具输出与阶段元数据。"""

    items: list[SearchResultItem] = []
    embedding_meta: dict | None = None
    rerank_meta: dict | None = None


class ReadEntryItem(BaseModel):
    """已发现 Entry 的完整正式内容与归属、来源关系。"""

    entry_id: int
    title: str
    content: str
    project_name: str
    node_path: str
    sources: list[dict] = []


class ReadEntriesOutput(BaseModel):
    """批量读取结果：成功对象与拒绝对象分离。"""

    items: list[ReadEntryItem] = []
    denied_entry_ids: list[int] = []
    unavailable_entry_ids: list[int] = []


class EvidenceReadItem(BaseModel):
    """单条 Source 证据读取结果。"""

    entry_id: int
    source_id: int
    source_title: str = ""
    attachment_id: int | None = None
    evidence_handle: str | None = None
    quote: str | None = None
    citable: bool = False
    status: str = TOOL_UNAVAILABLE
    reason: str | None = None


class EvidenceReadOutput(BaseModel):
    """Source 证据读取输出：只有核验通过的片段成为可引用 Evidence。"""

    items: list[EvidenceReadItem] = []


async def _load_scope_entries(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None,
) -> list[Entry]:
    """加载 Run 固化范围内的全部已确认正式 Entry。"""
    stmt = (
        select(Entry)
        .join(Project, Entry.project_id == Project.id)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Project.workspace_id == workspace_id)
    )
    if project_id is not None:
        stmt = stmt.where(Entry.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


def _ordered_entries(candidates: list[Entry], draft, limit: int) -> list[Entry]:
    """按语义重排结果取前 limit 条；重排缺失时保持召回顺序。"""
    by_id = {entry.id: entry for entry in candidates}
    ordered: list[Entry] = []
    seen: set[int] = set()
    for item in draft.results:
        entry = by_id.get(item.entry_id)
        if entry is not None and entry.id not in seen:
            ordered.append(entry)
            seen.add(entry.id)
        if len(ordered) >= limit:
            break
    for entry in candidates:
        if entry.id not in seen:
            ordered.append(entry)
            seen.add(entry.id)
        if len(ordered) >= limit:
            break
    return ordered


def _entry_project_name(entry: Entry) -> str:
    return entry.project.name if entry.project else "未知项目"


async def _node_paths(
    db: AsyncSession,
    project_id: int,
) -> dict[int, str]:
    """读取项目目录路径映射；项目已删除时返回空。"""
    if project_id is None:
        return {}
    return await build_node_path_map(db, project_id)


async def search_confirmed_knowledge(
    db: AsyncSession,
    ctx: RunToolContext,
    query: str,
    *,
    recall_limit: int,
    context_limit: int,
) -> SearchToolOutput:
    """在 Run 范围内混合召回正式 Entry，只返回已确认知识并携带项目归属。"""
    text = query.strip()
    if not text:
        return SearchToolOutput()
    entries = await _load_scope_entries(db, ctx.workspace_id, ctx.project_id)
    if not entries:
        return SearchToolOutput()

    candidates, _cosine, embedding_meta = await hybrid_recall_by_query_with_meta(
        db,
        ctx.workspace_id,
        entries,
        text,
        recall_limit,
    )
    rerank_meta: StageMeta | None = None
    if candidates:
        started = perf_counter()
        draft, provider, model, is_fallback, error = await run_semantic_agent(
            db,
            ctx.workspace_id,
            text,
            candidates,
        )
        rerank_meta = StageMeta(
            purpose=PURPOSE_RERANK,
            provider=provider,
            model=model,
            is_fallback=is_fallback,
            error=error,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        top_entries = _ordered_entries(candidates, draft, context_limit)
    else:
        top_entries = []

    project_ids = {entry.project_id for entry in top_entries}
    path_by_node: dict[int, str] = {}
    for project_id in project_ids:
        if project_id is not None:
            path_by_node.update(await _node_paths(db, project_id))

    items: list[SearchResultItem] = []
    for entry in top_entries:
        items.append(
            SearchResultItem(
                entry_id=entry.id,
                title=entry.title,
                project_name=_entry_project_name(entry),
                node_path=path_by_node.get(entry.node_id, ""),
                summary=entry.content[:200],
                source_count=len(entry.evidences),
            )
        )
        ctx.discovered_entry_ids.add(entry.id)
    return SearchToolOutput(
        items=items,
        embedding_meta=embedding_meta.__dict__ if embedding_meta else None,
        rerank_meta=rerank_meta.__dict__ if rerank_meta else None,
    )


async def read_entries(
    db: AsyncSession,
    ctx: RunToolContext,
    entry_ids: list[int],
) -> ReadEntriesOutput:
    """批量读取已发现且仍在范围内的 Entry 完整内容；未发现或越权对象拒绝。"""
    unique = list(dict.fromkeys(entry_ids))
    denied: list[int] = []
    unavailable: list[int] = []
    discovered = set(unique) & ctx.discovered_entry_ids
    for entry_id in unique:
        if entry_id not in ctx.discovered_entry_ids:
            denied.append(entry_id)

    if not discovered:
        return ReadEntriesOutput(denied_entry_ids=denied, unavailable_entry_ids=unavailable)
    rows = (
        await db.execute(
            select(Entry)
            .join(Project, Entry.project_id == Project.id)
            .options(*entry_eager_options(), selectinload(Entry.project))
            .where(
                Entry.id.in_(discovered),
                Project.workspace_id == ctx.workspace_id,
            )
        )
    ).scalars().all()
    by_id = {entry.id: entry for entry in rows}

    path_by_node: dict[int, str] = {}
    for entry in rows:
        if entry.project_id is not None:
            path_by_node.update(await _node_paths(db, entry.project_id))

    items: list[ReadEntryItem] = []
    for entry_id in unique:
        if entry_id in denied:
            continue
        entry = by_id.get(entry_id)
        if entry is None:
            unavailable.append(entry_id)
            continue
        # 复验范围：项目范围 Run 只能读该项目对象
        if ctx.scope_type == SCOPE_PROJECT and entry.project_id != ctx.project_id:
            denied.append(entry_id)
            continue
        items.append(
            ReadEntryItem(
                entry_id=entry.id,
                title=entry.title,
                content=entry.content,
                project_name=_entry_project_name(entry),
                node_path=path_by_node.get(entry.node_id, ""),
                sources=[
                    {
                        "source_id": item.source_id,
                        "source_title": item.source.title if item.source else "已删除来源",
                        "attachment_id": item.attachment_id,
                        "quote": item.quote or "",
                    }
                    for item in entry.evidences
                ],
            )
        )
    return ReadEntriesOutput(
        items=items,
        denied_entry_ids=denied,
        unavailable_entry_ids=unavailable,
    )


async def read_source_evidence(
    db: AsyncSession,
    ctx: RunToolContext,
    entry_id: int,
    source_ids: list[int],
) -> EvidenceReadOutput:
    """读取已发现 Entry 的真实 Source/Attachment 并核验原文，生成可引用 Evidence。"""
    if entry_id not in ctx.discovered_entry_ids:
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title="",
                    citable=False,
                    status=TOOL_DENIED,
                    reason="Entry 未被本轮发现",
                )
                for source_id in source_ids
            ]
        )

    entry = (
        await db.execute(
            select(Entry)
            .join(Project, Entry.project_id == Project.id)
            .options(*entry_eager_options(), selectinload(Entry.project))
            .where(
                Entry.id == entry_id,
                Project.workspace_id == ctx.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title="",
                    citable=False,
                    status=TOOL_UNAVAILABLE,
                    reason="Entry 已不存在",
                )
                for source_id in source_ids
            ]
        )
    if ctx.scope_type == SCOPE_PROJECT and entry.project_id != ctx.project_id:
        return EvidenceReadOutput(
            items=[
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title="",
                    citable=False,
                    status=TOOL_DENIED,
                    reason="Entry 已移出 Run 范围",
                )
                for source_id in source_ids
            ]
        )

    evidence_by_source = {item.source_id: item for item in entry.evidences}
    allowed_source_ids = set(evidence_by_source)
    source_rows = (
        await db.execute(
            select(Source)
            .options(selectinload(Source.attachments))
            .where(Source.id.in_(list(set(source_ids) & allowed_source_ids)))
        )
    ).scalars().all()
    source_by_id = {source.id: source for source in source_rows}
    path_map = await _node_paths(db, entry.project_id)
    project_name = _entry_project_name(entry)
    node_path = path_map.get(entry.node_id, "")

    items: list[EvidenceReadItem] = []
    for source_id in source_ids:
        if source_id not in allowed_source_ids:
            items.append(
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title="",
                    citable=False,
                    status=TOOL_DENIED,
                    reason="Source 与 Entry 无真实关联",
                )
            )
            continue
        source = source_by_id.get(source_id)
        if source is None:
            items.append(
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title=source.title,
                    citable=False,
                    status=TOOL_UNAVAILABLE,
                    reason="Source 已删除",
                )
            )
            continue
        entry_evidence = evidence_by_source[source_id]
        attachment = None
        if entry_evidence.attachment_id is not None:
            attachment = await db.get(Attachment, entry_evidence.attachment_id)
        if attachment is None and source.attachments:
            attachment = source.attachments[0]
        text = available_attachment_text(attachment)
        if not text:
            items.append(
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    citable=False,
                    status=TOOL_UNAVAILABLE,
                    reason="Source 无可读 Attachment 文本",
                )
            )
            continue
        quote = entry_evidence.quote or ""
        verified = locate_verified_quote(text, quote) if quote else None
        if verified is None:
            items.append(
                EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title=source.title,
                    attachment_id=attachment.id,
                    citable=False,
                    status=TOOL_UNAVAILABLE,
                    reason="候选片段无法在原文中核验",
                )
            )
            continue
        row = await create_answer_evidence(
            db,
            run_id=ctx.run_id,
            entry=entry,
            project_name=project_name,
            node_path=node_path,
            evidence=entry_evidence,
            attachment=attachment,
            verified=verified,
        )
        items.append(
            EvidenceReadItem(
                    entry_id=entry_id,
                    source_id=source_id,
                    source_title=source.title,
                    attachment_id=attachment.id,
                    evidence_handle=row.handle,
                quote=row.quote,
                citable=True,
                status=TOOL_OK,
            )
        )
    return EvidenceReadOutput(items=items)


async def record_tool_result(
    db: AsyncSession,
    *,
    run_id: int,
    tool_name: str,
    params: dict,
    result: dict,
    duration_ms: int,
) -> None:
    """统一记录工具调用（参数与结果只保存摘要，不复制整份内容）。"""
    sequence = await next_tool_sequence(db, run_id)
    denied_count = int(result.get("denied", 0))
    unavailable_count = int(result.get("unavailable", 0))
    total = int(result.get("total", 0))
    if denied_count or unavailable_count:
        status = TOOL_PARTIAL if total else TOOL_DENIED
        error = "部分对象越权或不可用"
    elif total == 0:
        status = TOOL_EMPTY
        error = None
    else:
        status = TOOL_OK
        error = None
    await record_tool_call(
        db,
        run_id=run_id,
        sequence=sequence,
        tool_name=tool_name,
        status=status,
        params_summary=json.dumps(params, ensure_ascii=False)[:500],
        result_summary=json.dumps(result, ensure_ascii=False)[:500],
        error=error,
        duration_ms=duration_ms,
    )
