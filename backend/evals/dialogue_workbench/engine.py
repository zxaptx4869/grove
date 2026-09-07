"""对现有统一对话循环的薄运行时包装。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
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
    _verified_failure_output,
    build_agent,
    run_turn,
)


@dataclass
class UnifiedConversationContext:
    state: LoopState
    history: list[ModelMessage]
    event_start: int = 0
    log_start: int = 0


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

    @classmethod
    async def create(cls, identity: dict[str, Any]) -> UnifiedLoopEngine:
        from app.db.session import async_session_factory
        from app.services import ai_models

        ledger = BudgetLedger()
        instrumentation = Instrumentation(ledger)
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
        conversation_id = await _create_conversation(
            self.identity["workspace_id"], self.identity["user_id"]
        )
        state = LoopState(
            workspace_id=self.identity["workspace_id"],
            user_id=self.identity["user_id"],
            conversation_id=conversation_id,
            ledger=self.ledger,
            instrumentation=self.instrumentation,
        )
        return UnifiedConversationContext(state=state, history=[])

    async def run_turn(
        self,
        context: UnifiedConversationContext,
        message: str,
        turn_number: int,
        stage,
    ) -> dict:
        run_id = await _submit_turn(context.state.conversation_id, message, turn_number)
        context.event_start = len(context.state.tool_events)
        context.log_start = len(self.instrumentation.logs)
        context.state.begin_turn(run_id, message)
        self.instrumentation.activity_callback = stage
        try:
            turn, context.history = await run_turn(
                self.agent, context.state, message, context.history
            )
        except asyncio.CancelledError:
            await _finish_new_run(run_id, "", "用户取消")
            raise
        finally:
            self.instrumentation.activity_callback = None
        await _finish_new_run(run_id, turn["answer"], turn["error"])
        return turn

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
        }
