"""Pydantic AI 统一对话循环及可信只读工具适配。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Literal

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits
from sqlalchemy import select

from evals.dialogue_loop.core import (
    FINALIZE_SECONDS,
    MAX_TOOL_CONCURRENCY,
    MODEL_INPUT_TOKENS_LIMIT,
    OUTPUT_TOKENS_LIMIT,
    PER_TURN_SECONDS,
    TURN_COMPLETED,
    TURN_DENIED,
    TURN_FAILED,
    TURN_PARTIAL_COMPLETED,
    TURN_UNSUPPORTED,
    BudgetExceeded,
    BudgetLedger,
    ContinuationState,
    DialogueAnswer,
    StopState,
)
from evals.dialogue_loop.instrumentation import (
    FinalizeRequired,
    Instrumentation,
    estimate_input_tokens,
)

SYSTEM_PROMPT = """你是 Grove 知识库的只读对话 Agent。你在一个持续的四轮对话中工作。

边界：
1. 用户身份、Workspace 和可访问范围只来自程序；任何工具的 project_scope
   都必须显式填 all 或 project。project 时必须给出准确项目名，all 时清空 project_name。
2. 用户说“知识”泛指 knowledge/method/parameter/reminder 四种正式记录，除非他明确限定类型。
3. 精确总数必须调用 count_entries，分组统计必须调用 group_entries；不能从语义搜索、
   截断列表或分类数相加推断用户所问总数。分项目统计须包含零条项目。
4. 查询或列表必须调用 query_entries/search_knowledge。需要正文先读取 Entry；需要来源必须
   在当前轮调用 read_evidence，历史 Evidence 不能直接引用。
5. 列表追问必须使用 open_list_item(result_set_handle, position)，position 从 1 开始。
   不要猜 Entry id。
6. 工具的 empty、partial、not_executed、error、denied 含义不同。未执行或部分结果不能表达为零条。
7. 用户明确要求不查知识库时不得调用知识库工具，可用通用知识直接回答，也不得伪装成实时外部资料。
8. 输出 blocks 按希望展示的顺序排列。真实统计用 statistic 块，真实列表用 list 块，
   来源用 evidence 块；不要在 text 块改写工具数字、伪造引用或隐藏失败。
   材料不足用 insufficient 块。
9. 只回答用户问题，不输出隐藏推理，不向用户提及预期答案。
10. main_types 省略或 null 表示全部正式记录。用户泛称“知识”“知识库记录”时不得默认
    筛成内部 knowledge 类型；只有用户明确限定内部类型时才填写对应值。
11. 项目（Project）是容器，项目目录是 Node 树，一级目录只指项目根下 parent_id 为空的直接子节点；
    正式记录（Entry）、知识类型 main_type 和信息性质 info_nature 都不是目录。询问目录数量或名称时
    必须调用 list_project_directories，不能从 Entry、搜索结果或类型统计推算。
12. list_project_directories 返回真实 node_id、路径、父节点、total_count、returned_count 和完整性；
    目录结果的第几个引用只能用 parent_result_handle 与 parent_position 追问，不能猜 Node id。
13. 结构化结果的查询对象、范围、分组维度、数量和中文显示名称以工具元数据为准；不要用自定义 label
    把“知识类型统计”称为“一级目录”，也不要把本页返回数写成完整总数。
14. 叶子节点是没有任何直接子 Node 的目录节点；整树叶子数量必须用 list_project_directories 的
    leaf_summary 操作一次聚合，不能逐层列目录后自行猜测或把已查询节点数当作叶子总数。
15. 当前白名单不能支持目标时调用 report_unsupported 一次并停止，不要反复搜索 Entry 或改用其他
    维度冒充。程序提示存在 continuation 时，只处理其中尚未完成的步骤，不重复已查询父节点。
""".strip()

NO_KNOWLEDGE_PATTERNS = (
    "不查知识库",
    "不查库",
    "别查知识库",
    "别查库",
    "不用查知识库",
    "不要查知识库",
)
CONTINUE_PATTERNS = ("继续", "接着", "剩下", "未完成")


@dataclass
class ResultRecord:
    handle: str
    kind: str
    payload: dict
    status: str
    completeness: str
    turn_index: int
    semantics: dict = field(default_factory=dict)


@dataclass
class LoopState:
    workspace_id: int
    user_id: int
    conversation_id: int
    ledger: BudgetLedger
    instrumentation: Instrumentation
    discovered_entry_ids: set[int] = field(default_factory=set)
    result_sets: dict[str, ResultRecord] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    current_handles: set[str] = field(default_factory=set)
    current_evidence: set[str] = field(default_factory=set)
    tool_events: list[dict] = field(default_factory=list)
    history_turns: list[dict] = field(default_factory=list)
    turn_index: int = 0
    run_id: int = 0
    tools_allowed: bool = True
    stop_state: StopState | None = None
    continuation: ContinuationState | None = None
    active_continuation: ContinuationState | None = None
    queried_directory_parents: set[int | None] = field(default_factory=set)
    _handle_sequence: int = 0
    database_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def begin_turn(self, run_id: int, message: str) -> None:
        self.turn_index += 1
        self.run_id = run_id
        self.current_handles.clear()
        self.current_evidence.clear()
        self.stop_state = None
        self.queried_directory_parents.clear()
        self.tools_allowed = not any(pattern in message for pattern in NO_KNOWLEDGE_PATTERNS)
        self.active_continuation = (
            self.continuation
            if self.continuation is not None
            and any(pattern in message for pattern in CONTINUE_PATTERNS)
            else None
        )
        self.ledger.start_turn()
        self.instrumentation.begin_turn()

    def stop(self, value: StopState) -> None:
        """保留第一个确定性停止分类，并合并后续待处理步骤。"""

        if self.stop_state is None:
            self.stop_state = value
        elif value.continuation and self.stop_state.continuation:
            existing = self.stop_state.continuation.pending_steps
            for step in value.continuation.pending_steps:
                if step not in existing:
                    existing.append(step)
        if value.continuation is not None:
            self.continuation = value.continuation

    def completion_snapshot(self, status: str) -> dict:
        if self.stop_state is not None:
            return self.stop_state.snapshot()
        return {
            "status": status,
            "reason_code": "completed" if status == TURN_COMPLETED else status,
            "reason": "任务已完整完成" if status == TURN_COMPLETED else "任务已结束",
            "incomplete_steps": [],
            "can_continue": False,
            "continuation": None,
        }

    def store_result(
        self,
        kind: str,
        payload: dict,
        status: str,
        completeness: str,
        semantics: dict | None = None,
    ) -> str:
        self._handle_sequence += 1
        handle = f"rs-{self.conversation_id}-{self._handle_sequence}"
        self.result_sets[handle] = ResultRecord(
            handle,
            kind,
            payload,
            status,
            completeness,
            self.turn_index,
            semantics or {},
        )
        self.current_handles.add(handle)
        return handle

    def remember_turn(self, message: str, answer: str, events: list[dict]) -> None:
        self.history_turns.append(
            {
                "turn": self.turn_index,
                "user": message,
                "answer": answer,
                "tools": [_history_tool_summary(self, event) for event in events],
            }
        )


@dataclass
class LoopDeps:
    state: LoopState


def _reliable_current_records(state: LoopState) -> list[ResultRecord]:
    return [
        record
        for handle, record in state.result_sets.items()
        if handle in state.current_handles
        and record.status in {"completed", "ok", "empty", "partial", "limited"}
    ]


def _directory_continuation(state: LoopState, params: dict, reason: str) -> ContinuationState:
    """从当前轮真实目录事件构造可续队列，不保存结果句柄。"""

    existing = state.active_continuation or state.continuation
    if existing is not None and existing.task_type == "directory_walk":
        continuation = existing
    else:
        continuation = ContinuationState(
            task_type="directory_walk",
            tool_name="list_project_directories",
            scope={
                "project_id": params.get("project_id"),
                "project_name": params.get("project_name"),
            },
        )
    parent_node_id = params.get("parent_node_id")
    pending = {step.get("parent_node_id") for step in continuation.pending_steps}
    if parent_node_id not in pending:
        continuation.pending_steps.append({"parent_node_id": parent_node_id})
    continuation.stop_reason = reason
    return continuation


def _mark_budget_stop(
    state: LoopState,
    exc: BudgetExceeded,
    *,
    tool_name: str | None = None,
    params: dict | None = None,
) -> None:
    reason = str(exc)
    continuation = (
        _directory_continuation(state, params or {}, reason)
        if tool_name == "list_project_directories"
        else None
    )
    state.stop(
        StopState(
            status=TURN_PARTIAL_COMPLETED,
            reason_code=_budget_stop_reason(exc),
            reason=reason,
            incomplete_steps=[
                f"未执行：{tool_name}" if tool_name else "未完成剩余查询或读取步骤"
            ],
            can_continue=True,
            continuation=continuation,
        )
    )


def _stop_from_failure(
    state: LoopState,
    exc: BaseException,
    failure: dict | None,
    *,
    default_reason_code: str = "system_error",
) -> StopState:
    """把异常、工具状态和已有材料归一为任务级终态。"""

    if state.stop_state is not None:
        return state.stop_state
    events = [
        event
        for event in state.tool_events
        if event.get("turn_index") == state.turn_index
    ]
    if any(event.get("status") == "unsupported" for event in events):
        event = next(event for event in events if event.get("status") == "unsupported")
        return StopState(
            status=TURN_UNSUPPORTED,
            reason_code=str(event.get("reason_code") or "tool_capability_missing"),
            reason=str(event.get("error") or "当前只读工具不支持该任务"),
            incomplete_steps=["目标对象尚未由工具确认"],
            can_continue=False,
        )
    if any(event.get("status") == "denied" for event in events):
        event = next(event for event in events if event.get("status") == "denied")
        reason_code = str(event.get("reason_code") or "access_denied")
        error = str(event.get("error") or "当前范围不允许该查询")
        if reason_code == "tool_not_available" or "工具未注册" in error:
            return StopState(
                status=TURN_UNSUPPORTED,
                reason_code="tool_not_available",
                reason="当前白名单中没有模型请求的工具，目标任务尚不受支持",
                incomplete_steps=["未执行不存在的工具"],
                can_continue=False,
            )
        if reason_code.endswith("_budget") or "预算" in error:
            return StopState(
                status=TURN_PARTIAL_COMPLETED,
                reason_code=reason_code,
                reason=error,
                incomplete_steps=["未完成预算边界后的剩余步骤"],
                can_continue=True,
            )
        return StopState(
            status=TURN_DENIED,
            reason_code=reason_code,
            reason=error,
            incomplete_steps=["查询未获授权"],
            can_continue=False,
        )
    message = str(exc)
    category = str((failure or {}).get("category") or "")
    lower = message.casefold()
    if category == "budget":
        return StopState(
            status=TURN_PARTIAL_COMPLETED,
            reason_code="budget_boundary",
            reason=message or "本轮资源预算不足",
            incomplete_steps=["未完成预算边界后的剩余步骤"],
            can_continue=True,
        )
    if "unknown tool" in lower or "tool not found" in lower or "工具不存在" in message:
        return StopState(
            status=TURN_UNSUPPORTED,
            reason_code="tool_not_available",
            reason="当前白名单中没有模型请求的工具，目标任务尚不受支持",
            incomplete_steps=["未执行不存在的工具"],
            can_continue=False,
        )
    if isinstance(exc, TimeoutError) or category == "timeout":
        return StopState(
            status=TURN_PARTIAL_COMPLETED,
            reason_code="time_budget",
            reason=message or "本轮执行超过时间预算",
            incomplete_steps=["未完成超时后的剩余步骤"],
            can_continue=True,
        )
    if category in {"schema_validation", "reference_validation", "truncated"}:
        return StopState(
            status=(
                TURN_PARTIAL_COMPLETED
                if _reliable_current_records(state)
                else TURN_FAILED
            ),
            reason_code="output_validation_failed",
            reason=message or "模型输出未通过结构校验",
            incomplete_steps=["模型未能生成合法结构化收尾"],
            can_continue=True,
        )
    if state.instrumentation.finalize_attempted and _reliable_current_records(state):
        return StopState(
            status=TURN_PARTIAL_COMPLETED,
            reason_code="finalize_model_failed",
            reason=message or "模型收尾失败，已保留当前轮已确认结果",
            incomplete_steps=["未生成合法的完整回答"],
            can_continue=True,
        )
    return StopState(
        status=TURN_FAILED,
        reason_code=default_reason_code,
        reason=message or "系统执行失败",
        incomplete_steps=["系统故障导致任务未完成"],
        can_continue=True,
    )


def _stop_from_events(state: LoopState, events: list[dict]) -> StopState | None:
    """在模型正常返回后仍以工具真实状态校正轮次终态。"""

    if state.stop_state is not None:
        return state.stop_state
    denied = next((event for event in events if event.get("status") == "denied"), None)
    if denied is not None:
        reason_code = str(denied.get("reason_code") or "access_denied")
        error = str(denied.get("error") or "当前范围不允许该查询")
        if reason_code == "tool_not_available" or "工具未注册" in error:
            return StopState(
                status=TURN_UNSUPPORTED,
                reason_code="tool_not_available",
                reason="当前白名单中没有模型请求的工具，目标任务尚不受支持",
                incomplete_steps=["未执行不存在的工具"],
                can_continue=False,
            )
        if reason_code.endswith("_budget") or "预算" in error:
            return StopState(
                status=TURN_PARTIAL_COMPLETED,
                reason_code=reason_code,
                reason=error,
                incomplete_steps=["未完成预算边界后的剩余步骤"],
                can_continue=True,
            )
        return StopState(
            status=TURN_DENIED,
            reason_code=reason_code,
            reason=error,
            incomplete_steps=["查询未获授权"],
            can_continue=False,
        )
    unsupported = next(
        (event for event in events if event.get("status") == "unsupported"), None
    )
    if unsupported is not None:
        return StopState(
            status=TURN_UNSUPPORTED,
            reason_code=str(unsupported.get("reason_code") or "tool_capability_missing"),
            reason=str(unsupported.get("error") or "当前只读工具不支持该任务"),
            incomplete_steps=["目标对象尚未由工具确认"],
            can_continue=False,
        )
    incomplete = [
        event
        for event in events
        if event.get("status") in {"partial", "limited", "error"}
    ]
    if incomplete:
        system_error = next(
            (event for event in incomplete if event.get("status") == "error"), None
        )
        status = TURN_PARTIAL_COMPLETED if _reliable_current_records(state) else TURN_FAILED
        return StopState(
            status=status,
            reason_code="tool_result_incomplete" if system_error is None else "tool_error",
            reason=str(
                (system_error or incomplete[0]).get("error")
                or "工具结果不完整，尚有步骤未确认"
            ),
            incomplete_steps=[
                f"未完整完成：{event.get('tool') or event.get('shared_tool') or '未知工具'}"
                for event in incomplete
            ],
            can_continue=True,
        )
    return None


def _entry_set(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    semantic_query: str | None,
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    if project_scope == "project" and not (project_name or "").strip():
        raise ModelRetry("字段 project_name：project_scope=project 时必须填写非空项目名")
    if project_scope == "all" and project_name is not None:
        raise ModelRetry("字段 project_name：project_scope=all 时必须设为 null")
    return {
        "schema_version": "v1",
        "project_name": project_name.strip() if project_name else None,
        "semantic_query": semantic_query.strip() if semantic_query else None,
        "main_types": list(main_types or []),
        "info_natures": [],
        "updated_at": None,
    }


def _count_params(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    return {
        "entry_set": _entry_set(project_scope, project_name, None, main_types),
        "operation": "count",
        "group_by": None,
    }


def _group_params(
    project_scope: Literal["all", "project"],
    project_name: str | None,
    group_by: Literal["project", "main_type", "info_nature", "updated_month"],
    main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None,
) -> dict:
    return {
        "entry_set": _entry_set(project_scope, project_name, None, main_types),
        "operation": "group_count",
        "group_by": group_by,
    }


def _shorten(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + f"\n[实验材料已缩减；原文保存在程序侧，省略 {len(text) - limit} 字符]"


def _model_payload(kind: str, payload: dict) -> dict:
    """保留本轮推理所需材料，完整正文只留在 result_sets。"""
    if kind in {"list", "directories"}:
        items = []
        for item in payload.get("items", []):
            items.append(
                {
                    key: (_shorten(value, 600) if key == "excerpt" else value)
                    for key, value in item.items()
                    if key
                    in {
                        "entry_id",
                        "node_id",
                        "parent_node_id",
                        "name",
                        "path",
                        "position",
                        "entry_count",
                        "title",
                        "project_id",
                        "project_name",
                        "main_type",
                        "updated_at",
                        "source_count",
                        "excerpt",
                        "matched_fields",
                        "match_hint",
                    }
                }
            )
        return {**{key: value for key, value in payload.items() if key != "items"}, "items": items}
    if kind == "entries":
        items = []
        for item in payload.get("items", []):
            items.append(
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"content", "sources"}
                    },
                    "content": _shorten(item.get("content"), 1_200),
                    "sources": [
                        {
                            key: value
                            for key, value in source.items()
                            if key in {"source_id", "source_title", "attachment_id"}
                        }
                        for source in item.get("sources", [])
                    ],
                }
            )
        return {**payload, "items": items}
    if kind == "evidence":
        items = []
        for item in payload.get("items", []):
            items.append({**item, "quote": _shorten(item.get("quote"), 2_000)})
        return {**payload, "items": items}
    return payload


def _tool_result_summary(payload: dict) -> dict:
    """为实验诊断生成有界摘要，不复制正文或把列表当成精确总数。"""
    summary = {
        key: payload[key]
        for key in (
            "value",
            "count",
            "total",
            "total_count",
            "returned_count",
            "matched_count",
        )
        if key in payload and isinstance(payload[key], (int, float, str))
    }
    items = payload.get("items")
    if isinstance(items, list):
        summary["returned_items"] = len(items)
        titles = [
            item.get("title") or item.get("name")
            for item in items
            if isinstance(item, dict) and (item.get("title") or item.get("name"))
        ]
        if titles:
            summary["titles"] = titles[:5]
    return summary


def _history_tool_summary(state: LoopState, event: dict) -> dict:
    summary = {
        "tool": event.get("tool"),
        "shared_tool": event.get("shared_tool"),
        "conditions": event.get("params", {}),
        "executed_conditions": event.get("shared_params", event.get("params", {})),
        "status": event.get("status"),
        "completeness": event.get("completeness", "unknown"),
        "result_handle": event.get("result_handle"),
        "error": event.get("error"),
    }
    record = state.result_sets.get(event.get("result_handle"))
    if record is None:
        return summary
    payload = record.payload
    if record.kind == "statistic":
        summary["statistics"] = {
            key: payload[key]
            for key in ("value", "group_by", "buckets", "truncated")
            if key in payload
        }
        summary["semantics"] = record.semantics
    elif record.kind == "list":
        summary["ordered_items"] = [
            {
                "position": index,
                "entry_id": item.get("entry_id"),
                "title": item.get("title"),
                "project_name": item.get("project_name"),
            }
            for index, item in enumerate(payload.get("items", []), 1)
        ]
        summary["semantics"] = record.semantics
    elif record.kind == "directories":
        summary["directory_items"] = [
            {
                "position": index,
                "node_id": item.get("node_id"),
                "name": item.get("name"),
                "parent_node_id": item.get("parent_node_id"),
                "path": item.get("path"),
            }
            for index, item in enumerate(payload.get("items", []), 1)
        ]
        summary["semantics"] = record.semantics
        summary["directory_total_count"] = payload.get(
            "total_count", len(payload.get("items", []))
        )
        summary["directory_returned_count"] = payload.get(
            "returned_count", len(payload.get("items", []))
        )
        summary["directory_has_more"] = payload.get("has_more", False)
    elif record.kind == "entries":
        summary["items"] = [
            {
                "entry_id": item.get("entry_id"),
                "title": item.get("title"),
                "project_name": item.get("project_name"),
                "source_ids": [source.get("source_id") for source in item.get("sources", [])],
            }
            for item in payload.get("items", [])
        ]
    elif record.kind == "evidence":
        summary["sources"] = [
            {
                "entry_id": item.get("entry_id"),
                "source_id": item.get("source_id"),
                "source_title": item.get("source_title"),
                "citable": item.get("citable"),
            }
            for item in payload.get("items", [])
        ]
    return summary


def build_compact_history(state: LoopState) -> list[ModelMessage]:
    """从程序侧记录重建合法、配对且不含历史正文的模型历史。"""
    messages: list[ModelMessage] = []
    for turn in state.history_turns:
        messages.append(ModelRequest(parts=[UserPromptPart(content=turn["user"])]))
        tools = turn["tools"]
        if tools:
            call_parts = []
            return_parts = []
            for index, tool in enumerate(tools, 1):
                call_id = f"history-{turn['turn']}-{index}"
                tool_name = tool.get("tool") or "unknown_tool"
                call_parts.append(
                    ToolCallPart(tool_name, tool.get("conditions", {}), tool_call_id=call_id)
                )
                return_parts.append(
                    ToolReturnPart(tool_name, tool, tool_call_id=call_id)
                )
            messages.append(ModelResponse(parts=call_parts))
            messages.append(ModelRequest(parts=return_parts))
        messages.append(ModelResponse(parts=[TextPart(content=turn["answer"])]))
    return messages


def _without_historical_system_prompts(history: list[ModelMessage]) -> list[ModelMessage]:
    """当前规则由 instructions 注入；历史中的旧 system 不得继续生效。"""
    cleaned: list[ModelMessage] = []
    for message in history:
        if not isinstance(message, ModelRequest):
            cleaned.append(message)
            continue
        parts = [part for part in message.parts if not isinstance(part, SystemPromptPart)]
        if parts:
            cleaned.append(replace(message, parts=parts))
    return cleaned


def _public_result(result, handle: str) -> dict:
    return {
        "result_handle": handle,
        "status": result.status,
        "completeness": result.completeness,
        "payload": result.payload,
        "error": result.error,
    }


TYPE_DISPLAY_NAMES = {
    "knowledge": "知识",
    "method": "方法",
    "parameter": "参数",
    "reminder": "提醒",
}
DIMENSION_DISPLAY_NAMES = {
    "project": "项目",
    "main_type": "知识类型",
    "info_nature": "信息性质",
    "updated_month": "更新时间（月）",
}


def _result_semantics(tool_name: str, params: dict, payload: dict) -> dict:
    """生成程序权威的查询对象、范围、维度与完整性语义。"""
    if tool_name == "list_project_directories":
        project = payload.get("project") or {}
        if payload.get("operation") == "leaf_summary":
            return {
                "subject": "directories",
                "query_object": "项目目录叶子节点",
                "display_name": "叶子节点总数",
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "project_scope": "项目",
                "group_by": "root_directory",
                "group_by_display_name": "一级目录",
                "total_count": payload.get("value"),
                "returned_count": payload.get("returned_count", 0),
                "has_more": payload.get("has_more", False),
                "completeness": "complete",
            }
        parent = payload.get("parent")
        return {
            "subject": "directories",
            "query_object": "项目目录",
            "display_name": "一级目录" if parent is None else "直接子目录",
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "parent_node_id": parent.get("node_id") if parent else None,
            "parent_path": parent.get("path") if parent else None,
            "total_count": payload.get("total_count", 0),
            "returned_count": payload.get("returned_count", 0),
            "has_more": payload.get("has_more", False),
            "completeness": "complete",
        }
    if tool_name == "aggregate_entries":
        entry_set = params.get("entry_set", {})
        project_name = entry_set.get("project_name")
        group_by = params.get("group_by")
        return {
            "subject": "entries",
            "query_object": "正式记录",
            "project_name": project_name,
            "project_scope": "项目" if project_name else "全部项目",
            "main_types": list(entry_set.get("main_types") or []),
            "type_display_names": [
                TYPE_DISPLAY_NAMES.get(value, value)
                for value in entry_set.get("main_types") or []
            ],
            "group_by": group_by,
            "group_by_display_name": DIMENSION_DISPLAY_NAMES.get(group_by)
            if group_by
            else None,
            "total_count": payload.get("value")
            if params.get("operation") == "count"
            else payload.get(
                "total_count",
                sum(item.get("count", 0) for item in payload.get("buckets", [])),
            ),
            "returned_count": payload.get("returned_count", len(payload.get("buckets", [])))
            if params.get("operation") != "count"
            else payload.get("value"),
            "bucket_count": len(payload.get("buckets", [])),
            "has_more": payload.get("truncated", False),
            "completeness": "unknown",
        }
    if tool_name in {"query_entries", "search_knowledge"}:
        entry_set = params.get("entry_set", {})
        project_name = entry_set.get("project_name") or params.get("project_name")
        return {
            "subject": "entries",
            "query_object": "正式记录",
            "project_name": project_name,
            "project_scope": "项目" if project_name else "全部项目",
            "main_types": list(entry_set.get("main_types") or []),
            "type_display_names": [
                TYPE_DISPLAY_NAMES.get(value, value)
                for value in entry_set.get("main_types") or []
            ],
            "total_count": payload.get("total_count"),
            "returned_count": payload.get("returned_count", len(payload.get("items", []))),
            "completeness": payload.get("completeness"),
        }
    return {}


def output_errors(answer: DialogueAnswer, state: LoopState) -> list[str]:
    """返回句柄边界错误；供一次模型纠正与无模型反例测试共用。"""
    errors = []
    for block in answer.blocks:
        if block.kind in {"statistic", "list"}:
            record = state.result_sets.get(block.result_handle)
            expected = block.kind
            if record is None or block.result_handle not in state.current_handles:
                errors.append(f"{block.result_handle} 不是当前轮结果")
            elif expected == "list" and record.kind not in {"list", "directories"}:
                errors.append(f"{block.result_handle} 不是列表结果")
            elif expected == "statistic" and record.kind != expected:
                errors.append(f"{block.result_handle} 不是 statistic 结果")
        elif block.kind == "evidence" and block.evidence_handle not in state.current_evidence:
            errors.append(f"{block.evidence_handle} 不是当前轮核验 Evidence")
    return errors


def list_position_entry_id(state: LoopState, result_set_handle: str, position: int) -> int:
    """将会话内有序列表位置解析为真实 Entry id。"""
    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "list" else []
    if record is None or record.kind != "list" or not 1 <= position <= len(items):
        raise ValueError("结果集句柄无效、非列表或位置越界")
    return int(items[position - 1]["entry_id"])


def list_directory_position_node_id(
    state: LoopState, result_set_handle: str, position: int
) -> int:
    """将目录结果的实际 1-based 位置解析为真实 Node id。"""
    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "directories" else []
    if record is None or record.kind != "directories" or not 1 <= position <= len(items):
        raise ValueError("目录结果句柄无效、非目录结果或位置越界")
    return int(items[position - 1]["node_id"])


async def _dispatch(
    ctx: RunContext[LoopDeps],
    tool_name: str,
    params: dict,
    kind: str,
    *,
    surface_tool: str | None = None,
    audit_params: dict | None = None,
) -> dict:
    from app.db.session import async_session_factory
    from app.models.knowledge_agent import RESULT_COMPLETENESS_UNKNOWN
    from app.services.knowledge_agent.read_tool_adapters import (
        KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
    )
    from app.services.knowledge_agent.read_tools import ReadToolBudget, dispatch_read_tool
    from app.services.knowledge_agent.tools import RunToolContext

    state = ctx.deps.state
    state.instrumentation.emit_activity(
        {
            "aggregate_entries": "querying",
            "list_project_directories": "querying",
            "query_entries": "querying",
            "search_knowledge": "querying",
            "read_entries": "reading_entries",
            "read_evidence": "reading_sources",
        }.get(tool_name, "querying")
    )
    try:
        await state.ledger.reserve_tool()
    except BudgetExceeded as exc:
        _mark_budget_stop(state, exc, tool_name=tool_name, params=params)
        if not any(
            event.get("turn_index") == state.turn_index
            and event.get("reason_code") == "tool_action_budget"
            for event in state.tool_events
        ):
            state.tool_events.append(
                {
                    "tool": surface_tool or tool_name,
                    "shared_tool": tool_name,
                    "status": "not_executed",
                    "completeness": RESULT_COMPLETENESS_UNKNOWN,
                    "params": audit_params or params,
                    "shared_params": params,
                    "reason_code": "tool_action_budget",
                    "error": str(exc),
                    "duration_ms": 0,
                    "turn_index": state.turn_index,
                }
            )
        raise
    if not state.tools_allowed:
        event = {
            "tool": surface_tool or tool_name,
            "shared_tool": tool_name,
            "status": "not_executed",
            "completeness": RESULT_COMPLETENESS_UNKNOWN,
            "params": audit_params or params,
            "shared_params": params,
            "error": "用户明确要求本轮不查知识库",
            "duration_ms": 0,
            "reason_code": "tools_disallowed_by_user",
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return event
    tool_budget = ReadToolBudget(
        max_calls=1, timeout_seconds=PER_TURN_SECONDS, max_result_bytes=32_000
    )

    async def not_cancelled() -> None:
        return None

    started = perf_counter()
    # 真实只读工具仍会写审计或 Evidence。SQLite 延迟事务若在并行读取后同时
    # 升级为写事务，会形成升级竞争；实验层只串行这段数据库事务，不改变模型
    # 调用、预算或共享领域工具的行为。
    async with state.database_lock:
        async with async_session_factory() as db:
            tool_ctx = RunToolContext(
                run_id=state.run_id,
                workspace_id=state.workspace_id,
                owner_user_id=state.user_id,
                scope_type="workspace",
                project_id=None,
                project_name=None,
                discovered_entry_ids=state.discovered_entry_ids,
            )
            result = await dispatch_read_tool(
                db,
                tool_ctx,
                tool_name=tool_name,
                tool_version="v1",
                params=params,
                budget=tool_budget,
                cancel_check=not_cancelled,
                registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
            )
            await db.commit()
    payload = result.payload
    if tool_name == "search_knowledge" and len(payload.get("items", [])) > 10:
        payload = {**payload, "items": payload["items"][:10], "truncated_by_experiment": True}
    semantics = _result_semantics(tool_name, params, payload)
    semantics["completeness"] = result.completeness
    handle = state.store_result(
        kind, payload, result.status, result.completeness, semantics=semantics
    )
    event = {
        "tool": surface_tool or tool_name,
        "shared_tool": tool_name,
        "result_handle": handle,
        "status": result.status,
        "completeness": result.completeness,
        "params": audit_params or params,
        "shared_params": params,
        "result_summary": _tool_result_summary(payload),
        "reason_code": (
            (result.audit_summary or {}).get("reason_code")
            or (
                "tool_not_available"
                if result.status == "denied" and "工具未注册" in (result.error or "")
                else None
            )
            or ("access_denied" if result.status == "denied" else None)
        ),
        "error": result.error,
        "duration_ms": int((perf_counter() - started) * 1000),
        "turn_index": state.turn_index,
    }
    state.tool_events.append(event)
    if tool_name == "read_evidence":
        for item in result.payload.get("items", []):
            evidence_handle = item.get("evidence_handle")
            if evidence_handle and item.get("citable"):
                state.evidence[evidence_handle] = item
                state.current_evidence.add(evidence_handle)
    if result.status == "error" and result.error and "预算已耗尽" in result.error:
        # 共享只读工具会把内部向量/文本预算异常保留为工具错误；实验循环需在
        # 已提交审计后恢复成统一停止信号，禁止 Agent 再发求解动作。
        exc = BudgetExceeded(result.error.removeprefix("只读工具执行失败："))
        _mark_budget_stop(state, exc, tool_name=tool_name, params=params)
        raise exc
    public = _public_result(result, handle)
    public["payload"] = _model_payload(kind, payload)
    return public


def build_agent(model) -> Agent[LoopDeps, DialogueAnswer]:
    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        instructions=SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0, "max_tokens": OUTPUT_TOKENS_LIMIT},
        max_concurrency=MAX_TOOL_CONCURRENCY,
        tool_timeout=PER_TURN_SECONDS,
    )

    @agent.instructions
    def continuation_instruction(ctx: RunContext[LoopDeps]) -> str:
        continuation = ctx.deps.state.active_continuation
        if continuation is None:
            return ""
        return (
            "程序已恢复上一轮未完成任务。只执行 pending_steps，禁止重复 completed_steps。"
            f"continuation={json.dumps(continuation.snapshot(), ensure_ascii=False)}"
        )

    @agent.tool
    async def report_unsupported(
        ctx: RunContext[LoopDeps], target: str, reason: str
    ) -> dict:
        """当前白名单没有支持目标对象的只读能力时，记录能力不足并停止尝试替代查询。"""

        event = {
            "tool": "report_unsupported",
            "status": "unsupported",
            "completeness": "unknown",
            "params": {"target": target[:200]},
            "reason_code": "tool_capability_missing",
            "error": reason[:1000] or "当前只读工具不支持该任务",
            "duration_ms": 0,
            "turn_index": ctx.deps.state.turn_index,
        }
        ctx.deps.state.tool_events.append(event)
        ctx.deps.state.stop(
            StopState(
                status=TURN_UNSUPPORTED,
                reason_code="tool_capability_missing",
                reason=event["error"],
                incomplete_steps=[f"不支持的目标：{target[:200]}"],
                can_continue=False,
            )
        )
        return event

    @agent.tool
    async def list_projects(ctx: RunContext[LoopDeps]) -> dict:
        """列出当前认证 Workspace 中可访问的 Project；这不是目录或 Entry 列表。"""
        from app.db.session import async_session_factory
        from app.models import Project
        from app.services.knowledge_agent.observability import (
            next_tool_sequence,
            record_tool_call,
        )

        state = ctx.deps.state
        state.instrumentation.emit_activity("querying")
        try:
            await state.ledger.reserve_tool()
        except BudgetExceeded as exc:
            _mark_budget_stop(state, exc, tool_name="list_projects", params={})
            raise
        if not state.tools_allowed:
            event = {
                "tool": "list_projects",
                "status": "not_executed",
                "error": "用户明确要求本轮不查知识库",
                "reason_code": "tools_disallowed_by_user",
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return event
        async with state.database_lock:
            async with async_session_factory() as db:
                rows = (
                    await db.execute(
                        select(Project.id, Project.name, Project.status)
                        .where(Project.workspace_id == state.workspace_id)
                        .order_by(Project.id)
                    )
                ).all()
                await record_tool_call(
                    db,
                    run_id=state.run_id,
                    sequence=await next_tool_sequence(db, state.run_id),
                    tool_name="list_projects",
                    status="completed" if rows else "empty",
                    result_summary=json.dumps({"project_count": len(rows)}, ensure_ascii=False),
                )
                await db.commit()
        payload = {
            "projects": [
                {"id": row.id, "name": row.name, "status": row.status}
                for row in rows
            ]
        }
        handle = state.store_result(
            "projects", payload, "completed" if rows else "empty", "complete"
        )
        event = {
            "tool": "list_projects",
            "result_handle": handle,
            "status": "completed" if rows else "empty",
            "completeness": "complete",
            "params": {},
            "error": None,
            "duration_ms": 0,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    @agent.tool
    async def list_project_directories(
        ctx: RunContext[LoopDeps],
        project_id: int | None = None,
        project_name: str | None = None,
        parent_node_id: int | None = None,
        parent_result_handle: str | None = None,
        parent_position: int | None = None,
        operation: Literal["children", "leaf_summary"] = "children",
    ) -> dict:
        """查询 Project 的真实 Node 目录。

        children 不传父节点时返回一级目录、传父节点时返回直接子目录；leaf_summary
        一次返回整棵项目目录树的真实叶子节点总数和一级目录分组，且不能传父节点。
        目录与 Entry、知识类型和信息性质完全不同。追问第几个目录时，必须
        使用上一轮该工具返回的 parent_result_handle 与 1-based parent_position。
        """
        state = ctx.deps.state
        if operation == "leaf_summary" and (
            parent_node_id is not None
            or parent_result_handle is not None
            or parent_position is not None
        ):
            raise ModelRetry("叶子节点聚合不能指定父节点或目录位置")
        if parent_result_handle is not None or parent_position is not None:
            if parent_result_handle is None or parent_position is None:
                raise ModelRetry("目录追问必须同时提供 parent_result_handle 和 parent_position")
            try:
                resolved_parent = list_directory_position_node_id(
                    state, parent_result_handle, parent_position
                )
            except ValueError as exc:
                raise ModelRetry(str(exc)) from exc
            if parent_node_id is not None and parent_node_id != resolved_parent:
                raise ModelRetry("parent_node_id 与实际目录结果位置不一致")
            parent_node_id = resolved_parent
            prior = state.result_sets.get(parent_result_handle)
            prior_project = (prior.payload.get("project") or {}) if prior else {}
            if project_id is None:
                project_id = prior_project.get("id")
            if project_name is None:
                project_name = prior_project.get("name")
        if project_id is None and project_name is None:
            raise ModelRetry("查询目录必须提供 project_id 或 project_name")
        params = {
            "project_id": project_id,
            "project_name": project_name,
            "parent_node_id": parent_node_id,
            "operation": operation,
        }
        if operation == "children" and parent_node_id in state.queried_directory_parents:
            event = {
                "tool": "list_project_directories",
                "shared_tool": "list_project_directories",
                "status": "not_executed",
                "completeness": "unknown",
                "params": params,
                "reason_code": "duplicate_directory_query",
                "error": "同一轮已查询该父节点，未重复执行",
                "duration_ms": 0,
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return event
        result = await _dispatch(
            ctx,
            "list_project_directories",
            params,
            "statistic" if operation == "leaf_summary" else "directories",
        )
        if result.get("status") in {"completed", "empty"}:
            if operation == "children":
                state.queried_directory_parents.add(parent_node_id)
                continuation = state.active_continuation
                if continuation is not None:
                    continuation.completed_steps.append({"parent_node_id": parent_node_id})
                    continuation.pending_steps = [
                        step
                        for step in continuation.pending_steps
                        if step.get("parent_node_id") != parent_node_id
                    ]
                    if not continuation.pending_steps:
                        state.continuation = None
                        state.active_continuation = None
            else:
                state.continuation = None
                state.active_continuation = None
        return result

    @agent.tool
    async def count_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """精确统计正式记录总数。main_types 未指定表示全部类型；“知识”泛称不是类型筛选。"""
        params = _count_params(project_scope, project_name, main_types)
        return await _dispatch(
            ctx,
            "aggregate_entries",
            params,
            "statistic",
            surface_tool="count_entries",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "main_types": list(main_types or []),
            },
        )

    @agent.tool
    async def group_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        group_by: Literal["project", "main_type", "info_nature", "updated_month"],
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """按一个明确维度统计正式记录。main_types 未指定表示全部正式类型。"""
        params = _group_params(project_scope, project_name, group_by, main_types)
        return await _dispatch(
            ctx,
            "aggregate_entries",
            params,
            "statistic",
            surface_tool="group_entries",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "group_by": group_by,
                "main_types": list(main_types or []),
            },
        )

    @agent.tool
    async def query_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        semantic_query: str | None,
        limit: int,
        sort_field: Literal["relevance", "updated_at", "created_at"],
        sort_direction: Literal["asc", "desc"],
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]] | None = None,
    ) -> dict:
        """按结构化条件查询列表；semantic_query 非空时结果完整性有限。"""
        params = {
            "entry_set": _entry_set(project_scope, project_name, semantic_query, main_types),
            "limit": min(max(limit, 1), 10),
            "sort": {"field": sort_field, "direction": sort_direction},
        }
        result = await _dispatch(
            ctx,
            "query_entries",
            params,
            "list",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "semantic_query": semantic_query,
                "main_types": list(main_types or []),
                "limit": params["limit"],
                "sort": params["sort"],
            },
        )
        ids = [item["entry_id"] for item in result.get("payload", {}).get("items", [])]
        try:
            ctx.deps.state.ledger.reserve_entries(ids)
        except BudgetExceeded as exc:
            _mark_budget_stop(ctx.deps.state, exc, tool_name="query_entries")
            raise
        return result

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all"],
        project_name: None,
        query: str,
    ) -> dict:
        """在授权 Workspace 全部项目中复用真实混合语义搜索；结果不能用于精确计数。"""
        result = await _dispatch(
            ctx,
            "search_knowledge",
            {"query": query},
            "list",
            audit_params={
                "project_scope": project_scope,
                "project_name": project_name,
                "query": query,
            },
        )
        ids = [item["entry_id"] for item in result.get("payload", {}).get("items", [])]
        try:
            ctx.deps.state.ledger.reserve_entries(ids)
        except BudgetExceeded as exc:
            _mark_budget_stop(ctx.deps.state, exc, tool_name="search_knowledge")
            raise
        return result

    @agent.tool
    async def read_entries(ctx: RunContext[LoopDeps], entry_ids: list[int]) -> dict:
        """读取本会话已由列表或搜索发现的 Entry 正文；任意新 id 会被拒绝。"""
        try:
            ctx.deps.state.ledger.reserve_entries(entry_ids)
        except BudgetExceeded as exc:
            _mark_budget_stop(ctx.deps.state, exc, tool_name="read_entries")
            raise
        return await _dispatch(ctx, "read_entries", {"entry_ids": entry_ids}, "entries")

    @agent.tool
    async def read_evidence(
        ctx: RunContext[LoopDeps], entry_id: int, source_ids: list[int]
    ) -> dict:
        """当前轮重新核验已发现 Entry 的真实 Source 原文并创建 Evidence。"""
        try:
            ctx.deps.state.ledger.reserve_evidence(len(source_ids))
        except BudgetExceeded as exc:
            _mark_budget_stop(ctx.deps.state, exc, tool_name="read_evidence")
            raise
        return await _dispatch(
            ctx, "read_evidence", {"entry_id": entry_id, "source_ids": source_ids}, "evidence"
        )

    @agent.tool
    async def open_list_item(
        ctx: RunContext[LoopDeps], result_set_handle: str, position: int
    ) -> dict:
        """按本实验会话中实际展示列表的 1-based 位置重新读取对象。"""
        from app.db.session import async_session_factory
        from app.services.knowledge_agent.tools import (
            RunToolContext,
            read_entries,
            resolve_recent_result_entries,
        )

        state = ctx.deps.state
        state.instrumentation.emit_activity("reading_entries")
        try:
            await state.ledger.reserve_tool()
        except BudgetExceeded as exc:
            _mark_budget_stop(state, exc, tool_name="open_list_item")
            raise
        try:
            entry_id = list_position_entry_id(state, result_set_handle, position)
        except ValueError:
            event = {
                "tool": "open_list_item",
                "status": "denied",
                "params": {"result_set_handle": result_set_handle, "position": position},
                "error": "结果集句柄无效、非列表或位置越界",
                "duration_ms": 0,
            }
            state.tool_events.append(event)
            return event
        state.ledger.reserve_entries([entry_id])
        async with state.database_lock:
            async with async_session_factory() as db:
                tool_ctx = RunToolContext(
                    run_id=state.run_id,
                    workspace_id=state.workspace_id,
                    owner_user_id=state.user_id,
                    scope_type="workspace",
                    project_id=None,
                    project_name=None,
                    discovered_entry_ids=state.discovered_entry_ids,
                )
                refreshed = await resolve_recent_result_entries(db, tool_ctx, [entry_id])
                if not refreshed.items:
                    event = {
                        "tool": "open_list_item",
                        "status": "error",
                        "params": {"result_set_handle": result_set_handle, "position": position},
                        "error": "对象已删除或移出当前范围",
                        "duration_ms": 0,
                    }
                    state.tool_events.append(event)
                    return event
                output = await read_entries(db, tool_ctx, [entry_id])
                await db.commit()
        payload = output.model_dump(mode="json")
        handle = state.store_result(
            "entries", payload, "completed" if output.items else "error", "limited"
        )
        event = {
            "tool": "open_list_item",
            "result_handle": handle,
            "status": "completed" if output.items else "error",
            "completeness": "limited",
            "params": {"result_set_handle": result_set_handle, "position": position},
            "error": None if output.items else "对象读取失败",
            "duration_ms": 0,
        }
        state.tool_events.append(event)
        return {**event, "payload": payload}

    @agent.output_validator
    async def validate_output(ctx: RunContext[LoopDeps], answer: DialogueAnswer) -> DialogueAnswer:
        errors = output_errors(answer, ctx.deps.state)
        if errors:
            message = "；".join(errors)
            ctx.deps.state.instrumentation.record_validation_failure(
                "reference_validation", message, answer.model_dump(mode="json")
            )
            raise ModelRetry(message)
        return answer

    return agent


def render_answer(answer: DialogueAnswer, state: LoopState) -> tuple[str, list[dict]]:
    """按模型块顺序以真实工具数据渲染，不接受模型填写数字或原文。"""
    lines: list[str] = []
    rendered: list[dict] = []
    for block in answer.blocks:
        if block.kind in {"text", "insufficient"}:
            text = block.text
            lines.append(text)
            rendered.append({"kind": block.kind, "text": text})
        elif block.kind == "statistic":
            record = state.result_sets[block.result_handle]
            payload = record.payload
            semantics = record.semantics
            group_display = semantics.get("group_by_display_name")
            if "value" in payload:
                if semantics.get("subject") == "directories":
                    text = (
                        f"{semantics.get('project_name') or '当前项目'} · "
                        f"{semantics.get('display_name') or '目录统计'}：{payload['value']}"
                    )
                else:
                    # 保留既有正式记录计数回答的文本兼容性。
                    text = f"总数：{payload['value']}"
            else:
                title = (
                    f"{semantics.get('project_name')} · 按{group_display or '维度'}统计"
                    if semantics.get("project_name")
                    else f"全部项目 · 按{group_display or '维度'}统计"
                )
                buckets = payload.get("buckets", [])
                values = "；".join(
                    f"{(
                        TYPE_DISPLAY_NAMES.get(
                            item.get('key'), item.get('label') or item.get('key')
                        )
                        if semantics.get('group_by') == 'main_type'
                        else item.get('label') or item.get('key')
                    )}：{item.get('count')}"
                    for item in buckets
                )
                text = f"{title}：{values or '无分组记录'}"
            lines.append(text)
            rendered.append(
                {
                    "kind": "statistic",
                    "handle": block.result_handle,
                    "text": text,
                    "value": payload.get("value"),
                    "group_by": payload.get("group_by"),
                    "buckets": payload.get("buckets", []),
                    "status": record.status,
                    "completeness": record.completeness,
                    "semantics": semantics,
                }
            )
        elif block.kind == "list":
            record = state.result_sets[block.result_handle]
            semantics = record.semantics
            if record.kind == "directories":
                project_name = semantics.get("project_name") or "当前项目"
                title = f"{project_name} · {semantics.get('display_name', '项目目录')}"
            else:
                title = (
                    f"{semantics.get('project_name')} · 正式记录列表"
                    if semantics.get("project_name")
                    else "全部项目 · 正式记录列表"
                )
            lines.append(title)
            items = record.payload.get("items", [])
            for index, item in enumerate(items, 1):
                if record.kind == "directories":
                    lines.append(f"{index}. {item.get('name', '未命名')}（{item.get('path', '')}）")
                else:
                    lines.append(
                        f"{index}. {item.get('title', '未命名')}"
                        f"（{item.get('project_name', '未知项目')}）"
                    )
            rendered.append(
                {
                    "kind": "list",
                    "handle": block.result_handle,
                    "label": title,
                    "items": items,
                    "status": record.status,
                    "completeness": record.completeness,
                    "semantics": semantics,
                }
            )
        else:
            item = state.evidence[block.evidence_handle]
            text = f"来源《{item.get('source_title', '')}》：{item.get('quote', '')}"
            if block.note:
                text = f"{block.note}\n{text}"
            lines.append(text)
            rendered.append(
                {
                    "kind": "evidence",
                    "handle": block.evidence_handle,
                    "text": text,
                    "entry_id": item.get("entry_id"),
                    "source_id": item.get("source_id"),
                }
            )
    return "\n".join(lines), rendered


def _verified_failure_output(
    state: LoopState, stop: StopState | None = None
) -> tuple[str, list[dict]]:
    """无模型地只展示当前轮真实句柄，并明确缺口、原因和续查能力。"""

    stop = stop or state.stop_state
    if stop is None:
        finalize_status = state.instrumentation.finalize_status
        notices = {
            "timed_out": "收尾请求超过时间预算",
            "invalid_output": "收尾输出未通过结构校验",
            "not_dispatched": "没有可用文本请求预算，未派发模型收尾",
            "failed": "收尾模型请求失败",
            "cancelled": "收尾请求被取消",
        }
        stop = StopState(
            status=(
                TURN_PARTIAL_COMPLETED
                if _reliable_current_records(state)
                else TURN_FAILED
            ),
            reason_code=f"finalize_{finalize_status}",
            reason=notices.get(finalize_status, "任务未能完成"),
            incomplete_steps=["未生成合法的完整回答"],
            can_continue=True,
        )
    state.stop(stop)
    status_text = {
        TURN_PARTIAL_COMPLETED: "本轮已部分完成，以下只保留程序确认的结果。",
        TURN_UNSUPPORTED: "当前工具能力不支持完整处理这个任务。",
        TURN_DENIED: "当前权限或数据范围不允许执行这个任务。",
        TURN_FAILED: "本轮遇到系统故障，以下仅保留已经确认的结果。",
    }[stop.status]
    requested_blocks: list[dict] = [{"kind": "text", "text": status_text}]
    for handle, record in state.result_sets.items():
        if handle not in state.current_handles or record.status not in {
            "completed", "ok", "empty", "partial", "limited"
        }:
            continue
        if record.kind == "statistic":
            requested_blocks.append(
                {"kind": "statistic", "result_handle": handle, "label": "已确认统计"}
            )
        elif record.kind in {"list", "directories"}:
            requested_blocks.append(
                {"kind": "list", "result_handle": handle, "label": "已确认列表"}
            )
    for handle in state.evidence:
        if handle in state.current_evidence:
            requested_blocks.append(
                {"kind": "evidence", "evidence_handle": handle, "note": "已确认来源"}
            )
    missing = "；".join(stop.incomplete_steps) or "仍有步骤尚未确认"
    if stop.can_continue and stop.continuation is not None:
        continuation_text = "可以在下一轮说“继续”，系统将从已保存的未完成步骤继续。"
    elif stop.can_continue:
        continuation_text = "可以在下一轮重新发起查询；当前没有可自动恢复的步骤。"
    else:
        continuation_text = "当前任务不能从已保存步骤自动继续。"
    finalize_status = state.instrumentation.finalize_status
    finalize_note = (
        f"；模型收尾状态：{finalize_status}"
        if finalize_status not in {"not_needed", "completed"}
        else ""
    )
    requested_blocks.append(
        {
            "kind": "insufficient",
            "text": (
                f"尚未确认：{missing}。停止原因：{stop.reason}{finalize_note}。"
                f"{continuation_text}"
            ),
        }
    )
    answer = DialogueAnswer.model_validate({"blocks": requested_blocks})
    return render_answer(answer, state)


def _usage_limits(request_limit: int) -> UsageLimits:
    return UsageLimits(
        request_limit=request_limit,
        per_request_input_tokens_limit=12_000,
        output_tokens_limit=24_000,
        # 输入在派发前另按确定性估算门禁；部分既有模型包装不实现 count_tokens。
        count_tokens_before_request=False,
    )


def _budget_stop_reason(exc: BudgetExceeded) -> str:
    """把可恢复的预算停止映射成稳定、可展示的收尾原因。"""
    message = str(exc)
    if "工具动作" in message:
        return "tool_action_budget"
    if "向量" in message:
        return "embedding_request_budget"
    if "Entry" in message:
        return "entry_read_budget"
    if "Evidence" in message:
        return "evidence_read_budget"
    if "输入长度" in message or "上下文" in message:
        return "input_hard_limit"
    return "text_request_budget"


def _aggregate_text_usage(logs: list, text_requests: int, tool_calls: int) -> dict | None:
    """从已完成调用日志恢复整轮 usage；未知费用保持未知。"""
    token_keys = (
        "input_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "output_tokens",
        "input_audio_tokens",
        "cache_audio_read_tokens",
        "output_audio_tokens",
    )
    totals = {key: 0 for key in token_keys}
    text_logs = [item for item in logs if item.kind == "text"]
    if not text_logs:
        return None
    text_usages = [item.usage for item in text_logs if item.usage]
    cost_total = Decimal("0")
    cost_available = bool(text_usages)
    for usage in text_usages:
        for key in token_keys:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
        cost = usage.get("cost")
        if cost is None:
            cost_available = False
        else:
            try:
                cost_total += Decimal(str(cost))
            except InvalidOperation:
                cost_available = False
    if len(text_usages) != len(text_logs):
        cost_available = False
    usage_complete = len(text_usages) == len(text_logs)
    return {
        **{key: totals[key] if usage_complete else None for key in token_keys},
        "cost": str(cost_total) if cost_available else None,
        "requests": text_requests,
        "tool_calls": tool_calls,
        "usage_complete": usage_complete,
        "known_requests": len(text_usages),
        "known_tokens": totals,
    }


def _current_material_history(
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
) -> list[ModelMessage]:
    """把求解阶段已取得的当前轮材料重建为合法配对消息。"""
    messages = [
        *_without_historical_system_prompts(history),
        ModelRequest(parts=[UserPromptPart(content=message)]),
    ]
    for index, event in enumerate(current_events, 1):
        handle = event.get("result_handle")
        if handle not in state.current_handles and event.get("status") not in {
            "denied",
            "error",
            "not_executed",
        }:
            continue
        tool_name = event.get("tool") or "unknown_tool"
        call_id = f"finalize-{state.turn_index}-{index}"
        content = _history_tool_summary(state, event)
        record = state.result_sets.get(handle)
        if record is not None:
            content["payload"] = _model_payload(record.kind, record.payload)
        messages.append(
            ModelResponse(
                parts=[
                    ToolCallPart(tool_name, event.get("params", {}), tool_call_id=call_id)
                ]
            )
        )
        messages.append(
            ModelRequest(parts=[ToolReturnPart(tool_name, content, tool_call_id=call_id)])
        )
    return messages


async def _finalize_once(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
    reason: str,
) -> object:
    """在独立时间窗内用当前轮已核验材料做唯一一次无工具收尾。"""
    state.instrumentation.begin_finalize(reason)
    before_logs = len(state.instrumentation.logs)
    material_history = _current_material_history(state, message, history, current_events)
    try:
        async with asyncio.timeout(FINALIZE_SECONDS):
            return await agent.run(
                "求解阶段已停止。请只根据本轮已获得并核验的材料收尾。",
                deps=LoopDeps(state),
                message_history=material_history,
                usage_limits=_usage_limits(1),
                retries=0,
            )
    except TimeoutError as exc:
        error = f"{type(exc).__name__}: 收尾超过 {FINALIZE_SECONDS:g} 秒"
        state.instrumentation.finalize_status = "timed_out"
        state.instrumentation.finalize_error = error
        state.instrumentation.finalize_failure = state.instrumentation.describe_failure(
            exc, before_logs
        )
        raise
    except Exception as exc:
        failure = state.instrumentation.describe_failure(exc, before_logs)
        state.instrumentation.finalize_failure = failure
        if state.instrumentation.finalize_response_received:
            state.instrumentation.finalize_status = "invalid_output"
            state.instrumentation.finalize_error = (
                "收尾输出非法，未重试模型请求："
                f"{failure['category']}: {failure['message']}"
            )
        elif state.instrumentation.finalize_error is None:
            state.instrumentation.finalize_status = "failed"
            state.instrumentation.finalize_error = (
                f"{failure['category']}: {failure['message']}"
            )
        raise


async def run_turn(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
) -> tuple[dict, list[ModelMessage]]:
    """执行一轮；超限、模型失败和 usage 缺失均显式保留。"""
    history = _without_historical_system_prompts(history)
    history_estimate = estimate_input_tokens(history)
    before_logs = len(state.instrumentation.logs)
    before_events = len(state.tool_events)
    started = perf_counter()
    solve_error = None
    solve_failure = None
    error_details = None
    try:
        if history_estimate > MODEL_INPUT_TOKENS_LIMIT:
            raise BudgetExceeded(
                f"压缩后对话上下文输入长度估算 {history_estimate} "
                "超过冻结上限，未派发模型请求"
            )
        async with asyncio.timeout(PER_TURN_SECONDS):
            result = await agent.run(
                message,
                deps=LoopDeps(state),
                message_history=history,
                usage_limits=_usage_limits(12),
            )
    except FinalizeRequired:
        try:
            result = await _finalize_once(
                agent,
                state,
                message,
                history,
                state.tool_events[before_events:],
                state.instrumentation.finalize_reason or "budget_boundary",
            )
        except Exception as finalize_exc:
            error_details = state.instrumentation.finalize_failure
            raw_error = state.instrumentation.finalize_error or (
                f"{type(finalize_exc).__name__}: {finalize_exc}"
            )
            stop = _stop_from_failure(state, finalize_exc, error_details)
            state.stop(stop)
            text, blocks = _verified_failure_output(state, stop)
            status = stop.status
            error = raw_error if status == TURN_FAILED else None
            usage = None
        else:
            text, blocks = render_answer(result.output, state)
            state.instrumentation.complete_finalize()
            status = "completed"
            error = None
            usage = asdict(result.usage) if result.usage is not None else None
    except BudgetExceeded as exc:
        solve_error = f"{type(exc).__name__}: {exc}"
        solve_failure = state.instrumentation.describe_failure(exc, before_logs)
        _mark_budget_stop(state, exc)
        if not state.instrumentation.context_policy_enabled:
            text, blocks = _verified_failure_output(state)
            status = TURN_PARTIAL_COMPLETED
            error = None
            error_details = solve_failure
            usage = None
        else:
            try:
                result = await _finalize_once(
                    agent,
                    state,
                    message,
                    history,
                    state.tool_events[before_events:],
                    _budget_stop_reason(exc),
                )
            except Exception:
                error_details = state.instrumentation.finalize_failure
                text, blocks = _verified_failure_output(state)
                status = TURN_PARTIAL_COMPLETED
                error = None
                usage = None
            else:
                text, blocks = render_answer(result.output, state)
                state.instrumentation.complete_finalize()
                status = TURN_PARTIAL_COMPLETED
                error = None
                usage = asdict(result.usage) if result.usage is not None else None
    except TimeoutError as exc:
        solve_error = f"{type(exc).__name__}: 求解超过 {PER_TURN_SECONDS:g} 秒"
        solve_failure = state.instrumentation.describe_failure(exc, before_logs)
        stop = _stop_from_failure(state, exc, solve_failure)
        state.stop(stop)
        if state.instrumentation.finalize_attempted:
            text, blocks = _verified_failure_output(state, stop)
            status = stop.status
            error_details = state.instrumentation.finalize_failure
            error = None
            usage = None
        else:
            try:
                result = await _finalize_once(
                    agent,
                    state,
                    message,
                    history,
                    state.tool_events[before_events:],
                    "solve_timeout",
                )
            except Exception:
                text, blocks = _verified_failure_output(state, stop)
                status = stop.status
                error_details = state.instrumentation.finalize_failure
                error = None
                usage = None
            else:
                text, blocks = render_answer(result.output, state)
                state.instrumentation.complete_finalize()
                status = stop.status
                error = None
                usage = asdict(result.usage) if result.usage is not None else None
    except Exception as exc:
        error_details = state.instrumentation.describe_failure(exc, before_logs)
        stop = _stop_from_failure(state, exc, error_details)
        state.stop(stop)
        text, blocks = _verified_failure_output(state, stop)
        status = stop.status
        error = f"{type(exc).__name__}: {exc}" if status == TURN_FAILED else None
        usage = None
    else:
        text, blocks = render_answer(result.output, state)
        state.instrumentation.complete_finalize()
        status = TURN_COMPLETED
        error = None
        usage = asdict(result.usage) if result.usage is not None else None
    current_events = state.tool_events[before_events:]
    event_stop = _stop_from_events(state, current_events)
    if event_stop is not None:
        state.stop(event_stop)
        status = event_stop.status
        if status in {TURN_UNSUPPORTED, TURN_DENIED, TURN_FAILED}:
            text, blocks = _verified_failure_output(state, event_stop)
        elif not any(block.get("kind") == "insufficient" for block in blocks):
            continuation_text = (
                "可以在下一轮继续未完成步骤。"
                if event_stop.can_continue and event_stop.continuation is not None
                else "可以在下一轮重新发起查询。"
                if event_stop.can_continue
                else "当前任务不能自动继续。"
            )
            notice = (
                f"尚未完成：{'；'.join(event_stop.incomplete_steps)}。"
                f"停止原因：{event_stop.reason}。{continuation_text}"
            )
            blocks.append({"kind": "insufficient", "text": notice})
            text = f"{text}\n{notice}" if text else notice
        if status != TURN_FAILED:
            error = None
    state.remember_turn(message, text, current_events)
    new_history = build_compact_history(state)
    input_estimates = [
        {
            "projected_input_tokens": item.projected_input_tokens,
            "estimated_input_tokens": item.estimated_input_tokens,
            "method": item.input_estimate_method,
            "components": item.estimate_components,
            "request_scope": item.request_scope,
            "actual_input_tokens": item.actual_input_tokens,
            "estimate_ratio": item.estimate_ratio,
            "finalize_only": item.finalize_only,
            "finalize_reason": item.finalize_reason,
        }
        for item in state.instrumentation.logs[before_logs:]
        if item.kind in {"text", "text_not_dispatched"}
    ]
    recovered_usage = _aggregate_text_usage(
        state.instrumentation.logs[before_logs:],
        state.ledger.active_text_requests,
        state.ledger.active_tool_calls,
    )
    if recovered_usage is not None:
        usage = recovered_usage
    return {
        "message": message,
        "status": status,
        "answer": text,
        "blocks": blocks,
        "error": error,
        "error_details": error_details,
        "solve_error": solve_error,
        "solve_failure": solve_failure,
        "duration_ms": int((perf_counter() - started) * 1000),
        "usage": usage,
        "budget": state.ledger.snapshot(),
        "tool_calls": current_events,
        "model_calls": [asdict(item) for item in state.instrumentation.logs[before_logs:]],
        "context": {
            "history_estimated_input_tokens": history_estimate,
            "input_estimates": input_estimates,
            "history_turns": len(state.history_turns),
            "solve_seconds_limit": PER_TURN_SECONDS,
            "finalize_seconds_limit": FINALIZE_SECONDS,
        },
        "finalization": state.instrumentation.finalization_snapshot(),
        "completion": state.completion_snapshot(status),
    }, new_history
