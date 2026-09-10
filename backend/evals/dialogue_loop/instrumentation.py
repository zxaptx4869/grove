"""实验进程内的模型预算包装；不修改共享业务模块。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from math import ceil
from time import perf_counter
from typing import Any

from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_core import to_jsonable_python

from evals.dialogue_loop.core import (
    BATCH_TEXT_REQUESTS,
    FINALIZE_SECONDS,
    INPUT_ESTIMATE_METHOD,
    INPUT_ESTIMATE_SOFT_LIMIT,
    INPUT_ESTIMATE_VERSION,
    MODEL_INPUT_TOKENS_LIMIT,
    PER_TURN_TEXT_REQUESTS,
    BudgetExceeded,
    BudgetLedger,
    DialogueAnswer,
)

FINALIZE_INSTRUCTION = (
    "实验求解阶段已到停止边界。不得再调用资料工具；请仅使用已取得的材料，"
    "在本次预留请求内给出完整回答。无法完成的部分必须明确说明限制。"
)


class FinalizeRequired(RuntimeError):
    """求解阶段已到停止点，必须转入独立收尾阶段。"""


class FinalizeToolAttempted(RuntimeError):
    """独立 finalizer 输出了未注册的资料工具调用。"""


@dataclass(frozen=True)
class InputEstimate:
    tokens: int
    components: dict[str, int | str]


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
    finalize_reason: str | None = None
    request_scope: str = "unknown"
    estimate_components: dict | None = None
    actual_input_tokens: int | None = None
    estimate_ratio: float | None = None
    finish_reason: str | None = None
    public_response: dict | None = None
    response_validation: dict | None = None
    error_kind: str | None = None
    error_chain: list[dict] = field(default_factory=list)


@dataclass
class Instrumentation:
    ledger: BudgetLedger
    logs: list[InvocationLog] = field(default_factory=list)
    context_policy_enabled: bool = False
    phase: str = "solve"
    finalize_reason: str | None = None
    finalize_attempted: bool = False
    finalize_response_received: bool = False
    finalize_status: str = "not_needed"
    finalize_error: str | None = None
    finalize_failure: dict | None = None
    validation_failures: list[dict] = field(default_factory=list)
    activity_callback: Callable[[str], None] | None = field(default=None, repr=False)

    def emit_activity(self, stage: str) -> None:
        """发布可验证的执行阶段，不包含模型思考内容。"""
        if self.activity_callback is not None:
            self.activity_callback(stage)

    def begin_turn(self) -> None:
        self.phase = "solve"
        self.finalize_reason = None
        self.finalize_attempted = False
        self.finalize_response_received = False
        self.finalize_status = "not_needed"
        self.finalize_error = None
        self.finalize_failure = None
        self.validation_failures.clear()

    def begin_finalize(self, reason: str) -> None:
        self.phase = "finalize"
        if self.finalize_reason is None:
            self.finalize_reason = reason
        if self.finalize_status == "not_needed":
            self.finalize_status = "pending"

    def complete_finalize(self) -> None:
        if self.finalize_attempted:
            self.finalize_status = "completed"
            self.finalize_error = None
            self.finalize_failure = None

    def record_validation_failure(
        self, category: str, message: str, candidate: dict | None = None
    ) -> None:
        self.validation_failures.append(
            {
                "category": category,
                "message": message[:4_000],
                "candidate": _bounded_public_value(candidate) if candidate else None,
                "log_index": max(len(self.logs) - 1, 0),
            }
        )

    def describe_failure(self, exc: BaseException, log_start: int = 0) -> dict:
        logs = self.logs[log_start:]
        validation = next(
            (
                item
                for item in reversed(self.validation_failures)
                if item.get("log_index", -1) >= log_start
            ),
            None,
        )
        response_log = next(
            (item for item in reversed(logs) if item.public_response is not None), None
        )
        latest_error = next(
            (
                (index + log_start, item)
                for index, item in reversed(list(enumerate(logs)))
                if item.error_kind in {"provider", "timeout", "cancelled"}
            ),
            None,
        )
        if isinstance(exc, TimeoutError):
            category = "timeout"
            validation = None
        elif latest_error and (
            validation is None or latest_error[0] > validation.get("log_index", -1)
        ):
            category = latest_error[1].error_kind
            validation = None
        elif validation is not None:
            category = validation["category"]
        elif isinstance(exc, BudgetExceeded):
            category = "budget"
        elif response_log and response_log.error_kind == "truncated":
            category = "truncated"
        elif response_log and response_log.response_validation:
            category = response_log.response_validation["category"]
            validation = response_log.response_validation
        else:
            category = "unknown"
        return {
            "category": category,
            "message": (validation or {}).get("message") or str(exc)[:4_000],
            "exception_chain": _exception_chain(exc),
            "validation": validation,
            "public_response": response_log.public_response if response_log else None,
        }

    def finalization_snapshot(self) -> dict:
        return {
            "reason": self.finalize_reason,
            "attempted": self.finalize_attempted,
            "response_received": self.finalize_response_received,
            "status": self.finalize_status,
            "error": self.finalize_error,
            "failure": self.finalize_failure,
            "seconds_limit": FINALIZE_SECONDS,
        }


def _json_bytes(value: Any) -> int:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return len(raw.encode("utf-8"))


def _project_tool(tool) -> dict:
    function = {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": tool.parameters_json_schema,
    }
    if tool.strict:
        function["strict"] = True
    return {"type": "function", "function": function}


def _project_messages(messages, model_request_parameters=None) -> tuple[list[dict], int]:
    """构造与当前 OpenAI Chat Provider 字段接近的仅长度计算投影。"""
    projected: list[dict] = []
    instruction_bytes = 0
    if model_request_parameters is not None:
        for part in model_request_parameters.instruction_parts or []:
            content = part.content
            projected.append({"role": "system", "content": content})
            instruction_bytes += len(content.encode("utf-8"))
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    projected.append({"role": "system", "content": part.content})
                elif isinstance(part, UserPromptPart):
                    projected.append(
                        {
                            "role": "user",
                            "content": part.content
                            if isinstance(part.content, str)
                            else to_jsonable_python(part.content),
                        }
                    )
                elif isinstance(part, ToolReturnPart):
                    projected.append(
                        {
                            "role": "tool",
                            "tool_call_id": part.tool_call_id,
                            "content": part.model_response_str(),
                        }
                    )
                elif isinstance(part, RetryPromptPart):
                    projected.append(
                        {
                            "role": "tool" if part.tool_name else "user",
                            "tool_call_id": part.tool_call_id if part.tool_name else None,
                            "content": part.model_response(),
                        }
                    )
        elif isinstance(message, ModelResponse):
            response: dict[str, Any] = {"role": "assistant"}
            text = "".join(
                part.content for part in message.parts if isinstance(part, TextPart)
            )
            calls = [
                {
                    "id": part.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": part.tool_name,
                        "arguments": part.args_as_json_str(),
                    },
                }
                for part in message.parts
                if isinstance(part, ToolCallPart)
            ]
            if text:
                response["content"] = text
            if calls:
                response["tool_calls"] = calls
            # ThinkingPart 不进入报告；这里只按字节长度占位，避免门禁漏算历史推理。
            hidden_bytes = sum(
                len(str(getattr(part, "content", "")).encode("utf-8"))
                for part in message.parts
                if not isinstance(part, TextPart | ToolCallPart)
            )
            if hidden_bytes:
                response["_hidden_content_size"] = "x" * hidden_bytes
            if len(response) > 1:
                projected.append(response)
        else:
            projected.append(
                {"role": "unknown", "content": to_jsonable_python(message)}
            )
    return projected, instruction_bytes


def estimate_input(messages, model_request_parameters=None) -> InputEstimate:
    """估算实际 Provider 请求形状，并保留不含正文的长度组件。"""
    projected_messages, instruction_bytes = _project_messages(
        messages, model_request_parameters
    )
    instruction_contents = (
        [part.content for part in model_request_parameters.instruction_parts or []]
        if model_request_parameters is not None
        else []
    )
    historical_system_count = sum(
        isinstance(part, SystemPromptPart)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
    )
    tools = []
    if model_request_parameters is not None:
        tools = [
            _project_tool(tool)
            for tool in (
                *model_request_parameters.function_tools,
                *model_request_parameters.output_tools,
            )
        ]
    payload = {"messages": projected_messages}
    if tools:
        payload["tools"] = tools
    payload_bytes = _json_bytes(payload)
    message_bytes = _json_bytes(projected_messages)
    tool_schema_bytes = _json_bytes(tools) if tools else 0
    fixed_overhead = 64
    message_overhead = len(projected_messages) * 4
    tool_overhead = len(tools) * 8
    tokens = ceil(payload_bytes / 3) + fixed_overhead + message_overhead + tool_overhead
    return InputEstimate(
        tokens=tokens,
        components={
            "version": INPUT_ESTIMATE_VERSION,
            "payload_utf8_bytes": payload_bytes,
            "instruction_utf8_bytes": instruction_bytes,
            "instruction_count": len(instruction_contents),
            "instruction_sha256": hashlib.sha256(
                "\n".join(instruction_contents).encode("utf-8")
            ).hexdigest(),
            "historical_system_count": historical_system_count,
            "message_json_utf8_bytes": message_bytes,
            "tool_schema_json_utf8_bytes": tool_schema_bytes,
            "message_count": len(projected_messages),
            "tool_count": len(tools),
            "fixed_overhead_tokens": fixed_overhead,
            "message_overhead_tokens": message_overhead,
            "tool_overhead_tokens": tool_overhead,
        },
    )


def estimate_input_tokens(messages, model_request_parameters=None) -> int:
    """提供可复现的保守长度门禁；它不是 Provider tokenizer。"""
    return estimate_input(messages, model_request_parameters).tokens


def _bounded_public_value(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return "<depth-limit>"
    if isinstance(value, str):
        return value if len(value) <= 8_000 else value[:8_000] + "\n<response-truncated>"
    if isinstance(value, dict):
        return {
            str(key): _bounded_public_value(item, depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_public_value(item, depth + 1) for item in value[:100]]
    return to_jsonable_python(value)


def _public_response(response: ModelResponse) -> dict:
    """只保留公开文本和结构化调用，显式忽略隐藏推理及 Provider 元数据。"""
    parts = []
    for part in response.parts:
        if isinstance(part, TextPart):
            parts.append({"kind": "text", "text": _bounded_public_value(part.content)})
        elif isinstance(part, ToolCallPart):
            try:
                arguments = part.args_as_dict()
            except Exception:
                arguments = part.args_as_json_str()
            parts.append(
                {
                    "kind": "tool_call",
                    "tool_name": part.tool_name,
                    "tool_call_id": part.tool_call_id,
                    "arguments": _bounded_public_value(arguments),
                }
            )
    return {"parts": parts}


def _exception_chain(exc: BaseException, limit: int = 8) -> list[dict]:
    chain = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < limit:
        seen.add(id(current))
        message = str(current)
        chain.append(
            {
                "type": type(current).__name__,
                "message": message[:4_000]
                + ("<exception-truncated>" if len(message) > 4_000 else ""),
            }
        )
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain


def _schema_diagnostic(
    response: ModelResponse,
    output_tool_names: set[str],
    function_tool_names: set[str],
    allow_text_output: bool,
) -> dict | None:
    output_seen = False
    for part in response.parts:
        if not isinstance(part, ToolCallPart) or part.tool_name not in output_tool_names:
            continue
        output_seen = True
        try:
            DialogueAnswer.model_validate(part.args_as_dict())
        except (ValidationError, ValueError, TypeError) as exc:
            errors = []
            if isinstance(exc, ValidationError):
                errors = [
                    {
                        "location": list(item["loc"]),
                        "type": item["type"],
                        "message": item["msg"],
                    }
                    for item in exc.errors(include_url=False, include_input=False)
                ]
            return {
                "category": "schema_validation",
                "message": str(exc)[:4_000],
                "errors": errors,
            }
    if output_seen:
        return None
    has_function_call = any(
        isinstance(part, ToolCallPart) and part.tool_name in function_tool_names
        for part in response.parts
    )
    if not allow_text_output and not has_function_call:
        return {
            "category": "schema_validation",
            "message": "模型响应没有调用要求的结构化输出工具",
            "errors": [],
        }
    return None


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


def _actual_input(usage: dict | None) -> int | None:
    if not usage:
        return None
    value = usage.get("input_tokens")
    return int(value) if isinstance(value, int | float) and value > 0 else None


def _estimate_ratio(estimate: int, actual: int | None) -> float | None:
    return round(estimate / actual, 6) if actual else None


class BudgetedModel(Model):
    """对每次底层 request 派发前预留额度，包括框架结构化重试。"""

    def __init__(
        self, wrapped: Model, state: Instrumentation, request_scope: str = "unknown"
    ):
        super().__init__(settings=wrapped.settings, profile=wrapped.profile)
        self.wrapped = wrapped
        self.state = state
        self.request_scope = request_scope

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
        projected = estimate_input(messages, model_request_parameters)
        estimate = projected.tokens
        turn_requests = self.state.ledger.active_text_requests
        batch_requests = self.state.ledger.batch_text_requests
        reason = None
        if self.state.phase == "finalize":
            reason = self.state.finalize_reason or "explicit_finalize"
        elif turn_requests > 0 and estimate >= INPUT_ESTIMATE_SOFT_LIMIT:
            reason = "input_soft_limit"
        elif (
            turn_requests >= PER_TURN_TEXT_REQUESTS - 1
            or batch_requests >= BATCH_TEXT_REQUESTS - 1
        ):
            reason = "text_request_budget"
        finalize_only = self.state.context_policy_enabled and reason is not None
        if finalize_only:
            entering_finalize = self.state.phase != "finalize"
            self.state.begin_finalize(reason)
            if entering_finalize:
                self.state.logs.append(
                    InvocationLog(
                        kind="finalize_transition",
                        provider=str(self.wrapped.system),
                        model=self.wrapped.model_name,
                        duration_ms=0,
                        usage=None,
                        error="达到求解停止点，当前求解请求未派发",
                        projected_input_tokens=estimate,
                        estimated_input_tokens=estimate,
                        input_estimate_method=INPUT_ESTIMATE_METHOD,
                        finalize_only=False,
                        finalize_reason=self.state.finalize_reason,
                        request_scope=self.request_scope,
                        estimate_components=projected.components,
                        error_kind="budget_boundary",
                    )
                )
                raise FinalizeRequired(self.state.finalize_reason or "finalize")
            if self.state.finalize_attempted:
                if self.state.finalize_response_received:
                    self.state.finalize_status = "invalid_output"
                    error = "收尾输出非法，已禁止第二次模型收尾请求"
                else:
                    error = "收尾请求已经派发，已禁止额外模型请求"
                self.state.finalize_error = error
                self.state.logs.append(
                    InvocationLog(
                        kind="text_not_dispatched",
                        provider=str(self.wrapped.system),
                        model=self.wrapped.model_name,
                        duration_ms=0,
                        usage=None,
                        error=error,
                        projected_input_tokens=estimate,
                        estimated_input_tokens=estimate,
                        input_estimate_method=INPUT_ESTIMATE_METHOD,
                        finalize_only=True,
                        finalize_reason=self.state.finalize_reason,
                        request_scope=self.request_scope,
                        estimate_components=projected.components,
                        error_kind="reference_validation"
                        if self.state.validation_failures
                        else "budget",
                    )
                )
                raise BudgetExceeded(error)
        dispatched_messages = _finalize_messages(messages) if finalize_only else messages
        dispatched_parameters = (
            replace(model_request_parameters, function_tools=[])
            if finalize_only
            else model_request_parameters
        )
        dispatched = estimate_input(dispatched_messages, dispatched_parameters)
        dispatched_estimate = dispatched.tokens
        if self.state.context_policy_enabled and dispatched_estimate > MODEL_INPUT_TOKENS_LIMIT:
            stage_name = "预算收尾" if finalize_only else "完整请求"
            error = (
                f"{stage_name}输入长度估算 {dispatched_estimate} 超过 "
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
                    finalize_reason=self.state.finalize_reason if finalize_only else None,
                    request_scope=self.request_scope,
                    estimate_components=dispatched.components,
                    error_kind="budget",
                )
            )
            if finalize_only:
                self.state.finalize_status = "not_dispatched"
                self.state.finalize_error = error
            raise BudgetExceeded(error)
        try:
            await self.state.ledger.reserve_text()
        except BudgetExceeded as exc:
            error = f"{type(exc).__name__}: {exc}"
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
                    finalize_reason=self.state.finalize_reason if finalize_only else None,
                    request_scope=self.request_scope,
                    estimate_components=dispatched.components,
                    error_kind="budget",
                )
            )
            if finalize_only:
                self.state.finalize_status = "not_dispatched"
                self.state.finalize_error = error
            raise
        if finalize_only:
            self.state.finalize_attempted = True
            self.state.finalize_status = "dispatched"
        self.state.emit_activity("finalizing" if finalize_only else "organizing")
        started = perf_counter()
        try:
            response = await self.wrapped.request(
                dispatched_messages, model_settings, dispatched_parameters
            )
        except asyncio.CancelledError as exc:
            self.state.logs.append(
                InvocationLog(
                    kind="text",
                    provider=str(self.wrapped.system),
                    model=self.wrapped.model_name,
                    duration_ms=int((perf_counter() - started) * 1000),
                    usage=None,
                    error="CancelledError: 模型请求被取消",
                    projected_input_tokens=estimate,
                    estimated_input_tokens=dispatched_estimate,
                    input_estimate_method=INPUT_ESTIMATE_METHOD,
                    finalize_only=finalize_only,
                    finalize_reason=self.state.finalize_reason if finalize_only else None,
                    request_scope=self.request_scope,
                    estimate_components=dispatched.components,
                    error_kind="cancelled",
                    error_chain=_exception_chain(exc),
                )
            )
            if finalize_only:
                self.state.finalize_status = "cancelled"
                self.state.finalize_error = "CancelledError: 收尾请求被取消"
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.state.logs.append(
                InvocationLog(
                    kind="text",
                    provider=str(self.wrapped.system),
                    model=self.wrapped.model_name,
                    duration_ms=int((perf_counter() - started) * 1000),
                    usage=None,
                    error=error,
                    projected_input_tokens=estimate,
                    estimated_input_tokens=dispatched_estimate,
                    input_estimate_method=INPUT_ESTIMATE_METHOD,
                    finalize_only=finalize_only,
                    finalize_reason=self.state.finalize_reason if finalize_only else None,
                    request_scope=self.request_scope,
                    estimate_components=dispatched.components,
                    error_kind="timeout" if isinstance(exc, TimeoutError) else "provider",
                    error_chain=_exception_chain(exc),
                )
            )
            if finalize_only:
                self.state.finalize_status = (
                    "timed_out" if isinstance(exc, TimeoutError) else "failed"
                )
                self.state.finalize_error = error
            raise
        if finalize_only:
            self.state.finalize_response_received = True
            self.state.finalize_status = "response_received"
        usage = _usage_dict(getattr(response, "usage", None))
        actual_input = _actual_input(usage)
        finish_reason = to_jsonable_python(getattr(response, "finish_reason", None))
        public_response = _public_response(response)
        unexpected_finalize_tools = (
            [
                part.tool_name
                for part in response.parts
                if isinstance(part, ToolCallPart)
                and part.tool_name
                not in {tool.name for tool in dispatched_parameters.output_tools}
            ]
            if finalize_only
            else []
        )
        response_validation = (
            {
                "category": "finalize_tool_attempted",
                "message": (
                    "独立收尾响应尝试调用未注册资料工具："
                    + "、".join(unexpected_finalize_tools)
                ),
                "errors": [{"tool_name": name} for name in unexpected_finalize_tools],
            }
            if unexpected_finalize_tools
            else (
            _schema_diagnostic(
                response,
                {tool.name for tool in dispatched_parameters.output_tools},
                {tool.name for tool in dispatched_parameters.function_tools},
                dispatched_parameters.allow_text_output,
            )
            if self.request_scope == "dialogue_agent"
            else None
            )
        )
        self.state.logs.append(
            InvocationLog(
                kind="text",
                provider=str(self.wrapped.system),
                model=self.wrapped.model_name,
                duration_ms=int((perf_counter() - started) * 1000),
                usage=usage,
                error=None,
                projected_input_tokens=estimate,
                estimated_input_tokens=dispatched_estimate,
                input_estimate_method=INPUT_ESTIMATE_METHOD,
                finalize_only=finalize_only,
                finalize_reason=self.state.finalize_reason if finalize_only else None,
                request_scope=self.request_scope,
                estimate_components=dispatched.components,
                actual_input_tokens=actual_input,
                estimate_ratio=_estimate_ratio(dispatched_estimate, actual_input),
                finish_reason=finish_reason,
                public_response=public_response,
                response_validation=response_validation,
                error_kind=(
                    "finalize_tool_attempted"
                    if unexpected_finalize_tools
                    else "truncated"
                    if finish_reason in {"length", "max_tokens"}
                    else None
                ),
            )
        )
        if unexpected_finalize_tools:
            error = response_validation["message"]
            self.state.finalize_status = "tool_attempted"
            self.state.finalize_error = error
            self.state.finalize_failure = {
                "category": "finalize_tool_attempted",
                "message": error,
                "exception_chain": [],
                "validation": response_validation,
                "public_response": public_response,
            }
            raise FinalizeToolAttempted(error)
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
        scope = "tool_internal" if state.context_policy_enabled else "legacy_pipeline"
        return BudgetedModel(model, state, request_scope=scope)

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
                    request_scope="tool_internal_embedding",
                    error_kind="provider",
                    error_chain=_exception_chain(exc),
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
                request_scope="tool_internal_embedding",
                error_kind="provider" if result.error else None,
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
        "provider_shaped_estimates": True,
        "request_scopes_recorded": True,
        "public_response_diagnostics": True,
        "v2_context_policy_enabled": state.context_policy_enabled,
    }
