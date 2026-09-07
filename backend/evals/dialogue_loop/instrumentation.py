"""实验进程内的模型预算包装；不修改共享业务模块。"""

from __future__ import annotations

import importlib
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from time import perf_counter
from typing import Any

from pydantic_ai.models import Model

from evals.dialogue_loop.core import BudgetLedger


@dataclass
class InvocationLog:
    kind: str
    provider: str
    model: str | None
    duration_ms: int
    usage: dict | None
    error: str | None


@dataclass
class Instrumentation:
    ledger: BudgetLedger
    logs: list[InvocationLog] = field(default_factory=list)


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
        await self.state.ledger.reserve_text()
        started = perf_counter()
        try:
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
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
    }
