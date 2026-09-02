"""既有知识搜索、Entry 与 Evidence 读取的统一只读工具薄适配器。

适配器不改变已发现集合和 Evidence 原文核验边界；它只把既有返回映射为统一
状态与最小审计摘要。调用参数仍由应用控制，dispatcher 继续注入 Run 范围。
"""

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    TOOL_COMPLETED,
    TOOL_DENIED,
    TOOL_EMPTY,
    TOOL_PARTIAL,
)
from app.services.knowledge_agent.read_tools import (
    ReadToolExecution,
    ReadToolParams,
    ReadToolSpec,
)
from app.services.knowledge_agent.structured_query_tools import (
    STRUCTURED_QUERY_TOOL_REGISTRY,
)
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    search_confirmed_knowledge,
)

READ_TOOL_VERSION = "v1"


class SearchKnowledgeParams(ReadToolParams):
    query: str = Field(min_length=1, max_length=500)


class ReadEntriesParams(ReadToolParams):
    entry_ids: list[int] = Field(min_length=1, max_length=30)


class ReadEvidenceParams(ReadToolParams):
    entry_id: int
    source_ids: list[int] = Field(min_length=1, max_length=30)


async def search_knowledge_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: SearchKnowledgeParams,
) -> ReadToolExecution:
    """复用既有受控搜索；语义召回不能声称完整全集。"""
    settings = get_settings()
    output = await search_confirmed_knowledge(
        db,
        ctx,
        params.query,
        recall_limit=settings.knowledge_agent_recall_limit,
        context_limit=settings.knowledge_agent_context_limit,
    )
    status = TOOL_COMPLETED if output.items else TOOL_EMPTY
    return ReadToolExecution(
        status=status,
        payload=output.model_dump(mode="json"),
        completeness=RESULT_COMPLETENESS_LIMITED,
        audit_summary={
            "returned_count": len(output.items),
            "completeness": RESULT_COMPLETENESS_LIMITED,
        },
    )


async def read_entries_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: ReadEntriesParams,
) -> ReadToolExecution:
    """复用已发现集合门禁；越权 id 不因适配器获得读取能力。"""
    output = await read_entries(db, ctx, params.entry_ids)
    affected = len(output.denied_entry_ids) + len(output.unavailable_entry_ids)
    if affected and output.items:
        status = TOOL_PARTIAL
    elif affected:
        status = TOOL_DENIED
    elif output.items:
        status = TOOL_COMPLETED
    else:
        status = TOOL_EMPTY
    return ReadToolExecution(
        status=status,
        payload=output.model_dump(mode="json"),
        completeness=(
            RESULT_COMPLETENESS_UNKNOWN if affected else RESULT_COMPLETENESS_LIMITED
        ),
        audit_summary={
            "returned_count": len(output.items),
            "denied_count": len(output.denied_entry_ids),
            "unavailable_count": len(output.unavailable_entry_ids),
        },
        error="部分 Entry 越权或不可用" if affected else None,
    )


async def read_evidence_handler(
    db: AsyncSession,
    ctx: RunToolContext,
    params: ReadEvidenceParams,
) -> ReadToolExecution:
    """复用真实 Source/Attachment 核验；审计不保存 quote。"""
    output = await read_source_evidence(
        db,
        ctx,
        params.entry_id,
        params.source_ids,
    )
    citable = sum(1 for item in output.items if item.citable)
    denied = sum(1 for item in output.items if item.status == TOOL_DENIED)
    unavailable = len(output.items) - citable - denied
    if citable and (denied or unavailable):
        status = TOOL_PARTIAL
    elif denied and not citable:
        status = TOOL_DENIED
    elif unavailable and not citable:
        status = TOOL_PARTIAL
    elif citable:
        status = TOOL_COMPLETED
    else:
        status = TOOL_EMPTY
    return ReadToolExecution(
        status=status,
        payload=output.model_dump(mode="json"),
        completeness=(
            RESULT_COMPLETENESS_UNKNOWN
            if denied or unavailable
            else RESULT_COMPLETENESS_LIMITED
        ),
        audit_summary={
            "requested_count": len(params.source_ids),
            "citable_count": citable,
            "denied_count": denied,
            "unavailable_count": unavailable,
        },
        error="部分 Evidence 越权或不可用" if denied or unavailable else None,
    )


KNOWLEDGE_AGENT_READ_TOOL_REGISTRY: dict[str, ReadToolSpec] = {
    **STRUCTURED_QUERY_TOOL_REGISTRY,
    "search_knowledge": ReadToolSpec(
        "search_knowledge", READ_TOOL_VERSION, SearchKnowledgeParams, search_knowledge_handler
    ),
    "read_entries": ReadToolSpec(
        "read_entries", READ_TOOL_VERSION, ReadEntriesParams, read_entries_handler
    ),
    "read_evidence": ReadToolSpec(
        "read_evidence", READ_TOOL_VERSION, ReadEvidenceParams, read_evidence_handler
    ),
}
