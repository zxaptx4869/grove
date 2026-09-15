"""正式 API 的 dialogue-loop 适配器。

该模块只负责把正式 Conversation/Run 包装成实验循环需要的最小状态，并把循环
结果写回正式模型。实验台的 Store、JSON 文件和工作台进程状态不进入这里。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAgentRun, KnowledgeMessage
from app.models.knowledge_agent import (
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
)
from app.services.knowledge_agent.observability import (
    StageMeta,
    record_model_invocation,
    run_fallback_summary,
)
from app.services.knowledge_agent.runner import RunCancelled
from evals.dialogue_loop.core import (
    TURN_COMPLETED,
    TURN_FAILED,
    TURN_PARTIAL_COMPLETED,
    BudgetLedger,
    ContinuationState,
)
from evals.dialogue_loop.instrumentation import BudgetedModel, Instrumentation
from evals.dialogue_loop.loop import LoopState, ResultRecord, build_agent, run_turn

logger = logging.getLogger(__name__)

STATE_VERSION = 1
HISTORY_LIMIT = 32
STATE_BYTES_LIMIT = 240_000


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _bounded_state(value: dict) -> dict:
    """保留可恢复材料的有界生产快照，不保存原始 prompt 或完整模型日志。"""
    raw = _json(value)
    if len(raw.encode("utf-8")) <= STATE_BYTES_LIMIT:
        return value
    # 先丢弃历史和非恢复性诊断，continuation/material 保留。
    reduced = dict(value)
    reduced["history_turns"] = reduced.get("history_turns", [])[-8:]
    reduced["model_calls"] = reduced.get("model_calls", [])[-8:]
    reduced["tool_events"] = reduced.get("tool_events", [])[-16:]
    reduced["truncated"] = True
    if len(_json(reduced).encode("utf-8")) > STATE_BYTES_LIMIT:
        # 结果 payload 已由循环工具限制大小；无法安全保存时明确不可恢复。
        reduced["records"] = {}
        reduced["evidence"] = {}
        reduced["truncated"] = True
    return reduced


def _record_snapshot(record: ResultRecord) -> dict:
    return {
        "handle": record.handle,
        "kind": record.kind,
        "payload": record.payload,
        "status": record.status,
        "completeness": record.completeness,
        "turn_index": record.turn_index,
        "semantics": record.semantics,
        "displayable": record.displayable,
    }


def _continuation_snapshot(continuation: ContinuationState | None) -> dict | None:
    if continuation is None:
        return None
    # snapshot() 隐去 material 是对外合同；生产恢复需要在正式 Run 内保留有界 material。
    return {
        **continuation.snapshot(),
        "recoverable_material": continuation.recoverable_material,
        "validation_refs": continuation.validation_refs,
    }


def _continuation_from_snapshot(raw: dict | None) -> ContinuationState | None:
    if not isinstance(raw, dict):
        return None
    fields = {
        "task_type",
        "tool_name",
        "scope",
        "completed_steps",
        "pending_steps",
        "confirmed",
        "stop_reason",
        "original_question",
        "resolved_references",
        "recoverable_material",
        "validation_refs",
    }
    try:
        return ContinuationState(**{key: raw.get(key) for key in fields})
    except (TypeError, ValueError):
        return None


def _state_snapshot(state: LoopState, turn: dict, *, loop_status: str) -> dict:
    records = {
        handle: _record_snapshot(record)
        for handle, record in state.result_sets.items()
        if record.displayable and handle in state.current_handles
    }
    return _bounded_state(
        {
            "version": STATE_VERSION,
            "loop_status": loop_status,
            "answer": turn.get("answer", ""),
            "blocks": turn.get("blocks", []),
            "completion": turn.get("completion") or {},
            "continuation": _continuation_snapshot(state.continuation),
            "history_turns": state.history_turns[-HISTORY_LIMIT:],
            "records": records,
            "evidence": state.evidence,
            "authorized_entry_ids": sorted(state.authorized_entry_ids),
            "tool_events": state.tool_events[-32:],
            "model_calls": turn.get("model_calls", [])[-16:],
            "budget": turn.get("budget"),
        }
    )


def _restore_state(state: LoopState, snapshot: dict) -> None:
    state.history_turns = list(snapshot.get("history_turns") or [])[-HISTORY_LIMIT:]
    state.authorized_entry_ids.update(
        int(item) for item in snapshot.get("authorized_entry_ids", [])
    )
    state.evidence.update(snapshot.get("evidence") or {})
    for raw in (snapshot.get("records") or {}).values():
        if not isinstance(raw, dict) or not raw.get("handle"):
            continue
        record = ResultRecord(
            handle=str(raw["handle"]),
            kind=str(raw.get("kind", "list")),
            payload=raw.get("payload") or {},
            status=str(raw.get("status", "completed")),
            completeness=str(raw.get("completeness", "limited")),
            turn_index=int(raw.get("turn_index", 0)),
            semantics=raw.get("semantics") or {},
            displayable=bool(raw.get("displayable", True)),
        )
        state.result_sets[record.handle] = record
        state.current_handles.add(record.handle)
        if record.kind == "list":
            state.authorized_entry_ids.update(
                int(item["entry_id"])
                for item in record.payload.get("items", [])
                if item.get("entry_id") is not None
            )
        try:
            sequence = int(record.handle.rsplit("-", 1)[-1])
        except (TypeError, ValueError):
            sequence = 0
        state._handle_sequence = max(state._handle_sequence, sequence)
    continuation = _continuation_from_snapshot(snapshot.get("continuation"))
    state.continuation = continuation


async def _cancel_check(run_id: int) -> None:
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        row = await db.get(KnowledgeAgentRun, run_id)
        if row is not None and row.cancel_requested:
            raise RunCancelled("运行中被取消")


async def _history_for_run(db: AsyncSession, run: KnowledgeAgentRun) -> list:
    """从正式消息表构造有界配对历史；不读取实验台历史格式。"""
    rows = (
        await db.execute(
            select(KnowledgeMessage)
            .where(
                KnowledgeMessage.conversation_id == run.conversation_id,
                KnowledgeMessage.id < (run.user_message_id or 0),
                KnowledgeMessage.role.in_(["user", "assistant"]),
                KnowledgeMessage.scope_type == run.scope_type,
                KnowledgeMessage.project_id == run.project_id,
            )
            .order_by(KnowledgeMessage.id.desc())
            .limit(HISTORY_LIMIT * 2)
        )
    ).scalars().all()
    messages = list(reversed(rows))
    history = []
    for message in messages:
        if not message.content.strip():
            continue
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=message.content[:2000])]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=message.content[:4000])]))
    return history[-HISTORY_LIMIT:]


def _run_status(loop_status: str) -> str:
    if loop_status == TURN_COMPLETED:
        return RUN_COMPLETED
    if loop_status == TURN_PARTIAL_COMPLETED:
        return RUN_PARTIAL
    if loop_status == "cancelled":
        return RUN_CANCELLED
    return RUN_FAILED


def _answer_status(loop_status: str, blocks: list[dict]) -> str:
    if loop_status == TURN_COMPLETED:
        return (
            "insufficient"
            if any(item.get("kind") == "insufficient" for item in blocks)
            else "completed"
        )
    if loop_status == TURN_PARTIAL_COMPLETED:
        return "partial"
    return "failed"


def _explicit_offline_model() -> FunctionModel:
    """开发环境未配置密钥时的显式降级：只交付可识别的资料不足块。"""

    def respond(_messages, info):
        output_tool = next(
            (tool for tool in info.output_tools if tool.name == "final_result"),
            None,
        )
        if output_tool is None:
            raise RuntimeError("统一循环未注册 final_result 输出工具")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    {
                        "blocks": [
                            {
                                "kind": "insufficient",
                                "text": "当前 Workspace 未配置可用文本模型，本轮未执行模型生成。",
                            }
                        ]
                    },
                )
            ]
        )

    return FunctionModel(respond, model_name="offline-production-fallback")


async def _record_model_logs(
    db: AsyncSession,
    run: KnowledgeAgentRun,
    model,
    turn: dict,
    *,
    fallback: bool = False,
) -> None:
    logs = turn.get("model_calls") or []
    if not logs:
        logs = [
            {
                "kind": "text_not_dispatched",
                "provider": "offline" if isinstance(model, TestModel) else "unknown",
                "model": getattr(model, "model_name", None),
                "duration_ms": 0,
                "usage": None,
                "error": "模型调用未产生可记录的日志",
            }
        ]
    for log in logs:
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=StageMeta(
                purpose=str(log.get("request_scope") or log.get("kind") or "dialogue_agent"),
                provider=str(log.get("provider") or "unknown"),
                model=log.get("model"),
                is_fallback=fallback or isinstance(model, TestModel) or bool(log.get("error")),
                error=log.get("error"),
                duration_ms=int(log.get("duration_ms") or 0),
                usage=log.get("usage"),
            ),
            prompt_version="dialogue-loop-v3",
        )


async def execute_dialogue_loop_run(db: AsyncSession, run: KnowledgeAgentRun) -> None:
    """执行正式 answer Run；候选草稿和 Entry 修订仍走各自受控操作入口。"""
    user_message = await db.get(KnowledgeMessage, run.user_message_id)
    message = user_message.content.strip() if user_message else ""
    if not message:
        run.status = RUN_FAILED
        run.error = "缺少用户消息，无法恢复 dialogue-loop"
        run.active_slot = None
        return

    from app.services.ai_models import get_text_model

    persisted = None
    previous = (
        await db.execute(
            select(KnowledgeAgentRun)
            .where(
                KnowledgeAgentRun.conversation_id == run.conversation_id,
                KnowledgeAgentRun.id != run.id,
                KnowledgeAgentRun.dialogue_loop_state_json.is_not(None),
            )
            .order_by(KnowledgeAgentRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if previous is not None:
        try:
            candidate = json.loads(previous.dialogue_loop_state_json or "null")
            if isinstance(candidate, dict):
                persisted = candidate
        except (json.JSONDecodeError, TypeError):
            persisted = None

    ledger = BudgetLedger()
    instrumentation = Instrumentation(ledger, context_policy_enabled=True)
    state = LoopState(
        workspace_id=run.workspace_id,
        user_id=run.owner_user_id,
        conversation_id=run.conversation_id,
        ledger=ledger,
        instrumentation=instrumentation,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
        cancel_check=lambda: _cancel_check(run.id),
    )
    if persisted:
        _restore_state(state, persisted)
    continuation = _continuation_from_snapshot(persisted.get("continuation") if persisted else None)
    if continuation is not None:
        state.continuation = continuation
    state.begin_turn(run.id, message)
    # 允许“第二条/刚才那组”复用最近一轮已授权结果；显式新话题必须清空旧句柄。
    if run.request_context_mode != "new_topic" and persisted:
        state.current_handles.update(state.result_sets)
    model = await get_text_model(db, run.workspace_id)
    used_fallback_model = isinstance(model, TestModel)
    if used_fallback_model:
        logger.warning("知识 Agent Run %s 使用离线模型，结果会标记为 fallback", run.id)
        model = _explicit_offline_model()
    wrapped_model = BudgetedModel(model, instrumentation, request_scope="dialogue_agent")
    agent = build_agent(wrapped_model)
    history = await _history_for_run(db, run)
    run.current_step = "dialogue_loop"
    run.dialogue_loop_state_json = _json(
        {
            "version": STATE_VERSION,
            "loop_status": "processing",
            "completion": {"can_continue": False},
        }
    )
    await db.commit()

    try:
        turn, _ = await run_turn(agent, state, message, history)
    except RunCancelled:
        run.status = RUN_CANCELLED
        run.current_step = None
        run.active_slot = None
        run.cancel_requested = True
        run.error = None
        run.dialogue_loop_state_json = _json(
            {
                "version": STATE_VERSION,
                "loop_status": "cancelled",
                "blocks": [],
                "completion": {"can_continue": False},
            }
        )
        if run.assistant_message_id:
            assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
            if assistant:
                assistant.content = "本轮已取消。"
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("dialogue-loop Run %s 执行失败", run.id)
        run.status = RUN_FAILED
        run.current_step = None
        run.active_slot = None
        run.error = f"dialogue-loop 执行失败：{type(exc).__name__}"
        run.dialogue_loop_state_json = _json(
            {
                "version": STATE_VERSION,
                "loop_status": TURN_FAILED,
                "blocks": [],
                "completion": {"can_continue": False},
            }
        )
        return

    loop_status = str(turn.get("status") or TURN_FAILED)
    state_snapshot = _state_snapshot(state, turn, loop_status=loop_status)
    run.dialogue_loop_state_json = _json(state_snapshot)
    run.status = _run_status(loop_status)
    run.current_step = None
    run.active_slot = None
    run.error = turn.get("error")
    run.answer_json = _json(
        {
            "answer": turn.get("answer") or "",
            "status": _answer_status(loop_status, turn.get("blocks") or []),
            "points": [],
            "citations": [],
            "conflicts": [],
            "group_counts": [],
            "warnings": [],
        }
    )
    if run.assistant_message_id:
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        if assistant:
            assistant.content = turn.get("answer") or ""
    await _record_model_logs(db, run, model, turn, fallback=used_fallback_model)
    run.fallback_summary = _json(await run_fallback_summary(db, run.id))
    await db.flush()
