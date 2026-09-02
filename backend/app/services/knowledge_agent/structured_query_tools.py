"""StructuredQueryPlan v1 的确定性只读查询工具。

所有范围谓词都来自 RunToolContext，并在每个 SQL 查询中重复应用。工具只读取
正式 Entry 与其现有归属/来源关系，不接触 Candidate、Extraction、Draft 或写入链路。
"""

from pydantic import Field
from sqlalchemy import Select, asc, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models import Entry, Project
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    TOOL_EMPTY,
    TOOL_LIMITED,
)
from app.services.entry import entry_eager_options
from app.services.knowledge_agent.entry_search import _assemble_items
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

STRUCTURED_QUERY_TOOL_VERSION = "v1"


class QueryEntriesParams(ReadToolParams):
    """query_entries v1 参数；不包含任何授权范围字段。"""

    entry_set: NormalizedEntrySetSpec
    limit: int = Field(ge=1, le=100)
    sort: NormalizedEntrySort


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


async def query_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: QueryEntriesParams,
) -> ReadToolExecution:
    """确定性返回有界正式 Entry 快照；列表截断只影响 entries 完整性。"""
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
            "has_more": False,
            "completeness": completeness,
        },
    )


STRUCTURED_QUERY_TOOL_REGISTRY: dict[str, ReadToolSpec] = {
    "query_entries": ReadToolSpec(
        name="query_entries",
        version=STRUCTURED_QUERY_TOOL_VERSION,
        params_model=QueryEntriesParams,
        handler=query_entries_handler,
    )
}
