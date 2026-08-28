"""知识 Agent 分阶段可观测性：模型调用、工具调用与降级摘要聚合。"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAgentModelInvocation, KnowledgeAgentToolCall
from app.models.knowledge_agent import (
    TOOL_DENIED,
    TOOL_EMPTY,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_PARTIAL,
    TOOL_UNAVAILABLE,
)

logger = logging.getLogger(__name__)

# 进入受影响阶段的工具状态：正常 ok 与正常 empty 不在此集合
AFFECTED_TOOL_STATUSES = {TOOL_PARTIAL, TOOL_DENIED, TOOL_UNAVAILABLE, TOOL_ERROR}


@dataclass
class StageMeta:
    """单个 AI 阶段的可观测元数据。"""

    purpose: str
    provider: str
    model: str | None
    is_fallback: bool
    error: str | None
    duration_ms: int


async def next_tool_sequence(db: AsyncSession, run_id: int) -> int:
    """返回本 Run 下一次工具调用的序号（重试时继续追加）。"""
    current = (
        await db.execute(
            select(func.max(KnowledgeAgentToolCall.sequence)).where(
                KnowledgeAgentToolCall.run_id == run_id
            )
        )
    ).scalar_one()
    return (current or 0) + 1


async def record_tool_call(
    db: AsyncSession,
    *,
    run_id: int,
    sequence: int,
    tool_name: str,
    status: str,
    params_summary: str | None = None,
    result_summary: str | None = None,
    error: str | None = None,
    duration_ms: int = 0,
    investigation_id: int | None = None,
    round_number: int | None = None,
    query_sequence: int | None = None,
) -> None:
    """持久化一次工具调用（只保存脱敏摘要）。"""
    db.add(
        KnowledgeAgentToolCall(
            run_id=run_id,
            sequence=sequence,
            tool_name=tool_name,
            params_summary=params_summary,
            result_summary=result_summary,
            status=status,
            error=error,
            duration_ms=duration_ms,
            investigation_id=investigation_id,
            round_number=round_number,
            query_sequence=query_sequence,
        )
    )
    await db.flush()


async def record_model_invocation(
    db: AsyncSession,
    *,
    run_id: int,
    meta: StageMeta,
    prompt_version: str,
    usage: dict | None = None,
    investigation_id: int | None = None,
    round_number: int | None = None,
    query_sequence: int | None = None,
) -> None:
    """持久化一次 embedding / 重排 / 回答模型调用。"""
    db.add(
        KnowledgeAgentModelInvocation(
            run_id=run_id,
            purpose=meta.purpose,
            prompt_version=prompt_version,
            provider=meta.provider,
            model=meta.model,
            is_fallback=meta.is_fallback,
            error=meta.error,
            duration_ms=meta.duration_ms,
            usage_json=json.dumps(usage, ensure_ascii=False) if usage else None,
            investigation_id=investigation_id,
            round_number=round_number,
            query_sequence=query_sequence,
        )
    )
    await db.flush()


async def record_reference_validation(
    db: AsyncSession,
    run_id: int,
    *,
    stats,
    note: str,
) -> None:
    """记录引用校验阶段的降级（服务端确定性阶段，不是模型调用）。"""
    db.add(
        KnowledgeAgentModelInvocation(
            run_id=run_id,
            purpose="validate_refs",
            prompt_version="server",
            provider="server",
            model=None,
            is_fallback=True,
            error=(
                f"{note}（请求 {stats.requested_count} / 有效 {stats.valid_count} / "
                f"丢弃 {stats.discarded_count}）"
            ),
            duration_ms=0,
        )
    )
    await db.flush()


async def run_fallback_summary(
    db: AsyncSession,
    run_id: int,
) -> dict:
    """聚合 Run 的阶段降级摘要；局部降级不被掩盖为完全正常。"""
    invocations = (
        await db.execute(
            select(KnowledgeAgentModelInvocation).where(
                KnowledgeAgentModelInvocation.run_id == run_id
            )
        )
    ).scalars().all()
    tool_calls = (
        await db.execute(
            select(KnowledgeAgentToolCall).where(
                KnowledgeAgentToolCall.run_id == run_id
            )
        )
    ).scalars().all()
    stages = [
        {
            "purpose": item.purpose,
            "is_fallback": item.is_fallback,
            "provider": item.provider,
            "model": item.model,
            "error": item.error,
        }
        for item in invocations
    ]
    for item in tool_calls:
        if item.status == TOOL_OK or item.status == TOOL_EMPTY:
            # 正常完成与正常空结果不算 fallback
            continue
        stages.append(
            {
                "purpose": f"tool:{item.tool_name}",
                "is_fallback": True,
                "provider": None,
                "model": None,
                "error": item.error or item.status,
            }
        )
    return {"has_fallback": any(stage["is_fallback"] for stage in stages), "stages": stages}
