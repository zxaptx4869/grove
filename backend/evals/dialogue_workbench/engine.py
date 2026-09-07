"""对现有统一对话循环的薄运行时包装。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any

from pydantic_ai.messages import ModelMessage

from evals.dialogue_loop.core import BudgetLedger
from evals.dialogue_loop.execution import _create_conversation, _finish_new_run, _submit_turn
from evals.dialogue_loop.instrumentation import (
    BudgetedModel,
    Instrumentation,
    install_instrumentation,
)
from evals.dialogue_loop.loop import (
    LoopState,
    _aggregate_text_usage,
    _verified_failure_output,
    build_agent,
    build_compact_history,
    run_turn,
)


@dataclass
class UnifiedConversationContext:
    state: LoopState
    history: list[ModelMessage]
    event_start: int = 0
    log_start: int = 0
    run_id: int | None = None
    persistence: dict | None = None


class UnifiedLoopEngine:
    """直接调用 dialogue-loop-v2，不复制工具或回答逻辑。"""

    offline = False

    def __init__(self, identity: dict[str, Any], model: Any, instrumentation: Instrumentation):
        self.identity = identity
        self.ledger = instrumentation.ledger
        self.instrumentation = instrumentation
        self.agent = build_agent(model)
        self.provider = str(model.system)
        self.model = model.model_name
        self.database_lock = asyncio.Lock()

    @classmethod
    async def create(cls, identity: dict[str, Any]) -> UnifiedLoopEngine:
        from app.db.session import async_session_factory
        from app.services import ai_models

        ledger = BudgetLedger()
        instrumentation = Instrumentation(ledger, context_policy_enabled=True)
        install_instrumentation(instrumentation)
        async with async_session_factory() as db:
            model = await ai_models.get_text_model(db, identity["workspace_id"])
            await db.rollback()
        if not isinstance(model, BudgetedModel):
            raise RuntimeError("文本模型没有进入实验预算包装，拒绝启动")
        if str(model.system).lower() in {"demo", "test", "offline", "mock"}:
            raise RuntimeError("模型配置不是可识别的真实 Provider，拒绝启动")
        model.request_scope = "dialogue_agent"
        return cls(identity, model, instrumentation)

    async def create_context(self) -> UnifiedConversationContext:
        async with self.database_lock:
            conversation_id = await _create_conversation(
                self.identity["workspace_id"], self.identity["user_id"]
            )
        state = LoopState(
            workspace_id=self.identity["workspace_id"],
            user_id=self.identity["user_id"],
            conversation_id=conversation_id,
            ledger=self.ledger,
            instrumentation=self.instrumentation,
            database_lock=self.database_lock,
        )
        return UnifiedConversationContext(state=state, history=[])

    async def run_turn(
        self,
        context: UnifiedConversationContext,
        message: str,
        turn_number: int,
        stage,
    ) -> dict:
        context.event_start = len(context.state.tool_events)
        context.log_start = len(self.instrumentation.logs)
        context.persistence = None
        started = perf_counter()
        async with self.database_lock:
            run_id = await _submit_turn(context.state.conversation_id, message, turn_number)
        context.run_id = run_id
        context.state.begin_turn(run_id, message)
        self.instrumentation.activity_callback = stage
        try:
            turn, context.history = await run_turn(
                self.agent, context.state, message, context.history
            )
        except asyncio.CancelledError:
            try:
                async with self.database_lock:
                    await _finish_new_run(run_id, "", "用户取消")
            except Exception as exc:  # noqa: BLE001
                context.persistence = _persistence_failure(exc)
            raise
        except Exception as exc:  # noqa: BLE001
            turn = self._recover_failed_turn(context, message, exc, started)
        finally:
            self.instrumentation.activity_callback = None
        try:
            async with self.database_lock:
                await _finish_new_run(run_id, turn["answer"], turn["error"])
        except Exception as exc:  # noqa: BLE001
            persistence = _persistence_failure(exc)
            context.persistence = persistence
            turn["solve_status"] = turn["status"]
            turn["status"] = "failed"
            turn["persistence"] = persistence
            notice = f"运行结果保存失败：{persistence['message']}"
            turn["error"] = f"{turn['error']}；{notice}" if turn.get("error") else notice
        else:
            context.persistence = {"status": "completed", "error": None}
            turn["persistence"] = context.persistence
        return turn

    def _recover_failed_turn(
        self,
        context: UnifiedConversationContext,
        message: str,
        exc: Exception,
        started: float,
    ) -> dict:
        """统一循环意外逸出时，从内存态恢复真实公开诊断。"""
        state = context.state
        text, blocks = _verified_failure_output(state)
        logs = self.instrumentation.logs[context.log_start :]
        events = state.tool_events[context.event_start :]
        failure = self.instrumentation.describe_failure(exc, context.log_start)
        if not state.history_turns or state.history_turns[-1].get("turn") != state.turn_index:
            state.remember_turn(message, text, events)
        context.history = build_compact_history(state)
        return {
            "message": message,
            "status": "failed",
            "answer": text,
            "blocks": blocks,
            "error": f"{type(exc).__name__}: {exc}",
            "error_details": failure,
            "solve_error": f"{type(exc).__name__}: {exc}",
            "solve_failure": failure,
            "duration_ms": int((perf_counter() - started) * 1000),
            "usage": _aggregate_text_usage(
                logs,
                state.ledger.active_text_requests,
                state.ledger.active_tool_calls,
            ),
            "budget": state.ledger.snapshot(),
            "tool_calls": events,
            "model_calls": [asdict(item) for item in logs],
            "context": {"history_turns": len(state.history_turns)},
            "finalization": self.instrumentation.finalization_snapshot(),
        }

    async def cancel_turn(self, context: UnifiedConversationContext) -> dict:
        state = context.state
        state.instrumentation.finalize_status = "cancelled"
        text, blocks = _verified_failure_output(state)
        current_events = state.tool_events[context.event_start :]
        return {
            "answer": text,
            "blocks": blocks,
            "tool_calls": current_events,
            "model_calls": [
                asdict(item) for item in state.instrumentation.logs[context.log_start :]
            ],
            "budget": state.ledger.snapshot(),
            "context": {"history_turns": len(state.history_turns)},
            "finalization": state.instrumentation.finalization_snapshot(),
            "persistence": context.persistence,
        }


def _persistence_failure(exc: Exception) -> dict:
    chain = []
    current: BaseException | None = exc
    while current is not None and len(chain) < 4:
        chain.append({"type": type(current).__name__, "message": str(current)[:4_000]})
        current = current.__cause__ or current.__context__
    return {
        "status": "failed",
        "category": "run_persistence",
        "message": str(exc)[:4_000],
        "exception_chain": chain,
    }
