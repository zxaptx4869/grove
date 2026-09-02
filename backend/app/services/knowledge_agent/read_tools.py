"""应用控制的 Knowledge Agent 只读工具 registry 与 dispatcher。

registry 只由应用代码显式装配；模型只能请求其中已有名称和版本。dispatcher
把 RunToolContext 与已校验参数分开传给处理器，不允许参数覆盖 owner、Workspace、
项目、数据库会话、预算或取消状态。
"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic, perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAgentToolCall
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_UNKNOWN,
    TOOL_CANCELLED,
    TOOL_COMPLETED,
    TOOL_DENIED,
    TOOL_EMPTY,
    TOOL_ERROR,
    TOOL_LIMITED,
)
from app.services.knowledge_agent.observability import (
    next_tool_sequence,
    record_tool_call,
)
from app.services.knowledge_agent.tools import RunToolContext

CancelCheck = Callable[[], Awaitable[None]]


class ReadToolParams(BaseModel):
    """只读工具参数基类：所有未声明字段都拒绝。"""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ReadToolExecution:
    """处理器返回的结构化结果与最小审计摘要。"""

    status: str
    payload: dict
    completeness: str = RESULT_COMPLETENESS_UNKNOWN
    audit_summary: dict | None = None
    error: str | None = None


ReadToolHandler = Callable[
    [AsyncSession, RunToolContext, BaseModel],
    Awaitable[ReadToolExecution],
]
ReadToolRestoreHandler = Callable[
    [AsyncSession, RunToolContext, BaseModel, dict],
    Awaitable[ReadToolExecution | None],
]


@dataclass(frozen=True)
class ReadToolSpec:
    """应用声明的工具契约；不接受运行时动态模块路径。"""

    name: str
    version: str
    params_model: type[BaseModel]
    handler: ReadToolHandler
    restore_handler: ReadToolRestoreHandler | None = None


@dataclass
class ReadToolBudget:
    """单计划共享的服务端预算；客户端与模型不能扩张。"""

    max_calls: int
    timeout_seconds: float
    max_result_bytes: int
    calls_used: int = 0
    started_at: float = 0.0

    def __post_init__(self) -> None:
        if self.started_at <= 0:
            self.started_at = monotonic()

    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_seconds - (monotonic() - self.started_at))


@dataclass(frozen=True)
class ReadToolDispatchResult:
    """dispatcher 结果：payload 有界，状态/完整性可独立判断。"""

    tool_name: str
    tool_version: str
    fingerprint: str
    status: str
    completeness: str
    payload: dict
    error: str | None
    duration_ms: int
    reused: bool = False


# 应用静态注册表；具体工具在模块加载时由明确代码一次性装配，不扫描模块。
READ_TOOL_REGISTRY: dict[str, ReadToolSpec] = {}


def install_read_tool(spec: ReadToolSpec) -> None:
    """由应用启动代码显式安装白名单工具；重复名称直接拒绝。"""
    if spec.name in READ_TOOL_REGISTRY:
        raise RuntimeError(f"只读工具已注册：{spec.name}")
    READ_TOOL_REGISTRY[spec.name] = spec


def tool_call_fingerprint(
    *,
    run_id: int,
    tool_name: str,
    tool_version: str,
    params: dict,
) -> str:
    """生成绑定 Run、工具版本与规范化参数的稳定 sha256 指纹。"""
    raw = json.dumps(
        {
            "run_id": run_id,
            "tool_name": tool_name,
            "tool_version": tool_version,
            "params": params,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bounded_json(value: dict, limit: int) -> tuple[str, bool]:
    """序列化审计/结果；超限时只返回确定性元数据，不复制原始内容。"""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= limit:
        return raw, False
    fallback = json.dumps(
        {
            "truncated": True,
            "keys": sorted(str(key)[:64] for key in value)[:20],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return fallback, True


async def _record_dispatch(
    db: AsyncSession,
    *,
    ctx: RunToolContext,
    tool_name: str,
    tool_version: str,
    fingerprint: str,
    params_summary: dict,
    result_summary: dict,
    status: str,
    error: str | None,
    duration_ms: int,
) -> None:
    """保存有界审计；不记录正文、Source 原文或 prompt。"""
    sequence = await next_tool_sequence(db, ctx.run_id)
    params_raw, _ = _bounded_json(
        {
            "tool_version": tool_version,
            "fingerprint": fingerprint,
            "params": params_summary,
        },
        1000,
    )
    result_raw, _ = _bounded_json(result_summary, 2000)
    await record_tool_call(
        db,
        run_id=ctx.run_id,
        sequence=sequence,
        tool_name=tool_name,
        status=status,
        params_summary=params_raw,
        result_summary=result_raw,
        error=error,
        duration_ms=duration_ms,
    )


async def dispatch_read_tool(
    db: AsyncSession,
    ctx: RunToolContext,
    *,
    tool_name: str,
    tool_version: str,
    params: Mapping[str, Any],
    budget: ReadToolBudget,
    cancel_check: CancelCheck,
    registry: Mapping[str, ReadToolSpec] | None = None,
) -> ReadToolDispatchResult:
    """校验并调用白名单只读工具；未知/越权参数不尝试修正或猜测。"""
    started = perf_counter()
    active_registry = READ_TOOL_REGISTRY if registry is None else registry
    spec = active_registry.get(tool_name)
    raw_keys = sorted(str(key)[:64] for key in params)[:20]
    if spec is None or spec.version != tool_version:
        fingerprint = tool_call_fingerprint(
            run_id=ctx.run_id,
            tool_name=tool_name,
            tool_version=tool_version,
            params={"rejected_keys": raw_keys},
        )
        error = "工具未注册或版本不受支持"
        duration = int((perf_counter() - started) * 1000)
        await _record_dispatch(
            db,
            ctx=ctx,
            tool_name=tool_name[:64],
            tool_version=tool_version[:32],
            fingerprint=fingerprint,
            params_summary={"rejected_keys": raw_keys},
            result_summary={"status": TOOL_DENIED},
            status=TOOL_DENIED,
            error=error,
            duration_ms=duration,
        )
        return ReadToolDispatchResult(
            tool_name=tool_name,
            tool_version=tool_version,
            fingerprint=fingerprint,
            status=TOOL_DENIED,
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            payload={},
            error=error,
            duration_ms=duration,
        )

    try:
        validated = spec.params_model.model_validate(dict(params))
    except ValidationError as exc:
        fingerprint = tool_call_fingerprint(
            run_id=ctx.run_id,
            tool_name=tool_name,
            tool_version=tool_version,
            params={"rejected_keys": raw_keys},
        )
        error = f"工具参数非法：{exc.error_count()} 项"
        duration = int((perf_counter() - started) * 1000)
        await _record_dispatch(
            db,
            ctx=ctx,
            tool_name=tool_name,
            tool_version=tool_version,
            fingerprint=fingerprint,
            params_summary={"rejected_keys": raw_keys},
            result_summary={"status": TOOL_DENIED},
            status=TOOL_DENIED,
            error=error,
            duration_ms=duration,
        )
        return ReadToolDispatchResult(
            tool_name=tool_name,
            tool_version=tool_version,
            fingerprint=fingerprint,
            status=TOOL_DENIED,
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            payload={},
            error=error,
            duration_ms=duration,
        )

    normalized_params = validated.model_dump(mode="json", by_alias=True)
    fingerprint = tool_call_fingerprint(
        run_id=ctx.run_id,
        tool_name=tool_name,
        tool_version=tool_version,
        params=normalized_params,
    )
    await cancel_check()
    reusable = await _find_reusable_call(
        db,
        run_id=ctx.run_id,
        tool_name=tool_name,
        fingerprint=fingerprint,
    )
    if reusable is not None and spec.restore_handler is not None:
        restored = await spec.restore_handler(db, ctx, validated, reusable)
        if restored is not None:
            await cancel_check()
            duration = int((perf_counter() - started) * 1000)
            return ReadToolDispatchResult(
                tool_name=tool_name,
                tool_version=tool_version,
                fingerprint=fingerprint,
                status=restored.status,
                completeness=restored.completeness,
                payload=restored.payload,
                error=restored.error,
                duration_ms=duration,
                reused=True,
            )
    if budget.calls_used >= budget.max_calls or budget.remaining_seconds() <= 0:
        error = "只读工具调用预算已耗尽"
        duration = int((perf_counter() - started) * 1000)
        await _record_dispatch(
            db,
            ctx=ctx,
            tool_name=tool_name,
            tool_version=tool_version,
            fingerprint=fingerprint,
            params_summary=normalized_params,
            result_summary={"status": TOOL_DENIED, "budget_exhausted": True},
            status=TOOL_DENIED,
            error=error,
            duration_ms=duration,
        )
        return ReadToolDispatchResult(
            tool_name=tool_name,
            tool_version=tool_version,
            fingerprint=fingerprint,
            status=TOOL_DENIED,
            completeness=RESULT_COMPLETENESS_UNKNOWN,
            payload={},
            error=error,
            duration_ms=duration,
        )

    budget.calls_used += 1
    try:
        await cancel_check()
        async with asyncio.timeout(budget.remaining_seconds()):
            execution = await spec.handler(db, ctx, validated)
        await cancel_check()
    except TimeoutError:
        execution = ReadToolExecution(
            status=TOOL_ERROR,
            payload={},
            error="只读工具执行超时",
        )
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "RunCancelled":
            duration = int((perf_counter() - started) * 1000)
            await _record_dispatch(
                db,
                ctx=ctx,
                tool_name=tool_name,
                tool_version=tool_version,
                fingerprint=fingerprint,
                params_summary=normalized_params,
                result_summary={"status": TOOL_CANCELLED},
                status=TOOL_CANCELLED,
                error="Run 已取消",
                duration_ms=duration,
            )
            raise
        execution = ReadToolExecution(
            status=TOOL_ERROR,
            payload={},
            error=f"只读工具执行失败：{exc}",
        )

    payload_raw, payload_truncated = _bounded_json(
        execution.payload,
        budget.max_result_bytes,
    )
    payload = json.loads(payload_raw)
    status = execution.status
    completeness = execution.completeness
    error = execution.error
    if payload_truncated:
        status = TOOL_LIMITED
        completeness = "limited"
        error = error or "工具结果超过 JSON 字节预算"
    duration = int((perf_counter() - started) * 1000)
    audit = execution.audit_summary or {
        "status": status,
        "completeness": completeness,
        "payload_keys": sorted(payload),
    }
    await _record_dispatch(
        db,
        ctx=ctx,
        tool_name=tool_name,
        tool_version=tool_version,
        fingerprint=fingerprint,
        params_summary=normalized_params,
        result_summary=audit,
        status=status,
        error=error,
        duration_ms=duration,
    )
    return ReadToolDispatchResult(
        tool_name=tool_name,
        tool_version=tool_version,
        fingerprint=fingerprint,
        status=status,
        completeness=completeness,
        payload=payload,
        error=error,
        duration_ms=duration,
    )


async def _find_reusable_call(
    db: AsyncSession,
    *,
    run_id: int,
    tool_name: str,
    fingerprint: str,
) -> dict | None:
    """查找同 Run 已提交的成功调用摘要；旧/非法摘要不复用。"""
    rows = (
        await db.execute(
            select(KnowledgeAgentToolCall)
            .where(
                KnowledgeAgentToolCall.run_id == run_id,
                KnowledgeAgentToolCall.tool_name == tool_name,
                KnowledgeAgentToolCall.status.in_(
                    [TOOL_COMPLETED, TOOL_EMPTY, TOOL_LIMITED]
                ),
            )
            .order_by(KnowledgeAgentToolCall.sequence)
        )
    ).scalars().all()
    for row in rows:
        try:
            params_summary = json.loads(row.params_summary or "{}")
            result_summary = json.loads(row.result_summary or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if params_summary.get("fingerprint") != fingerprint:
            continue
        if not isinstance(result_summary, dict):
            continue
        return result_summary
    return None


def completed_execution(
    payload: dict,
    *,
    completeness: str,
    audit_summary: dict,
) -> ReadToolExecution:
    """构造正常完成结果，空集合状态由具体工具明确给出。"""
    return ReadToolExecution(
        status=TOOL_COMPLETED,
        payload=payload,
        completeness=completeness,
        audit_summary=audit_summary,
    )
