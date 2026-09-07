"""工作台会话、轮次、反馈和统一循环运行时。"""

from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from evals.dialogue_loop.core import (
    BATCH_EMBEDDING_REQUESTS,
    BATCH_TEXT_REQUESTS,
    EXPERIMENT_VERSION,
    PROMPT_VERSION,
    BudgetLedger,
    frozen_budget,
)
from evals.dialogue_loop.report import sanitize
from evals.dialogue_workbench.store import WorkbenchStore

TERMINAL_TURN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
FEEDBACK_KINDS = {"wrong", "misunderstood", "omitted"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ConversationEngine(Protocol):
    provider: str
    model: str
    offline: bool
    ledger: BudgetLedger

    async def create_context(self) -> Any: ...

    async def run_turn(
        self,
        context: Any,
        message: str,
        turn_number: int,
        stage: Callable[[str], None],
    ) -> dict: ...

    async def cancel_turn(self, context: Any) -> dict: ...


class WorkbenchRuntime:
    """单实验进程共享预算和一个活动生成任务。"""

    def __init__(
        self,
        *,
        engine: ConversationEngine,
        store: WorkbenchStore,
        snapshot_at: str,
        snapshot_fingerprint: str,
        isolation_unchanged: Callable[[], bool | Awaitable[bool]],
    ):
        self.engine = engine
        self.store = store
        self.snapshot_at = snapshot_at
        self.snapshot_fingerprint = snapshot_fingerprint
        self.isolation_unchanged = isolation_unchanged
        self.session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.browser_sessions: set[str] = set()
        self.contexts: dict[str, Any] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.request_ids: dict[tuple[str, str], str] = {}
        self.active_turn_id: str | None = None
        self.unsafe_reason: str | None = None
        self._persist_lock = asyncio.Lock()
        self.data = store.load()
        self.current_session = {
            "id": self.session_id,
            "active": True,
            "created_at": utc_now(),
            "experiment_version": EXPERIMENT_VERSION,
            "prompt_version": PROMPT_VERSION,
            "provider": engine.provider,
            "model": engine.model,
            "offline": engine.offline,
            "snapshot_at": snapshot_at,
            "snapshot_fingerprint": snapshot_fingerprint,
            "conversations": [],
        }
        self.data.setdefault("sessions", []).append(self.current_session)
        self.store.save(self.data)

    def issue_browser_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.browser_sessions.add(token)
        return token

    def authorize(self, token: str | None) -> bool:
        return bool(token and token in self.browser_sessions)

    def _conversation(self, conversation_id: str) -> dict:
        for session in self.data.get("sessions", []):
            for conversation in session.get("conversations", []):
                if conversation.get("id") == conversation_id:
                    return conversation
        raise KeyError(conversation_id)

    def _current_conversation(self, conversation_id: str) -> dict:
        conversation = self._conversation(conversation_id)
        if conversation.get("session_id") != self.session_id or conversation.get("read_only"):
            raise PermissionError("该对话属于已结束的运行，只能查看和导出")
        return conversation

    def public_state(self) -> dict:
        ledger = self.engine.ledger.snapshot()
        return sanitize(
            {
                "metadata": {
                    "experiment_version": EXPERIMENT_VERSION,
                    "prompt_version": PROMPT_VERSION,
                    "provider": self.engine.provider,
                    "model": self.engine.model,
                    "offline": self.engine.offline,
                    "snapshot_at": self.snapshot_at,
                    "snapshot_fingerprint": self.snapshot_fingerprint,
                    "status": "unsafe" if self.unsafe_reason else "ready",
                    "unsafe_reason": self.unsafe_reason,
                    "storage_path": str(self.store.path),
                    "serial_execution": True,
                },
                "budget": {
                    **frozen_budget(),
                    "used": {
                        "text_requests": ledger["batch_text_requests"],
                        "embedding_requests": ledger["batch_embedding_requests"],
                    },
                    "remaining": {
                        "text_requests": max(
                            BATCH_TEXT_REQUESTS - ledger["batch_text_requests"], 0
                        ),
                        "embedding_requests": max(
                            BATCH_EMBEDDING_REQUESTS - ledger["batch_embedding_requests"], 0
                        ),
                    },
                },
                "active_turn_id": self.active_turn_id,
                "sessions": self.data.get("sessions", []),
            }
        )

    async def create_conversation(self) -> dict:
        if self.unsafe_reason:
            raise RuntimeError(self.unsafe_reason)
        conversation_id = str(uuid4())
        context = await self.engine.create_context()
        now = utc_now()
        conversation = {
            "id": conversation_id,
            "session_id": self.session_id,
            "title": "新对话",
            "created_at": now,
            "updated_at": now,
            "read_only": False,
            "recovery_notice": None,
            "turns": [],
        }
        self.contexts[conversation_id] = context
        self.current_session["conversations"].insert(0, conversation)
        await self.persist()
        return sanitize(conversation)

    async def submit_turn(self, conversation_id: str, message: str, request_id: str) -> dict:
        if self.unsafe_reason:
            raise RuntimeError(self.unsafe_reason)
        conversation = self._current_conversation(conversation_id)
        normalized = message.strip()
        if not normalized:
            raise ValueError("消息不能为空")
        if len(normalized.encode("utf-8")) > 48_000:
            raise ValueError("消息超过 48 KiB 输入上限")
        key = (conversation_id, request_id)
        if key in self.request_ids:
            return self._turn(conversation, self.request_ids[key])
        if self.active_turn_id is not None:
            raise RuntimeError("当前实验已有一轮正在生成，请等待完成或先停止")
        if conversation_id not in self.contexts:
            raise RuntimeError("当前对话运行上下文不可恢复，请新建对话")
        turn_id = str(uuid4())
        now = utc_now()
        turn = {
            "id": turn_id,
            "request_id": request_id,
            "user_message": normalized,
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "answer": "",
            "blocks": [],
            "error": None,
            "error_details": None,
            "solve_error": None,
            "duration_ms": 0,
            "tool_calls": None,
            "model_calls": None,
            "budget": None,
            "context": None,
            "finalization": None,
            "persistence": None,
            "isolation_check": None,
            "feedback": None,
        }
        if conversation["title"] == "新对话":
            conversation["title"] = normalized[:24] + ("…" if len(normalized) > 24 else "")
        conversation["turns"].append(turn)
        conversation["updated_at"] = now
        self.request_ids[key] = turn_id
        self.active_turn_id = turn_id
        task = asyncio.create_task(
            self._execute_turn(conversation_id, turn_id), name=f"workbench-turn-{turn_id}"
        )
        self.tasks[turn_id] = task
        await self.persist()
        return sanitize(turn)

    def _turn(self, conversation: dict, turn_id: str) -> dict:
        for turn in conversation.get("turns", []):
            if turn.get("id") == turn_id:
                return turn
        raise KeyError(turn_id)

    async def _execute_turn(self, conversation_id: str, turn_id: str) -> None:
        conversation = self._current_conversation(conversation_id)
        turn = self._turn(conversation, turn_id)
        context = self.contexts[conversation_id]
        turn["status"] = "running"
        self._set_stage(turn, "organizing")
        started = perf_counter()

        def stage(value: str) -> None:
            self._set_stage(turn, value)
            self.store.save(self.data)

        try:
            result = await self.engine.run_turn(
                context, turn["user_message"], len(conversation["turns"]), stage
            )
        except asyncio.CancelledError:
            cancelled = await self.engine.cancel_turn(context)
            turn.update(cancelled)
            turn["status"] = "cancelled"
            turn["stage"] = "cancelled"
            turn["error"] = "用户已停止生成。"
        except Exception as exc:
            turn["status"] = "failed"
            turn["stage"] = "failed"
            turn["error"] = f"{type(exc).__name__}: {str(exc)[:2000]}"
            turn["error_details"] = {
                "category": "runtime",
                "message": str(exc)[:4_000],
            }
        else:
            turn.update(sanitize(result))
            turn["stage"] = turn.get("status", "completed")
        finally:
            turn["duration_ms"] = turn.get("duration_ms") or int((perf_counter() - started) * 1000)
            turn["updated_at"] = utc_now()
            turn["completed_at"] = turn["updated_at"]
            conversation["updated_at"] = turn["updated_at"]
            self.tasks.pop(turn_id, None)
            if self.active_turn_id == turn_id:
                self.active_turn_id = None
            try:
                unchanged = self.isolation_unchanged()
                if inspect.isawaitable(unchanged):
                    unchanged = await unchanged
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {str(exc)[:2_000]}"
                turn["isolation_check"] = {
                    "status": "failed",
                    "message": "隔离指纹无法核验，未判定业务数据已被修改。",
                    "error": message,
                }
                self.unsafe_reason = "隔离指纹无法核验，实验已停止后续数据库操作"
            else:
                if unchanged:
                    turn["isolation_check"] = {"status": "unchanged", "error": None}
                else:
                    turn["isolation_check"] = {
                        "status": "changed",
                        "message": "业务数据隔离指纹发生变化。",
                        "error": None,
                    }
                    self.unsafe_reason = "业务数据隔离指纹发生变化，实验已停止"
            await self.persist()

    def _set_stage(self, turn: dict, stage: str) -> None:
        turn["stage"] = stage
        turn["updated_at"] = utc_now()

    async def cancel_turn(self, conversation_id: str, turn_id: str) -> dict:
        conversation = self._current_conversation(conversation_id)
        turn = self._turn(conversation, turn_id)
        task = self.tasks.get(turn_id)
        if task is None or turn.get("status") in TERMINAL_TURN_STATUSES:
            return sanitize(turn)
        turn["stage"] = "cancelling"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return sanitize(turn)

    async def save_feedback(self, conversation_id: str, turn_id: str, kind: str, note: str) -> dict:
        conversation = self._current_conversation(conversation_id)
        turn = self._turn(conversation, turn_id)
        if kind not in FEEDBACK_KINDS:
            raise ValueError("反馈类型无效")
        feedback = {
            "kind": kind,
            "note": note.strip()[:2000],
            "saved_at": utc_now(),
            "conversation_id": conversation_id,
            "turn_id": turn_id,
            "experiment_version": EXPERIMENT_VERSION,
            "diagnostic": {
                "status": turn.get("status"),
                "error": turn.get("error"),
                "budget": turn.get("budget"),
                "finalization": turn.get("finalization"),
            },
        }
        turn["feedback"] = feedback
        await self.persist()
        return sanitize(feedback)

    async def persist(self) -> None:
        async with self._persist_lock:
            self.store.save(self.data)

    def export_payload(self) -> dict:
        return sanitize(self.data)


class OfflineFixtureEngine:
    """只供自动化和浏览器验收的显式离线桩。"""

    provider = "offline_fixture"
    model = "deterministic-workbench-fixture"
    offline = True

    def __init__(self):
        self.ledger = BudgetLedger()

    async def create_context(self) -> dict:
        return {"turns": 0, "cancelled": False}

    async def run_turn(
        self,
        context: dict,
        message: str,
        turn_number: int,
        stage: Callable[[str], None],
    ) -> dict:
        context["turns"] += 1
        self.ledger.start_turn()
        delay = 0.7 if "慢查询" in message else 0.04
        stage("querying")
        await asyncio.sleep(delay)
        stage("reading_sources")
        await asyncio.sleep(delay)
        stage("organizing")
        await asyncio.sleep(delay)
        await self.ledger.reserve_text()
        if "失败" in message:
            return {
                "message": message,
                "status": "failed",
                "answer": "本轮未完成。",
                "blocks": [{"kind": "insufficient", "text": "离线桩模拟 Provider 失败。"}],
                "error": "FixtureProviderError: 离线桩模拟失败",
                "error_details": {"category": "provider", "message": "离线桩模拟失败"},
                "solve_error": None,
                "duration_ms": 120,
                "usage": None,
                "budget": self.ledger.snapshot(),
                "tool_calls": [],
                "model_calls": [
                    {
                        "kind": "text",
                        "provider": self.provider,
                        "model": self.model,
                        "duration_ms": 40,
                        "usage": None,
                        "error_kind": "provider",
                    }
                ],
                "context": {"history_turns": context["turns"] - 1},
                "finalization": {"status": "not_needed", "attempted": False},
            }
        items = [
            {
                "entry_id": 101,
                "title": "施工材料环保等级",
                "project_name": "房子装修",
                "main_type": "knowledge",
                "summary": "离线验收用的正式知识摘要。",
            },
            {
                "entry_id": 102,
                "title": "甲醛控制方法",
                "project_name": "房子装修",
                "main_type": "method",
                "summary": "用于验证有序列表与跨轮展示。",
            },
        ]
        return {
            "message": message,
            "status": "completed",
            "answer": "这是明确标记的离线验收回答。\n共找到 2 条正式记录。",
            "blocks": [
                {"kind": "text", "text": "这是明确标记的离线验收回答。"},
                {
                    "kind": "statistic",
                    "handle": "fixture-stat",
                    "text": "正式记录总数：2",
                    "value": 2,
                    "status": "completed",
                    "completeness": "complete",
                },
                {
                    "kind": "list",
                    "handle": "fixture-list",
                    "label": "相关记录",
                    "items": items,
                    "status": "completed",
                    "completeness": "complete",
                },
                {
                    "kind": "evidence",
                    "handle": "fixture-evidence",
                    "text": "来源《装修验收记录》：材料进场后应核对环保等级。",
                    "entry_id": 101,
                    "source_id": 201,
                },
            ],
            "error": None,
            "error_details": None,
            "solve_error": None,
            "duration_ms": 120,
            "usage": {"input_tokens": 320, "output_tokens": 86},
            "budget": self.ledger.snapshot(),
            "tool_calls": [
                {
                    "tool": "query_entries",
                    "status": "completed",
                    "completeness": "complete",
                    "params": {
                        "project_scope": "all",
                        "project_name": None,
                        "main_types": [],
                        "limit": 10,
                    },
                    "result_handle": "fixture-list",
                    "result_summary": {
                        "returned_items": 2,
                        "titles": ["施工材料环保等级", "甲醛控制方法"],
                    },
                    "duration_ms": 28,
                },
                {
                    "tool": "read_evidence",
                    "status": "completed",
                    "completeness": "limited",
                    "params": {"entry_id": 101, "source_ids": [201]},
                    "result_handle": "fixture-evidence",
                    "result_summary": {"returned_items": 1},
                    "duration_ms": 21,
                },
            ],
            "model_calls": [
                {
                    "kind": "text",
                    "provider": self.provider,
                    "model": self.model,
                    "duration_ms": 40,
                    "usage": {"input_tokens": 320, "output_tokens": 86},
                    "estimated_input_tokens": 380,
                    "actual_input_tokens": 320,
                    "request_scope": "dialogue_agent",
                    "finalize_only": False,
                    "error": None,
                }
            ],
            "context": {
                "history_turns": context["turns"] - 1,
                "history_estimated_input_tokens": 120 + context["turns"] * 30,
            },
            "finalization": {"status": "not_needed", "attempted": False},
        }

    async def cancel_turn(self, context: dict) -> dict:
        context["cancelled"] = True
        return {
            "answer": "生成已停止。",
            "blocks": [{"kind": "insufficient", "text": "生成已停止。"}],
            "tool_calls": [],
            "model_calls": [],
            "budget": self.ledger.snapshot(),
            "context": None,
            "finalization": {"status": "cancelled", "attempted": False},
        }
