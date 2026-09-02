"""StructuredQueryPlan v1 的确定性只读查询工具。

所有范围谓词都来自 RunToolContext，并在每个 SQL 查询中重复应用。工具只读取
正式 Entry 与其现有归属/来源关系，不接触 Candidate、Extraction、Draft 或写入链路。
"""

from time import perf_counter
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import Select, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.semantic import run_semantic_agent
from app.core.config import get_settings
from app.models import Entry, Project
from app.models.knowledge_agent import (
    PURPOSE_RERANK,
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    TOOL_EMPTY,
    TOOL_LIMITED,
)
from app.services.entry import entry_eager_options
from app.services.knowledge_agent.entry_search import _assemble_items
from app.services.knowledge_agent.observability import StageMeta, record_model_invocation
from app.services.knowledge_agent.read_tools import (
    ReadToolExecution,
    ReadToolParams,
    ReadToolSpec,
    completed_execution,
)
from app.services.knowledge_agent.structured_query import (
    NormalizedEntrySetSpec,
    NormalizedEntrySort,
)
from app.services.knowledge_agent.tools import RunToolContext
from app.services.vector_search import hybrid_recall_by_query_with_meta

STRUCTURED_QUERY_TOOL_VERSION = "v1"


class QueryEntriesParams(ReadToolParams):
    """query_entries v1 参数；不包含任何授权范围字段。"""

    entry_set: NormalizedEntrySetSpec
    limit: int = Field(ge=1, le=100)
    sort: NormalizedEntrySort


class AggregateEntriesParams(ReadToolParams):
    """aggregate_entries v1 参数；聚合直接针对共享集合执行。"""

    entry_set: NormalizedEntrySetSpec
    operation: Literal["count", "group_count"]
    group_by: Literal["main_type", "info_nature", "updated_month"] | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> "AggregateEntriesParams":
        """count 不接受分组字段，group_count 必须指定白名单字段。"""
        if self.operation == "count" and self.group_by is not None:
            raise ValueError("count 不接受 group_by")
        if self.operation == "group_count" and self.group_by is None:
            raise ValueError("group_count 必须指定 group_by")
        return self


def _apply_entry_set_filters(
    stmt: Select,
    entry_set: NormalizedEntrySetSpec,
) -> Select:
    """只应用跨 SQLite/MySQL 8 语义一致的白名单结构化条件。"""
    if entry_set.main_types:
        stmt = stmt.where(Entry.main_type.in_(entry_set.main_types))
    if entry_set.info_natures:
        concrete = [
            value for value in entry_set.info_natures if value != "unspecified"
        ]
        predicates = []
        if concrete:
            predicates.append(Entry.info_nature.in_(concrete))
        if "unspecified" in entry_set.info_natures:
            predicates.append(Entry.info_nature.is_(None))
        stmt = stmt.where(or_(*predicates))
    if entry_set.updated_at is not None:
        if entry_set.updated_at.from_ is not None:
            stmt = stmt.where(Entry.updated_at >= entry_set.updated_at.from_)
        if entry_set.updated_at.to is not None:
            stmt = stmt.where(Entry.updated_at < entry_set.updated_at.to)
    return stmt


def structured_entry_select(
    ctx: RunToolContext,
    entry_set: NormalizedEntrySetSpec,
    sort: NormalizedEntrySort,
) -> Select:
    """构造带可信范围、结构化过滤和稳定 tie-breaker 的 Entry 查询。"""
    if entry_set.semantic_query is not None:
        raise ValueError("纯结构化查询不能执行 semantic_query")
    if sort.field == "relevance":
        raise ValueError("纯结构化查询不能按 relevance 排序")
    stmt = (
        select(Entry)
        .join(Project, Entry.project_id == Project.id)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Project.workspace_id == ctx.workspace_id)
    )
    if ctx.project_id is not None:
        stmt = stmt.where(Entry.project_id == ctx.project_id)
    stmt = _apply_entry_set_filters(stmt, entry_set)
    sort_column = Entry.updated_at if sort.field == "updated_at" else Entry.created_at
    order = desc if sort.direction == "desc" else asc
    return stmt.order_by(order(sort_column), order(Entry.id))


def structured_scope_select(
    ctx: RunToolContext,
    entry_set: NormalizedEntrySetSpec,
) -> Select:
    """构造可信范围 + 结构化条件查询，供语义候选池与聚合共享。"""
    stmt = (
        select(Entry)
        .join(Project, Entry.project_id == Project.id)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Project.workspace_id == ctx.workspace_id)
    )
    if ctx.project_id is not None:
        stmt = stmt.where(Entry.project_id == ctx.project_id)
    return _apply_entry_set_filters(stmt, entry_set)


def _aggregate_scope_stmt(
    ctx: RunToolContext,
    entry_set: NormalizedEntrySetSpec,
) -> Select:
    """构造聚合共享集合范围；语义集合只能使用服务端预先固化的候选 id。"""
    stmt = (
        select(Entry.id)
        .join(Project, Entry.project_id == Project.id)
        .where(Project.workspace_id == ctx.workspace_id)
    )
    if ctx.project_id is not None:
        stmt = stmt.where(Entry.project_id == ctx.project_id)
    stmt = _apply_entry_set_filters(stmt, entry_set)
    if entry_set.semantic_query is not None:
        if ctx.structured_query_entry_ids is None:
            raise ValueError("semantic_query 共享集合尚未由服务端准备")
        stmt = stmt.where(Entry.id.in_(ctx.structured_query_entry_ids))
    return stmt


def _updated_month_expression(dialect_name: str):
    """为 SQLite/MySQL 8 生成一致的 UTC YYYY-MM 月桶表达式。"""
    if dialect_name == "mysql":
        return func.date_format(Entry.updated_at, "%Y-%m")
    if dialect_name == "sqlite":
        return func.strftime("%Y-%m", Entry.updated_at)
    # 测试/未来方言的保守表达；生产范围当前只支持 SQLite/MySQL 8
    return func.to_char(Entry.updated_at, "YYYY-MM")


async def aggregate_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: AggregateEntriesParams,
) -> ReadToolExecution:
    """直接对共享集合执行 count/group_count，不依赖任何列表输出。"""
    settings = get_settings()
    if (
        params.entry_set.semantic_query is not None
        and ctx.structured_query_entry_ids is None
    ):
        await prepare_semantic_entry_set(db, ctx, params.entry_set)
    base_ids = _aggregate_scope_stmt(ctx, params.entry_set).subquery()
    semantic = params.entry_set.semantic_query is not None
    base_completeness = (
        RESULT_COMPLETENESS_LIMITED if semantic else RESULT_COMPLETENESS_COMPLETE
    )
    if params.operation == "count":
        value = int(
            (
                await db.execute(select(func.count()).select_from(base_ids))
            ).scalar_one()
        )
        status = TOOL_EMPTY if value == 0 else (
            TOOL_LIMITED if semantic else "completed"
        )
        return ReadToolExecution(
            status=status,
            payload={"value": value},
            completeness=base_completeness,
            audit_summary={
                "operation": "count",
                "value": value,
                "status": status,
                "semantic": semantic,
                "completeness": base_completeness,
            },
        )

    dialect_name = db.bind.dialect.name if db.bind is not None else "sqlite"
    if params.group_by == "main_type":
        bucket_expr = Entry.main_type
    elif params.group_by == "info_nature":
        bucket_expr = func.coalesce(Entry.info_nature, "unspecified")
    else:
        bucket_expr = _updated_month_expression(dialect_name)
    stmt = (
        select(bucket_expr.label("bucket"), func.count(Entry.id).label("count"))
        .where(Entry.id.in_(select(base_ids.c.id)))
        .group_by(bucket_expr)
        .order_by(asc(bucket_expr))
        .limit(settings.knowledge_agent_structured_query_bucket_limit + 1)
    )
    rows = list((await db.execute(stmt)).all())
    truncated = len(rows) > settings.knowledge_agent_structured_query_bucket_limit
    rows = rows[: settings.knowledge_agent_structured_query_bucket_limit]
    buckets = [
        {"key": str(row.bucket), "count": int(row.count)}
        for row in rows
        if row.bucket is not None
    ]
    completeness = (
        RESULT_COMPLETENESS_LIMITED if semantic or truncated else base_completeness
    )
    if not buckets:
        status = TOOL_EMPTY
    elif semantic or truncated:
        status = TOOL_LIMITED
    else:
        status = "completed"
    return ReadToolExecution(
        status=status,
        payload={
            "group_by": params.group_by,
            "buckets": buckets,
            "truncated": truncated,
        },
        completeness=completeness,
        audit_summary={
            "operation": "group_count",
            "group_by": params.group_by,
            "bucket_count": len(buckets),
            "buckets": buckets,
            "status": status,
            "semantic": semantic,
            "truncated": truncated,
            "completeness": completeness,
        },
    )


def _sort_semantic_candidates(
    entries: list[Entry],
    sort: NormalizedEntrySort,
) -> list[Entry]:
    """对已受控语义候选执行稳定排序；relevance 保持重排顺序。"""
    if sort.field == "relevance":
        return entries
    attribute = sort.field
    return sorted(
        entries,
        key=lambda entry: (getattr(entry, attribute), entry.id),
        reverse=sort.direction == "desc",
    )


async def semantic_query_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: QueryEntriesParams,
) -> ReadToolExecution:
    """在结构化合法子集上复用混合召回与重排，完整性永不标记 complete。"""
    settings = get_settings()
    query = params.entry_set.semantic_query
    if query is None:
        raise ValueError("semantic_query 不能为空")
    ranked = await prepare_semantic_entry_set(db, ctx, params.entry_set)
    ordered = _sort_semantic_candidates(ranked, params.sort)
    truncated = (
        len(ranked)
        >= settings.knowledge_agent_structured_query_semantic_candidate_limit
        or len(ordered) > params.limit
    )
    selected = ordered[: params.limit]
    items, unavailable = await _assemble_items(
        db,
        ctx,
        selected,
        query,
        excerpt_chars=settings.knowledge_agent_result_excerpt_chars,
        node_path_chars=settings.knowledge_agent_result_node_path_chars,
        match_hint_chars=settings.knowledge_agent_result_match_hint_chars,
    )
    for item in items:
        ctx.discovered_entry_ids.add(item.entry_id)
    if unavailable:
        completeness = RESULT_COMPLETENESS_UNKNOWN
        status = "partial"
        error = "部分语义候选在快照装配时不可用"
    else:
        completeness = RESULT_COMPLETENESS_LIMITED
        status = TOOL_LIMITED if items else TOOL_EMPTY
        error = None
    return ReadToolExecution(
        status=status,
        payload={
            "items": [item.model_dump(mode="json") for item in items],
            "returned_count": len(items),
            "has_more": truncated,
            "semantic_candidate_count": len(ranked),
        },
        completeness=completeness,
        audit_summary={
            "returned_count": len(items),
            "entry_ids": [item.entry_id for item in items],
            "semantic_candidate_count": len(ranked),
            "status": status,
            "semantic": True,
            "truncated": truncated,
            "has_more": truncated,
            "unavailable_count": len(unavailable),
            "completeness": completeness,
        },
        error=error,
    )


async def prepare_semantic_entry_set(
    db: AsyncSession,
    ctx: RunToolContext,
    entry_set: NormalizedEntrySetSpec,
) -> list[Entry]:
    """准备一次共享语义集合；同一 ctx 后续输出只复用，不再次召回/重排。"""
    settings = get_settings()
    query = entry_set.semantic_query
    if query is None:
        raise ValueError("semantic_query 不能为空")
    if ctx.structured_query_entry_ids is not None:
        rows = list(
            (
                await db.execute(
                    structured_scope_select(ctx, entry_set).where(
                        Entry.id.in_(ctx.structured_query_entry_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {entry.id: entry for entry in rows}
        return [
            by_id[entry_id]
            for entry_id in (ctx.structured_query_entry_order or [])
            if entry_id in by_id
        ]
    scope_rows = list(
        (await db.execute(structured_scope_select(ctx, entry_set)))
        .scalars()
        .all()
    )
    if not scope_rows:
        ctx.structured_query_entry_ids = set()
        ctx.structured_query_entry_order = []
        return []
    candidates, _cosine, embedding_meta = await hybrid_recall_by_query_with_meta(
        db,
        ctx.workspace_id,
        scope_rows,
        query,
        settings.knowledge_agent_structured_query_semantic_candidate_limit,
    )
    if embedding_meta is not None:
        await record_model_invocation(
            db,
            run_id=ctx.run_id,
            meta=embedding_meta,
            prompt_version=STRUCTURED_QUERY_TOOL_VERSION,
        )
    rerank_meta = None
    ranked: list[Entry] = []
    if candidates:
        started = perf_counter()
        draft, provider, model, is_fallback, error = await run_semantic_agent(
            db,
            ctx.workspace_id,
            query,
            candidates,
            strict=True,
        )
        rerank_meta = StageMeta(
            purpose=PURPOSE_RERANK,
            provider=provider,
            model=model,
            is_fallback=is_fallback,
            error=error,
            duration_ms=int((perf_counter() - started) * 1000),
        )
        await record_model_invocation(
            db,
            run_id=ctx.run_id,
            meta=rerank_meta,
            prompt_version=STRUCTURED_QUERY_TOOL_VERSION,
        )
        by_id = {entry.id: entry for entry in candidates}
        seen: set[int] = set()
        for item in draft.results:
            entry = by_id.get(item.entry_id)
            if entry is None or entry.id in seen:
                continue
            ranked.append(entry)
            seen.add(entry.id)
        if not ranked and (is_fallback or error):
            ranked = list(candidates)
    ctx.structured_query_entry_ids = {entry.id for entry in ranked}
    ctx.structured_query_entry_order = [entry.id for entry in ranked]
    return ranked


async def query_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: QueryEntriesParams,
) -> ReadToolExecution:
    """确定性返回有界正式 Entry 快照；列表截断只影响 entries 完整性。"""
    if params.entry_set.semantic_query is not None:
        return await semantic_query_entries_handler(db, ctx, params)
    settings = get_settings()
    stmt = structured_entry_select(ctx, params.entry_set, params.sort).limit(
        params.limit + 1
    )
    rows = list((await db.execute(stmt)).scalars().all())
    truncated = len(rows) > params.limit
    selected = rows[: params.limit]
    items, unavailable = await _assemble_items(
        db,
        ctx,
        selected,
        params.entry_set.semantic_query or "",
        excerpt_chars=settings.knowledge_agent_result_excerpt_chars,
        node_path_chars=settings.knowledge_agent_result_node_path_chars,
        match_hint_chars=settings.knowledge_agent_result_match_hint_chars,
    )
    if unavailable:
        return ReadToolExecution(
            status="partial",
            payload={
                "items": [item.model_dump(mode="json") for item in items],
                "returned_count": len(items),
                "has_more": truncated,
                "unavailable_count": len(unavailable),
            },
            completeness="unknown",
            audit_summary={
                "returned_count": len(items),
                "unavailable_count": len(unavailable),
                "completeness": "unknown",
            },
            error="部分 Entry 在快照装配时不可用",
        )
    if not items:
        return ReadToolExecution(
            status=TOOL_EMPTY,
            payload={"items": [], "returned_count": 0, "has_more": False},
            completeness=RESULT_COMPLETENESS_COMPLETE,
            audit_summary={
                "returned_count": 0,
                "entry_ids": [],
                "status": TOOL_EMPTY,
                "has_more": False,
                "completeness": RESULT_COMPLETENESS_COMPLETE,
            },
        )
    completeness = (
        RESULT_COMPLETENESS_LIMITED
        if truncated
        else RESULT_COMPLETENESS_COMPLETE
    )
    if truncated:
        return ReadToolExecution(
            status=TOOL_LIMITED,
            payload={
                "items": [item.model_dump(mode="json") for item in items],
                "returned_count": len(items),
                "has_more": True,
            },
            completeness=completeness,
            audit_summary={
                "returned_count": len(items),
                "entry_ids": [item.entry_id for item in items],
                "status": TOOL_LIMITED,
                "has_more": True,
                "completeness": completeness,
            },
        )
    return completed_execution(
        {
            "items": [item.model_dump(mode="json") for item in items],
            "returned_count": len(items),
            "has_more": False,
        },
        completeness=completeness,
        audit_summary={
            "returned_count": len(items),
            "entry_ids": [item.entry_id for item in items],
            "status": "completed",
            "has_more": False,
            "completeness": completeness,
        },
    )


async def restore_query_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: QueryEntriesParams,
    summary: dict,
) -> ReadToolExecution | None:
    """按已提交有序 Entry id 重建当前快照；对象变化显式降为 partial。"""
    entry_ids = summary.get("entry_ids")
    if not isinstance(entry_ids, list) or not all(
        isinstance(entry_id, int) for entry_id in entry_ids
    ):
        return None
    rows = list(
        (
            await db.execute(
                structured_scope_select(ctx, params.entry_set).where(
                    Entry.id.in_(entry_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {entry.id: entry for entry in rows}
    ordered = [by_id[entry_id] for entry_id in entry_ids if entry_id in by_id]
    settings = get_settings()
    items, unavailable = await _assemble_items(
        db,
        ctx,
        ordered,
        params.entry_set.semantic_query or "",
        excerpt_chars=settings.knowledge_agent_result_excerpt_chars,
        node_path_chars=settings.knowledge_agent_result_node_path_chars,
        match_hint_chars=settings.knowledge_agent_result_match_hint_chars,
    )
    missing = len(entry_ids) - len(items) + len(unavailable)
    if missing:
        status = "partial"
        completeness = RESULT_COMPLETENESS_UNKNOWN
        error = "恢复时部分 Entry 已删除或移出 Run 范围"
    else:
        status = str(summary.get("status") or "completed")
        completeness = str(
            summary.get("completeness") or RESULT_COMPLETENESS_UNKNOWN
        )
        error = None
    return ReadToolExecution(
        status=status,
        payload={
            "items": [item.model_dump(mode="json") for item in items],
            "returned_count": len(items),
            "has_more": bool(summary.get("has_more", False)),
        },
        completeness=completeness,
        audit_summary=summary,
        error=error,
    )


async def restore_aggregate_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: AggregateEntriesParams,
    summary: dict,
) -> ReadToolExecution | None:
    """复用已提交的有界 count/桶摘要，不重新扫描共享集合。"""
    del db, ctx
    completeness = summary.get("completeness")
    status = summary.get("status")
    if not isinstance(completeness, str) or not isinstance(status, str):
        return None
    if params.operation == "count":
        value = summary.get("value")
        if not isinstance(value, int):
            return None
        payload = {"value": value}
    else:
        buckets = summary.get("buckets")
        if not isinstance(buckets, list):
            return None
        payload = {
            "group_by": params.group_by,
            "buckets": buckets,
            "truncated": bool(summary.get("truncated", False)),
        }
    return ReadToolExecution(
        status=status,
        payload=payload,
        completeness=completeness,
        audit_summary=summary,
    )


STRUCTURED_QUERY_TOOL_REGISTRY: dict[str, ReadToolSpec] = {
    "query_entries": ReadToolSpec(
        name="query_entries",
        version=STRUCTURED_QUERY_TOOL_VERSION,
        params_model=QueryEntriesParams,
        handler=query_entries_handler,
        restore_handler=restore_query_entries_handler,
    ),
    "aggregate_entries": ReadToolSpec(
        name="aggregate_entries",
        version=STRUCTURED_QUERY_TOOL_VERSION,
        params_model=AggregateEntriesParams,
        handler=aggregate_entries_handler,
        restore_handler=restore_aggregate_entries_handler,
    ),
}
