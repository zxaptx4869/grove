"""实验进程内的模型预算包装；不修改共享业务模块。"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from math import ceil
from time import perf_counter
from typing import Any

from pydantic_ai.messages import ModelRequest, SystemPromptPart
from pydantic_ai.models import Model
from pydantic_core import to_jsonable_python

from evals.dialogue_loop.core import (
    INPUT_ESTIMATE_METHOD,
    INPUT_ESTIMATE_SOFT_LIMIT,
    MODEL_INPUT_TOKENS_LIMIT,
    PER_TURN_TEXT_REQUESTS,
    BudgetExceeded,
    BudgetLedger,
)

FINALIZE_INSTRUCTION = (
    "实验输入预算已接近资料阶段阈值。不得再调用资料工具；请仅使用已取得的材料，"
    "在本次预留请求内给出完整回答。无法完成的部分必须明确说明限制。"
)


@dataclass
class InvocationLog:
    kind: str
    provider: str
    model: str | None
    duration_ms: int
    usage: dict | None
    error: str | None
    projected_input_tokens: int | None = None
    estimated_input_tokens: int | None = None
    input_estimate_method: str | None = None
    finalize_only: bool = False


@dataclass
class Instrumentation:
    ledger: BudgetLedger
    logs: list[InvocationLog] = field(default_factory=list)
    context_policy_enabled: bool = False


def estimate_input_tokens(messages, model_request_parameters=None) -> int:
    """提供可复现的保守长度门禁；它不是 Provider tokenizer。"""
    value = {"messages": messages}
    if model_request_parameters is not None:
        value["request_parameters"] = model_request_parameters
    raw = json.dumps(to_jsonable_python(value), ensure_ascii=False, separators=(",", ":"))
    return ceil(len(raw.encode("utf-8")) / 3)


def _finalize_messages(messages):
    return [
        *messages,
        ModelRequest(parts=[SystemPromptPart(content=FINALIZE_INSTRUCTION)]),
    ]


def _usage_dict(value: Any) -> dict | None:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return None


class BudgetedModel(Model):
    """对每次底层 request 派发前预留额度，包括框架结构化重试。"""

    def __init__(self, wrapped: Model, state: Instrumentation):
        super().__init__(settings=wrapped.settings, profile=wrapped.profile)
        self.wrapped = wrapped
        self.state = state

    @property
    def model_name(self) -> str:
        return self.wrapped.model_name

    @property
    def system(self) -> str:
        return self.wrapped.system

    @property
    def base_url(self) -> str | None:
        return self.wrapped.base_url

    async def request(self, messages, model_settings, model_request_parameters):
        estimate = estimate_input_tokens(messages, model_request_parameters)
        finalize_only = self.state.context_policy_enabled and (
            estimate >= INPUT_ESTIMATE_SOFT_LIMIT
            or self.state.ledger.active_text_requests >= PER_TURN_TEXT_REQUESTS - 1
        )
        dispatched_messages = _finalize_messages(messages) if finalize_only else messages
        dispatched_parameters = (
            replace(model_request_parameters, function_tools=[])
            if finalize_only
            else model_request_parameters
        )
        dispatched_estimate = estimate_input_tokens(dispatched_messages, dispatched_parameters)
        if self.state.context_policy_enabled and dispatched_estimate > MODEL_INPUT_TOKENS_LIMIT:
            error = (
                f"预算收尾输入长度估算 {dispatched_estimate} 超过 "
                f"{MODEL_INPUT_TOKENS_LIMIT}，未派发请求"
            )
            self.state.logs.append(
                InvocationLog(
                    kind="text_not_dispatched",
                    provider=str(self.wrapped.system),
                    model=self.wrapped.model_name,
                    duration_ms=0,
                    usage=None,
                    error=error,
                    projected_input_tokens=estimate,
                    estimated_input_tokens=dispatched_estimate,
                    input_estimate_method=INPUT_ESTIMATE_METHOD,
                    finalize_only=finalize_only,
                )
            )
            raise BudgetExceeded(error)
        await self.state.ledger.reserve_text()
        started = perf_counter()
        try:
            response = await self.wrapped.request(
                dispatched_messages, model_settings, dispatched_parameters
            )
        except Exception as exc:
            self.state.logs.append(
                InvocationLog(
                    kind="text",
                    provider=str(self.wrapped.system),
                    model=self.wrapped.model_name,
                    duration_ms=int((perf_counter() - started) * 1000),
                    usage=None,
                    error=f"{type(exc).__name__}: {exc}",
                    projected_input_tokens=estimate,
                    estimated_input_tokens=dispatched_estimate,
                    input_estimate_method=INPUT_ESTIMATE_METHOD,
                    finalize_only=finalize_only,
                )
            )
            raise
        self.state.logs.append(
            InvocationLog(
                kind="text",
                provider=str(self.wrapped.system),
                model=self.wrapped.model_name,
                duration_ms=int((perf_counter() - started) * 1000),
                usage=_usage_dict(getattr(response, "usage", None)),
                error=None,
                projected_input_tokens=estimate,
                estimated_input_tokens=dispatched_estimate,
                input_estimate_method=INPUT_ESTIMATE_METHOD,
                finalize_only=finalize_only,
            )
        )
        return response

    async def count_tokens(self, messages, model_settings, model_request_parameters):
        return await self.wrapped.count_tokens(messages, model_settings, model_request_parameters)


def install_instrumentation(state: Instrumentation) -> dict:
    """导入旧执行链后替换其局部函数引用，返回覆盖核对摘要。"""
    ai_models = importlib.import_module("app.services.ai_models")
    embedding = importlib.import_module("app.services.embedding")
    original_get_text_model = ai_models.get_text_model
    original_encode_text = embedding.encode_text

    # 旧流程按开关动态导入；预先加载所有可能的模型模块，之后统一替换已绑定引用。
    module_names = (
        "app.agents.basis",
        "app.agents.composite_answer",
        "app.agents.coverage_repair",
        "app.agents.investigation",
        "app.agents.knowledge_agent",
        "app.agents.knowledge_context",
        "app.agents.result_mode",
        "app.agents.semantic",
        "app.agents.structured_query",
        "app.services.vector_search",
        "app.services.knowledge_agent.runner",
    )
    for name in module_names:
        importlib.import_module(name)

    async def budgeted_get_text_model(db, workspace_id: int):
        model = await original_get_text_model(db, workspace_id)
        return BudgetedModel(model, state)

    async def budgeted_encode_text(db, workspace_id: int, text: str, **kwargs):
        await state.ledger.reserve_embedding()
        started = perf_counter()
        try:
            result = await original_encode_text(db, workspace_id, text, **kwargs)
        except Exception as exc:
            state.logs.append(
                InvocationLog(
                    kind="embedding",
                    provider="doubao",
                    model=kwargs.get("model"),
                    duration_ms=int((perf_counter() - started) * 1000),
                    usage=None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise
        state.logs.append(
            InvocationLog(
                kind="embedding",
                provider=result.provider,
                model=result.model,
                duration_ms=int((perf_counter() - started) * 1000),
                usage=None,
                error=result.error,
            )
        )
        return result

    patched_text = []
    patched_embedding = []
    for name, module in list(sys.modules.items()):
        if not name.startswith("app.") or module is None:
            continue
        if getattr(module, "get_text_model", None) is original_get_text_model:
            module.get_text_model = budgeted_get_text_model
            patched_text.append(name)
        if getattr(module, "encode_text", None) is original_encode_text:
            module.encode_text = budgeted_encode_text
            patched_embedding.append(name)
    ai_models.get_text_model = budgeted_get_text_model
    embedding.encode_text = budgeted_encode_text
    return {
        "text_modules": sorted(patched_text),
        "embedding_modules": sorted(patched_embedding),
        "text_dispatch_counted": True,
        "embedding_dispatch_counted": True,
        "framework_retries_counted": True,
        "input_estimates_recorded": True,
        "v2_context_policy_enabled": state.context_policy_enabled,
    }
