"""Pydantic AI 统一对话循环及可信只读工具适配。"""

from __future__ import annotations

import asyncio
import json
import re
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
    TURN_NOT_EXECUTED,
    TURN_PARTIAL_COMPLETED,
    TURN_UNSUPPORTED,
    BudgetExceeded,
    BudgetLedger,
    ContinuationState,
    DialogueAnswer,
    StopState,
    StrictModel,
)
from evals.dialogue_loop.instrumentation import (
    FinalizeRequired,
    Instrumentation,
    estimate_input_tokens,
)

SYSTEM_PROMPT = """你是 Grove 知识库的只读对话 Agent。你在一个持续的多轮对话中工作。

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
16. 用户明确提到目录名称或完整路径时，优先用 list_project_directories 的 find 操作直接定位；
    不要先遍历所有一级目录。目录名不是 Entry 标题、知识类型或信息性质，不能用相关性搜索代替定位。
17. find 只有 match_status=unique 时才是唯一目录；ambiguous 时展示候选完整路径并请用户选择。
    找到后用目录结果句柄查询 children，或用现有统计/列表工具查询真实 Node 范围。
18. is_leaf 只以目录工具服务端返回值为准；它来自完整 Node 集合对子节点的确认。后续“这个目录”
    优先复用上一轮 directory_result_handle 和真实 node_id，不重复 find。用户专门追问是否为叶子时，
    仍按该句柄查询 children；只有直接子目录完整返回为空，才回答它是叶子节点。
19. find 完整返回 not_found 后，直接说明指定目录不存在；必要时最多改用 contains 查找相近名称，
    不得再从项目根调用 children 逐层遍历，也不得把定位空结果改写成权限错误。
20. 用户明确提到项目名并询问其中的知识时，search_knowledge 必须使用 project_scope=project 和准确
    project_name；只有用户明确询问全部项目时才使用 all。项目范围搜索只返回严格语义相关的正式记录，
    不要把相近主题候选当作墙纸等目标知识。
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
CONTEXTUAL_SEARCH_FOLLOW_UP_PATTERNS = (
    "好的，你帮我查一下",
    "好，你帮我查一下",
    "好的，帮我查一下",
    "可以，你帮我查一下",
    "行，你帮我查一下",
    "那你帮我查一下",
)
CANDIDATE_SELF_UPDATE_PATTERNS = (
    "输出给我",
    "我自己更新",
    "我去更新",
    "我自己修改",
    "供我审核",
    "给我审核",
    "候选修改稿",
    "建议草稿",
)
CANDIDATE_REVISION_PATTERNS = (
    "帮我补充",
    "帮我完善",
    "改写一版",
    "给我一版更新后的内容",
    "整理成可以更新的版本",
)
DIRECT_WRITE_PATTERNS = (
    "直接帮我更新",
    "直接更新知识库",
    "更新知识库",
    "保存到这条记录",
    "保存到原记录",
    "把原记录改掉",
    "覆盖原来的内容",
    "覆盖原记录",
    "写入 entry",
    "替我保存",
    "保存修改",
)


def _candidate_revision_requested(message: str) -> bool:
    """确定性区分候选文本生成与明确写入；用户自行更新的表达优先。"""

    normalized = message.strip().lower()
    if any(pattern in normalized for pattern in CANDIDATE_SELF_UPDATE_PATTERNS):
        return True
    if any(pattern in normalized for pattern in DIRECT_WRITE_PATTERNS):
        return False
    return any(pattern in normalized for pattern in CANDIDATE_REVISION_PATTERNS)


def _contextual_search_follow_up(message: str) -> bool:
    """识别不自带新主题的短承接查询，不负责推断具体主题或范围。"""

    normalized = re.sub(r"[，。！？!?,\s]", "", message).casefold()
    return any(
        re.sub(r"[，。！？!?,\s]", "", pattern).casefold() == normalized
        for pattern in CONTEXTUAL_SEARCH_FOLLOW_UP_PATTERNS
    )


def _definition_question(message: str) -> bool:
    """识别通用定义问句形式，不绑定任何具体领域关键词。"""

    normalized = re.sub(r"[？?。！!\s]", "", message)
    return "是什么" in normalized or normalized.startswith("什么是")


ENTRY_CONTENT_PATTERNS = (
    "具体内容",
    "完整内容",
    "完整正文",
    "正文是什么",
    "正文内容",
    "详细内容",
    "内容是什么",
    "展开说说",
    "展开看看",
)


def _entry_content_requested(message: str) -> bool:
    """识别需要直接展示已读取 Entry 正文的请求，不参与候选稿分流。"""
    return not _candidate_revision_requested(message) and any(
        pattern in message.strip().lower() for pattern in ENTRY_CONTENT_PATTERNS
    )


def _entry_reference(text: str) -> tuple[str, int] | None:
    """解析正文引用标记，兼容旧版句柄格式；句柄随后仍由服务端校验。"""
    match = re.fullmatch(r"\[\[(?:entry:)?([^:\]]+):(\d+)\]\]", text.strip())
    if match is None:
        return None
    return match.group(1), int(match.group(2))


class LegacySort(StrictModel):
    """兼容旧版嵌套排序参数；新合同仍优先使用扁平字段。"""

    field: Literal["relevance", "updated_at", "created_at"]
    direction: Literal["asc", "desc"]


class RelevanceDecision(StrictModel):
    """同一对话 Agent 对真实候选作出的有界相关性分类。"""

    entry_id: int
    relevance: Literal["direct", "indirect", "unrelated"]
    reason: str = ""


@dataclass
class ResultRecord:
    handle: str
    kind: str
    payload: dict
    status: str
    completeness: str
    turn_index: int
    semantics: dict = field(default_factory=dict)
    displayable: bool = True


@dataclass
class LoopState:
    workspace_id: int
    user_id: int
    conversation_id: int
    ledger: BudgetLedger
    instrumentation: Instrumentation
    discovered_entry_ids: set[int] = field(default_factory=set)
    authorized_entry_ids: set[int] = field(default_factory=set)
    read_entry_ids: set[int] = field(default_factory=set)
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
    semantic_search_results: dict[str, str] = field(default_factory=dict)
    current_message: str = ""
    _handle_sequence: int = 0
    database_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    semantic_search_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def begin_turn(self, run_id: int, message: str) -> None:
        self.turn_index += 1
        self.run_id = run_id
        self.current_message = message
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
        *,
        displayable: bool = True,
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
            displayable,
        )
        if kind == "list" and displayable:
            self.authorized_entry_ids.update(
                int(item["entry_id"])
                for item in payload.get("items", [])
                if item.get("entry_id") is not None
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
        and record.displayable
        and record.status in {"completed", "ok", "empty", "partial", "limited"}
    ]


def _none_if_string_null(value: str | None) -> str | None:
    """将模型常见的字符串 null 视为未提供，不处理其他值。"""

    if value is None or not value.strip() or value.strip().casefold() == "null":
        return None
    return value.strip()


def _optional_int(value: int | str | None, field_name: str) -> int | None:
    """只兼容字符串 null；其他字符串不能借兼容层变成对象 ID。"""

    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().casefold() == "null":
            return None
        raise ModelRetry(f"字段 {field_name}：只接受整数或 null")
    return value


def _optional_main_types(
    value: list[Literal["knowledge", "method", "parameter", "reminder"]] | str | None,
) -> list[Literal["knowledge", "method", "parameter", "reminder"]] | None:
    """兼容可空列表的字符串 null，同时拒绝其他字符串。"""

    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().casefold() == "null":
            return None
        raise ModelRetry("字段 main_types：只接受类型数组或 null")
    return value


def _optional_directory_scope(value: str | None) -> Literal["direct", "subtree"] | None:
    normalized = _none_if_string_null(value)
    if normalized is None:
        return None
    if normalized not in {"direct", "subtree"}:
        raise ModelRetry("字段 directory_scope：只接受 direct、subtree 或 null")
    return normalized


def _normalized_sort(
    *,
    semantic_query: str | None,
    sort_field: Literal["relevance", "updated_at", "created_at"] | None,
    sort_direction: Literal["asc", "desc"] | None,
    sort: LegacySort | str | None,
) -> tuple[
    Literal["relevance", "updated_at", "created_at"], Literal["asc", "desc"]
]:
    """规范化首选扁平排序字段与唯一旧式嵌套兼容形态。"""

    legacy = None
    if isinstance(sort, str):
        if sort.strip().casefold() != "null":
            raise ModelRetry("字段 sort：只接受 {field, direction} 或 null")
    else:
        legacy = sort
    if legacy is not None:
        if sort_field is not None and sort_field != legacy.field:
            raise ModelRetry("sort.field 与 sort_field 冲突")
        if sort_direction is not None and sort_direction != legacy.direction:
            raise ModelRetry("sort.direction 与 sort_direction 冲突")
        sort_field = sort_field or legacy.field
        sort_direction = sort_direction or legacy.direction
    sort_field = sort_field or ("relevance" if semantic_query else "updated_at")
    sort_direction = sort_direction or "desc"
    if semantic_query is None and sort_field == "relevance":
        raise ModelRetry("没有 semantic_query 时不能按 relevance 排序")
    return sort_field, sort_direction


def _semantic_query_key(
    *,
    project_scope: str,
    project_name: str | None,
    query: str,
    main_types: list[str] | None = None,
    node_scope: dict | None = None,
) -> str:
    """为确定性相同的语义查询生成跨表面工具共享键。"""

    return json.dumps(
        {
            "project_scope": project_scope,
            "project_name": project_name.casefold() if project_name else None,
            "query": " ".join(query.casefold().split()),
            "main_types": sorted(main_types or []),
            "node_scope": node_scope or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _authorized_list_for_entry_ids(
    state: LoopState, entry_ids: list[int]
) -> tuple[str, ResultRecord] | None:
    """定位包含读取目标的最近授权列表，供失败续执行保存最小状态。"""

    for handle, record in reversed(list(state.result_sets.items())):
        if record.kind != "list" or not record.displayable:
            continue
        available = [int(item["entry_id"]) for item in record.payload.get("items", [])]
        if entry_ids == available:
            return handle, record
    return None


def _directory_continuation(state: LoopState, params: dict, reason: str) -> ContinuationState:
    """从当前轮真实目录事件构造可续队列，不保存结果句柄。"""

    operation = params.get("operation", "children")
    task_type = "directory_find" if operation == "find" else "directory_walk"
    existing = state.active_continuation or state.continuation
    if existing is not None and existing.task_type == task_type:
        continuation = existing
    else:
        continuation = ContinuationState(
            task_type=task_type,
            tool_name="list_project_directories",
            scope={
                "project_id": params.get("project_id"),
                "project_name": params.get("project_name"),
            },
        )
    step = (
        {
            "operation": "find",
            "name": params.get("name"),
            "path": params.get("path"),
            "match": params.get("match", "exact"),
        }
        if operation == "find"
        else {"parent_node_id": params.get("parent_node_id")}
    )
    if step not in continuation.pending_steps:
        continuation.pending_steps.append(step)
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
    denied_events = [event for event in events if event.get("status") == "denied"]
    if denied_events:
        event = next(
            (
                item
                for item in denied_events
                if item.get("reason_code") != "invalid_tool_params"
                and "工具参数非法" not in str(item.get("error") or "")
            ),
            denied_events[0],
        )
        reason_code = str(event.get("reason_code") or "access_denied")
        error = str(event.get("error") or "当前范围不允许该查询")
        if reason_code == "invalid_tool_params" or "工具参数非法" in error:
            return StopState(
                status=(
                    TURN_PARTIAL_COMPLETED
                    if _reliable_current_records(state)
                    else TURN_NOT_EXECUTED
                ),
                reason_code="invalid_tool_params",
                reason=error,
                incomplete_steps=["模型未能提交合法的工具参数"],
                can_continue=True,
            )
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
            status=TURN_PARTIAL_COMPLETED,
            reason_code="output_validation_failed",
            reason=message or "模型输出未通过结构校验",
            incomplete_steps=["模型未能生成合法的完整回答"],
            can_continue=True,
        )
    if "exceeded max retries" in lower or "校验" in message:
        invalid_tool_shape = (
            "tool" in lower and not _reliable_current_records(state) and not events
        )
        return StopState(
            status=TURN_NOT_EXECUTED if invalid_tool_shape else TURN_PARTIAL_COMPLETED,
            reason_code=(
                "invalid_tool_params" if invalid_tool_shape else "output_validation_failed"
            ),
            reason=message or "模型输出未通过结构校验",
            incomplete_steps=[
                "查询未执行：模型未能提交合法参数"
                if invalid_tool_shape
                else "模型未能生成合法的完整回答"
            ],
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
    denied_events = [event for event in events if event.get("status") == "denied"]
    denied = next(
        (
            event
            for event in denied_events
            if event.get("reason_code") != "invalid_tool_params"
            and "工具参数非法" not in str(event.get("error") or "")
        ),
        denied_events[0] if denied_events else None,
    )
    if denied is not None:
        reason_code = str(denied.get("reason_code") or "access_denied")
        error = str(denied.get("error") or "当前范围不允许该查询")
        if reason_code == "invalid_tool_params" or "工具参数非法" in error:
            return StopState(
                status=(
                    TURN_PARTIAL_COMPLETED
                    if _reliable_current_records(state)
                    else TURN_NOT_EXECUTED
                ),
                reason_code="invalid_tool_params",
                reason=error,
                incomplete_steps=["模型未能提交合法的工具参数"],
                can_continue=True,
            )
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
    incomplete = []
    for event in events:
        status = event.get("status")
        if status in {"partial", "error"}:
            incomplete.append(event)
            continue
        # 语义查询即使没有更多结果也会标记 limited，只有明确存在后续结果时
        # 才把它视为尚未完成的步骤。
        if status == "limited":
            has_more = (event.get("result_summary") or {}).get("has_more")
            if has_more is not False:
                incomplete.append(event)
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
    normalized_project_name = _none_if_string_null(project_name)
    normalized_query = _none_if_string_null(semantic_query)
    if project_scope == "project" and normalized_project_name is None:
        raise ModelRetry("字段 project_name：project_scope=project 时必须填写非空项目名")
    if project_scope == "all" and normalized_project_name is not None:
        raise ModelRetry("字段 project_name：project_scope=all 时必须设为 null")
    return {
        "schema_version": "v1",
        "project_name": normalized_project_name,
        "semantic_query": normalized_query,
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
                        "depth",
                        "is_leaf",
                        "title",
                        "project_id",
                        "project_name",
                        "main_type",
                        "updated_at",
                        "source_count",
                        "excerpt",
                        "matched_fields",
                        "match_hint",
                        "relevance_level",
                    }
                }
            )
        return {
            **{
                key: value
                for key, value in payload.items()
                if key not in {"items", "internal_classifications"}
            },
            "items": items,
        }
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
            "has_more",
            "truncated",
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
        if record.displayable:
            summary["ordered_items"] = [
                {
                    "position": index,
                    "entry_id": item.get("entry_id"),
                    "title": item.get("title"),
                    "project_name": item.get("project_name"),
                    "relevance_level": item.get("relevance_level"),
                }
                for index, item in enumerate(payload.get("items", []), 1)
            ]
        else:
            summary["candidate_count"] = len(payload.get("items", []))
        summary["semantics"] = record.semantics
    elif record.kind == "directories":
        summary["directory_items"] = [
            {
                "position": index,
                "node_id": item.get("node_id"),
                "name": item.get("name"),
                "parent_node_id": item.get("parent_node_id"),
                "path": item.get("path"),
                "depth": item.get("depth"),
                "is_leaf": item.get("is_leaf"),
                "project_id": item.get("project_id"),
                "project_name": item.get("project_name"),
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


def _public_result(result, handle: str, *, result_role: str = "authorized") -> dict:
    return {
        "result_handle": handle,
        "result_role": result_role,
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
        if payload.get("operation") == "find":
            query = payload.get("query") or {}
            return {
                "subject": "directories",
                "query_object": "项目目录定位",
                "display_name": "目录定位结果",
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "project_scope": "项目",
                "directory_name": query.get("name"),
                "directory_path": query.get("path"),
                "match_status": payload.get("match_status"),
                "match": query.get("applied_match"),
                "total_count": payload.get("total_count", 0),
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
            "node_scope": params.get("node_scope"),
            "node_id": params.get("node_id"),
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
            "node_scope": params.get("node_scope"),
            "node_id": params.get("node_id"),
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
            elif not record.displayable:
                errors.append(f"{block.result_handle} 是内部候选，不能进入主答案")
            elif expected == "list" and record.kind not in {"list", "directories"}:
                errors.append(f"{block.result_handle} 不是列表结果")
            elif expected == "statistic" and record.kind != expected:
                errors.append(f"{block.result_handle} 不是 statistic 结果")
        elif block.kind == "text" and (reference := _entry_reference(block.text)):
            result_handle, position = reference
            record = state.result_sets.get(result_handle)
            if record is None or result_handle not in state.current_handles:
                errors.append(f"{result_handle} 不是当前轮结果")
            elif record.kind != "entries":
                errors.append(f"{result_handle} 不是已读取 Entry 结果")
            elif not 1 <= position <= len(record.payload.get("items", [])):
                errors.append(f"{result_handle} 的正文位置越界")
            elif not record.payload["items"][position - 1].get("content"):
                errors.append(f"{result_handle} 的正文未成功读取")
        elif block.kind == "evidence" and block.evidence_handle not in state.current_evidence:
            errors.append(f"{block.evidence_handle} 不是当前轮核验 Evidence")
    candidate_handles = {
        handle
        for handle, record in state.result_sets.items()
        if handle in state.current_handles
        and record.semantics.get("result_role") == "candidate"
        and record.status in {"completed", "empty", "limited"}
    }
    selected_candidates = {
        record.semantics.get("candidate_result_handle")
        for handle, record in state.result_sets.items()
        if handle in state.current_handles
        and record.displayable
        and record.semantics.get("result_role") == "authorized"
    }
    if candidate_handles - selected_candidates:
        errors.append("语义候选必须先完整调用 select_relevant_entries 形成授权集合")
    answer_text = "\n".join(
        block.text
        for block in answer.blocks
        if block.kind in {"text", "insufficient"}
    )
    for record in state.result_sets.values():
        if (
            record.handle not in state.current_handles
            or record.semantics.get("result_role") != "authorized"
        ):
            continue
        candidate = state.result_sets.get(
            str(record.semantics.get("candidate_result_handle") or "")
        )
        rejected_ids = {
            int(item["entry_id"])
            for item in record.payload.get("internal_classifications", [])
            if item.get("relevance") != "direct"
        }
        rejected_titles = {
            str(item.get("title") or "").strip()
            for item in (candidate.payload.get("items", []) if candidate else [])
            if int(item["entry_id"]) in rejected_ids
        }
        if any(title and title in answer_text for title in rejected_titles):
            errors.append("主答案包含间接相关或不相关候选的标题")
            break
    if _entry_content_requested(state.current_message):
        has_entry_result = any(
            handle in state.current_handles
            and record.kind == "entries"
            and any(item.get("content") for item in record.payload.get("items", []))
            for handle, record in state.result_sets.items()
        )
        has_entry_block = any(
            block.kind == "text" and _entry_reference(block.text) for block in answer.blocks
        )
        if has_entry_result and not has_entry_block:
            errors.append("用户要求具体内容时必须提供正文引用，直接展示已读取正文")
    if _definition_question(state.current_message):
        first_text = next(
            (index for index, block in enumerate(answer.blocks) if block.kind == "text"),
            None,
        )
        first_list = next(
            (index for index, block in enumerate(answer.blocks) if block.kind == "list"),
            None,
        )
        if first_list is not None and (first_text is None or first_text > first_list):
            errors.append("定义型问题必须先回答概念和核心结论，再展示直接相关正式记录")
    if _candidate_revision_requested(state.current_message):
        draft_text = "\n".join(
            block.text for block in answer.blocks if block.kind == "text"
        )
        required_sections = {
            "未写入状态": ("尚未写入知识库", "尚未写入正式记录"),
            "原记录内容": ("原记录要点", "原记录已有内容"),
            "新增建议": ("建议补充", "建议新增"),
            "修改后版本": ("修改后候选版本", "候选修改稿"),
        }
        missing = [
            label
            for label, markers in required_sections.items()
            if not any(marker in draft_text for marker in markers)
        ]
        source_boundary_phrases = (
            "不属于原始来源原文",
            "不是原始来源原文",
            "并非来自该来源原文",
            "并非来自原始来源",
            "不来自原始来源",
        )
        has_source_boundary = any(
            phrase in draft_text for phrase in source_boundary_phrases
        ) or (
            "来源边界" in draft_text
            and "来源原文" in draft_text
            and any(negation in draft_text for negation in ("并非", "不是", "不属于"))
        )
        if not has_source_boundary:
            missing.append("来源边界")
        if missing:
            errors.append(f"候选修改稿缺少：{'、'.join(missing)}")
    return errors


def list_position_entry_id(state: LoopState, result_set_handle: str, position: int) -> int:
    """将会话内有序列表位置解析为真实 Entry id。"""
    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "list" else []
    if (
        record is None
        or record.kind != "list"
        or not record.displayable
        or not 1 <= position <= len(items)
    ):
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


def directory_reference_item(
    state: LoopState,
    result_set_handle: str,
    position: int | None = None,
) -> dict:
    """从会话目录句柄解析唯一项或用户指定的实际位置。"""

    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "directories" else []
    if record is None or record.kind != "directories" or not items:
        raise ValueError("目录结果句柄无效、没有候选或类型不正确")
    if position is None:
        if len(items) != 1:
            raise ValueError("目录结果不唯一，必须按候选完整路径指定位置")
        return items[0]
    if not 1 <= position <= len(items):
        raise ValueError("目录结果位置越界")
    return items[position - 1]


def completed_directory_not_found(
    state: LoopState,
    *,
    project_id: int | None,
    project_name: str | None,
) -> tuple[str, ResultRecord] | None:
    """返回当前轮同项目已完整确认的目录未命中结果。"""

    for handle, record in state.result_sets.items():
        if handle not in state.current_handles or record.kind != "directories":
            continue
        payload = record.payload
        project = payload.get("project") or {}
        if (
            payload.get("operation") != "find"
            or payload.get("match_status") != "not_found"
            or record.status != "empty"
            or record.completeness != "complete"
        ):
            continue
        if project_id is not None and project.get("id") != project_id:
            continue
        if project_name is not None and project.get("name") != project_name:
            continue
        return handle, record
    return None


def render_directory_not_found(
    state: LoopState,
) -> tuple[str, list[dict]] | None:
    """为完整目录未命中生成无需模型收尾的确定性回答。"""

    resolved = completed_directory_not_found(state, project_id=None, project_name=None)
    if resolved is None:
        return None
    handle, record = resolved
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "list", "result_handle": handle, "label": "目录定位"}]}
    )
    return render_answer(answer, state)


def _entry_directory_scope(
    state: LoopState,
    *,
    project_scope: str,
    project_name: str | None,
    result_handle: str | None,
    position: int | None,
    scope: Literal["direct", "subtree"] | None,
) -> tuple[str | None, dict]:
    """只从可信会话目录结果生成共享 Entry 工具的 Node 范围。"""

    if result_handle is None:
        if position is not None or scope is not None:
            raise ModelRetry("目录位置或范围必须与 directory_result_handle 同时提供")
        return project_name, {}
    if project_scope != "project":
        raise ModelRetry("目录范围查询必须使用 project_scope=project")
    try:
        item = directory_reference_item(state, result_handle, position)
    except ValueError as exc:
        raise ModelRetry(str(exc)) from exc
    record = state.result_sets[result_handle]
    project = record.payload.get("project") or {}
    actual_project_id = item.get("project_id") or project.get("id")
    actual_project_name = item.get("project_name") or project.get("name")
    if not actual_project_id or not actual_project_name:
        raise ModelRetry("目录结果缺少真实项目身份")
    if project_name is not None and project_name != actual_project_name:
        raise ModelRetry("project_name 与目录结果所属项目不一致")
    return actual_project_name, {
        "project_id": int(actual_project_id),
        "node_id": int(item["node_id"]),
        "node_scope": scope or "subtree",
    }


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
    is_semantic_candidate = kind == "list" and (
        tool_name == "search_knowledge"
        or (params.get("entry_set") or {}).get("semantic_query") is not None
    )
    semantics["result_role"] = "candidate" if is_semantic_candidate else "authorized"
    handle = state.store_result(
        kind,
        payload,
        result.status,
        result.completeness,
        semantics=semantics,
        displayable=not is_semantic_candidate,
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
    public = _public_result(
        result,
        handle,
        result_role="candidate" if is_semantic_candidate else "authorized",
    )
    public["payload"] = _model_payload(kind, payload)
    return public


async def _semantic_search_dispatch(
    ctx: RunContext[LoopDeps],
    *,
    search_key: str,
    dispatch_tool: str,
    params: dict,
    surface_tool: str,
    audit_params: dict,
) -> dict:
    """串行执行或复用等价语义查询，跨两个表面入口共享成功结果。"""

    state = ctx.deps.state
    async with state.semantic_search_lock:
        existing_handle = state.semantic_search_results.get(search_key)
        existing = state.result_sets.get(existing_handle) if existing_handle else None
        if existing is not None:
            state.current_handles.add(existing.handle)
            event = {
                "tool": surface_tool,
                "shared_tool": dispatch_tool,
                "result_handle": existing.handle,
                "status": "not_executed",
                "completeness": existing.completeness,
                "params": audit_params,
                "shared_params": params,
                "result_summary": _tool_result_summary(existing.payload),
                "reason_code": "duplicate_semantic_query",
                "error": "等价语义查询已成功完成，本次复用既有结果而未重复执行",
                "duration_ms": 0,
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return {
                **event,
                "result_role": existing.semantics.get("result_role", "candidate"),
                "payload": _model_payload(existing.kind, existing.payload),
            }
        result = await _dispatch(
            ctx,
            dispatch_tool,
            params,
            "list",
            surface_tool=surface_tool,
            audit_params=audit_params,
        )
        handle = result.get("result_handle")
        record = state.result_sets.get(handle)
        if record is not None:
            record.semantics["search_key"] = search_key
        if record is not None and result.get("status") in {
            "completed",
            "empty",
            "limited",
        }:
            state.semantic_search_results[search_key] = record.handle
        return result


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

    @agent.instructions
    def relevance_selection_instruction(ctx: RunContext[LoopDeps]) -> str:
        if ctx.deps.state.instrumentation.phase == "finalize":
            return ""
        return (
            "语义候选先用 select_relevant_entries 全量三分；仅 direct 授权句柄可展示或读取，"
            "无 direct 不凑数。同义查询只用一个搜索入口，查询后再选择和读取。"
            "定义问题先答概念再列直接记录，并区分通用知识、正式记录与 Source。"
        )

    @agent.instructions
    def contextual_search_follow_up_instruction(ctx: RunContext[LoopDeps]) -> str:
        if not _contextual_search_follow_up(ctx.deps.state.current_message):
            return ""
        return (
            "当前消息是对上一轮建议的承接查询，不包含新主题。请从历史用户原话、已展示回答和"
            "工具条件复用上一轮主题与项目范围，只选择 search_knowledge 或 query_entries 一个"
            "语义搜索入口；不要把‘好的’或‘帮我查一下’本身作为 query。"
        )

    @agent.instructions
    def candidate_revision_instruction(ctx: RunContext[LoopDeps]) -> str:
        if not _candidate_revision_requested(ctx.deps.state.current_message):
            return ""
        return (
            "当前请求只要求生成候选修改稿，用户将自行审核或更新，不是写入正式记录。"
            "不要调用 report_unsupported 或任何写入工具；直接用 final_result 的 text 块输出，"
            "明确尚未写入知识库，并区分原记录要点、建议补充、修改后候选版本和来源边界说明。"
        )

    @agent.instructions
    def entry_content_instruction(ctx: RunContext[LoopDeps]) -> str:
        if not _entry_content_requested(ctx.deps.state.current_message):
            return ""
        return (
            "用户要求具体内容、正文、完整内容或展开记录。完成 read_entries 后，必须追加一个"
            "text 块，且 text 严格写成 [[entry:结果句柄:位置]]（位置从 1 开始）来引用真实正文；"
            "程序会将该标记渲染为正文块。Evidence 只表示出处，不能替代 Entry 正文。"
        )

    @agent.tool
    async def report_unsupported(
        ctx: RunContext[LoopDeps], target: str, reason: str
    ) -> dict:
        """当前白名单没有支持目标对象的只读能力时，记录能力不足并停止尝试替代查询。"""

        if _candidate_revision_requested(ctx.deps.state.current_message):
            raise ModelRetry(
                "当前用户只要求生成供审核的候选修改稿，不是写入请求。请不要调用 "
                "report_unsupported，改用 final_result 输出候选稿，并明确尚未写入知识库。"
            )

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
    async def select_relevant_entries(
        ctx: RunContext[LoopDeps],
        candidate_result_handle: str,
        classifications: list[RelevanceDecision],
    ) -> dict:
        """把语义候选逐项分为 direct/indirect/unrelated，并只授权 direct。

        必须覆盖候选中的每个 entry_id 且不得新增或重复。direct 表示标题或正文明确回答
        当前主题；indirect 只涉及相关材料、场景或风险；unrelated 只有弱语义相似。
        """

        state = ctx.deps.state
        candidate_result_handle = _none_if_string_null(candidate_result_handle) or ""
        record = state.result_sets.get(candidate_result_handle)
        if (
            record is None
            or candidate_result_handle not in state.current_handles
            or record.kind != "list"
            or record.semantics.get("result_role") != "candidate"
        ):
            raise ModelRetry("candidate_result_handle 不是当前可分类的语义候选")
        candidate_items = record.payload.get("items", [])
        candidate_ids = [int(item["entry_id"]) for item in candidate_items]
        decision_ids = [item.entry_id for item in classifications]
        if len(decision_ids) != len(set(decision_ids)):
            raise ModelRetry("classifications 中的 entry_id 不得重复")
        if set(decision_ids) != set(candidate_ids):
            raise ModelRetry("classifications 必须且只能覆盖候选中的全部 entry_id")
        try:
            await state.ledger.reserve_tool()
        except BudgetExceeded as exc:
            _mark_budget_stop(
                state,
                exc,
                tool_name="select_relevant_entries",
                params={"candidate_result_handle": candidate_result_handle},
            )
            raise
        by_id = {item.entry_id: item for item in classifications}
        direct_items = [
            {**item, "relevance_level": "direct"}
            for item in candidate_items
            if by_id[int(item["entry_id"])].relevance == "direct"
        ]
        counts = {
            level: sum(1 for item in classifications if item.relevance == level)
            for level in ("direct", "indirect", "unrelated")
        }
        payload = {
            **{
                key: value
                for key, value in record.payload.items()
                if key not in {"items", "returned_count", "has_more"}
            },
            "items": direct_items,
            "returned_count": len(direct_items),
            "has_more": False,
            "candidate_count": len(candidate_items),
            "internal_classifications": [
                {
                    "entry_id": item.entry_id,
                    "relevance": item.relevance,
                    "reason": item.reason[:300],
                }
                for item in classifications
            ],
        }
        semantics = {
            **record.semantics,
            "result_role": "authorized",
            "relevance_scope": "direct",
            "display_name": "直接相关正式记录",
            "candidate_result_handle": candidate_result_handle,
            "classification_counts": counts,
            "total_count": len(direct_items),
            "returned_count": len(direct_items),
            "has_more": False,
        }
        status = "completed" if direct_items else "empty"
        handle = state.store_result(
            "list",
            payload,
            status,
            record.completeness,
            semantics=semantics,
            displayable=True,
        )
        state.authorized_entry_ids.update(
            int(item["entry_id"]) for item in direct_items
        )
        search_key = record.semantics.get("search_key")
        if search_key:
            state.semantic_search_results[search_key] = handle
        event = {
            "tool": "select_relevant_entries",
            "shared_tool": "select_relevant_entries",
            "result_handle": handle,
            "status": status,
            "completeness": record.completeness,
            "params": {"candidate_result_handle": candidate_result_handle},
            "result_summary": {
                "candidate_count": len(candidate_items),
                "returned_count": len(direct_items),
                "classification_counts": counts,
                "has_more": False,
            },
            "reason_code": "direct_results_authorized",
            "error": None,
            "duration_ms": 0,
            "turn_index": state.turn_index,
        }
        state.tool_events.append(event)
        return {
            **event,
            "result_role": "authorized",
            "payload": _model_payload("list", payload),
        }

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
        parent_node_id: int | str | None = None,
        parent_result_handle: str | None = None,
        parent_position: int | str | None = None,
        operation: Literal["children", "find", "leaf_summary"] = "children",
        name: str | None = None,
        path: str | None = None,
        match: Literal["exact", "contains"] = "exact",
        limit: int = 20,
    ) -> dict:
        """查询 Project 的真实 Node 目录。

        children 不传父节点时返回一级目录、传父节点时返回直接子目录；leaf_summary
        一次返回整棵项目目录树的真实叶子节点总数和一级目录分组，且不能传父节点。
        用户给出目录名称或完整路径时直接使用 find，不先遍历根目录；exact 精确匹配
        优先，contains 只在没有精确结果时使用。目录与 Entry、知识类型和信息性质完全
        不同。追问目录时复用上一轮 parent_result_handle；结果唯一时可省略位置，多候选时
        必须同时提供 1-based parent_position。
        """
        state = ctx.deps.state
        project_name = _none_if_string_null(project_name)
        parent_node_id = _optional_int(parent_node_id, "parent_node_id")
        parent_result_handle = _none_if_string_null(parent_result_handle)
        parent_position = _optional_int(parent_position, "parent_position")
        name = _none_if_string_null(name)
        path = _none_if_string_null(path)
        if operation == "leaf_summary" and (
            parent_node_id is not None
            or parent_result_handle is not None
            or parent_position is not None
        ):
            raise ModelRetry("叶子节点聚合不能指定父节点或目录位置")
        if operation == "find" and (
            parent_node_id is not None
            or parent_result_handle is not None
            or parent_position is not None
        ):
            raise ModelRetry("目录定位不能指定父节点或目录位置")
        if parent_result_handle is not None or parent_position is not None:
            if parent_result_handle is None:
                raise ModelRetry("目录位置必须与 parent_result_handle 同时提供")
            try:
                resolved_item = directory_reference_item(
                    state, parent_result_handle, parent_position
                )
                resolved_parent = int(resolved_item["node_id"])
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
            "name": name,
            "path": path,
            "match": match,
            "limit": limit,
        }
        prior_not_found = (
            completed_directory_not_found(
                state,
                project_id=project_id,
                project_name=project_name,
            )
            if operation == "children"
            and parent_result_handle is None
            else None
        )
        if prior_not_found is not None:
            result_handle, record = prior_not_found
            event = {
                "tool": "list_project_directories",
                "shared_tool": "list_project_directories",
                "result_handle": result_handle,
                "status": "not_executed",
                "completeness": "complete",
                "params": params,
                "reason_code": "directory_lookup_already_resolved",
                "error": None,
                "duration_ms": 0,
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return {**event, "payload": _model_payload(record.kind, record.payload)}
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
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]]
        | str
        | None = None,
        directory_result_handle: str | None = None,
        directory_position: int | str | None = None,
        directory_scope: Literal["direct", "subtree"] | str | None = None,
    ) -> dict:
        """精确统计正式记录总数；目录范围只能从已有目录结果句柄解析。"""
        project_name = _none_if_string_null(project_name)
        main_types = _optional_main_types(main_types)
        directory_result_handle = _none_if_string_null(directory_result_handle)
        directory_position = _optional_int(directory_position, "directory_position")
        directory_scope = _optional_directory_scope(directory_scope)
        project_name, node_scope = _entry_directory_scope(
            ctx.deps.state,
            project_scope=project_scope,
            project_name=project_name,
            result_handle=directory_result_handle,
            position=directory_position,
            scope=directory_scope,
        )
        params = _count_params(project_scope, project_name, main_types)
        params.update(node_scope)
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
                "directory_result_handle": directory_result_handle,
                "directory_position": directory_position,
                "directory_scope": directory_scope,
            },
        )

    @agent.tool
    async def group_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        group_by: Literal["project", "main_type", "info_nature", "updated_month"],
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]]
        | str
        | None = None,
        directory_result_handle: str | None = None,
        directory_position: int | str | None = None,
        directory_scope: Literal["direct", "subtree"] | str | None = None,
    ) -> dict:
        """按明确维度统计正式记录；目录范围只能从已有目录结果句柄解析。"""
        project_name = _none_if_string_null(project_name)
        main_types = _optional_main_types(main_types)
        directory_result_handle = _none_if_string_null(directory_result_handle)
        directory_position = _optional_int(directory_position, "directory_position")
        directory_scope = _optional_directory_scope(directory_scope)
        project_name, node_scope = _entry_directory_scope(
            ctx.deps.state,
            project_scope=project_scope,
            project_name=project_name,
            result_handle=directory_result_handle,
            position=directory_position,
            scope=directory_scope,
        )
        params = _group_params(project_scope, project_name, group_by, main_types)
        params.update(node_scope)
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
                "directory_result_handle": directory_result_handle,
                "directory_position": directory_position,
                "directory_scope": directory_scope,
            },
        )

    @agent.tool
    async def query_entries(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        semantic_query: str | None,
        limit: int = 10,
        sort_field: Literal["relevance", "updated_at", "created_at"] | None = None,
        sort_direction: Literal["asc", "desc"] | None = None,
        sort: LegacySort | str | None = None,
        main_types: list[Literal["knowledge", "method", "parameter", "reminder"]]
        | str
        | None = None,
        directory_result_handle: str | None = None,
        directory_position: int | str | None = None,
        directory_scope: Literal["direct", "subtree"] | str | None = None,
    ) -> dict:
        """按结构化条件查询列表。

        首选 sort_field/sort_direction；兼容旧式 sort={field,direction}。可空字段
        的字符串 "null" 只按未提供处理。目录范围只接受已定位结果，且不能做语义搜索。
        """
        project_name = _none_if_string_null(project_name)
        semantic_query = _none_if_string_null(semantic_query)
        main_types = _optional_main_types(main_types)
        directory_result_handle = _none_if_string_null(directory_result_handle)
        directory_position = _optional_int(directory_position, "directory_position")
        directory_scope = _optional_directory_scope(directory_scope)
        sort_field, sort_direction = _normalized_sort(
            semantic_query=semantic_query,
            sort_field=sort_field,
            sort_direction=sort_direction,
            sort=sort,
        )
        project_name, node_scope = _entry_directory_scope(
            ctx.deps.state,
            project_scope=project_scope,
            project_name=project_name,
            result_handle=directory_result_handle,
            position=directory_position,
            scope=directory_scope,
        )
        params = {
            "entry_set": _entry_set(project_scope, project_name, semantic_query, main_types),
            "limit": min(max(limit, 1), 10),
            "sort": {"field": sort_field, "direction": sort_direction},
            **node_scope,
        }
        audit_params = {
            "project_scope": project_scope,
            "project_name": project_name,
            "semantic_query": semantic_query,
            "main_types": list(main_types or []),
            "limit": params["limit"],
            "sort": params["sort"],
            "directory_result_handle": directory_result_handle,
            "directory_position": directory_position,
            "directory_scope": directory_scope,
        }
        if semantic_query is not None:
            search_key = _semantic_query_key(
                project_scope=project_scope,
                project_name=project_name,
                query=semantic_query,
                main_types=list(main_types or []),
                node_scope=node_scope,
            )
            result = await _semantic_search_dispatch(
                ctx,
                search_key=search_key,
                dispatch_tool="query_entries",
                params=params,
                surface_tool="query_entries",
                audit_params=audit_params,
            )
        else:
            result = await _dispatch(
                ctx,
                "query_entries",
                params,
                "list",
                audit_params=audit_params,
            )
        ids = [item["entry_id"] for item in result.get("payload", {}).get("items", [])]
        try:
            ctx.deps.state.ledger.reserve_entries(ids)
        except BudgetExceeded as exc:
            _mark_budget_stop(ctx.deps.state, exc, tool_name="query_entries")
            raise
        if semantic_query is None:
            ctx.deps.state.authorized_entry_ids.update(ids)
        return result

    @agent.tool
    async def search_knowledge(
        ctx: RunContext[LoopDeps],
        project_scope: Literal["all", "project"],
        project_name: str | None,
        query: str,
    ) -> dict:
        """搜索正式记录；指定项目时使用严格项目范围，结果不能用于精确计数。"""
        project_name = _none_if_string_null(project_name)
        if project_scope == "project":
            params = {
                "entry_set": _entry_set(project_scope, project_name, query, None),
                "limit": 10,
                "sort": {"field": "relevance", "direction": "desc"},
            }
            dispatch_tool = "query_entries"
        else:
            if project_name is not None:
                raise ModelRetry("字段 project_name：project_scope=all 时必须设为 null")
            params = {"query": query}
            dispatch_tool = "search_knowledge"
        audit_params = {
            "project_scope": project_scope,
            "project_name": project_name,
            "query": query,
        }
        search_key = _semantic_query_key(
            project_scope=project_scope,
            project_name=project_name,
            query=query,
        )
        result = await _semantic_search_dispatch(
            ctx,
            search_key=search_key,
            dispatch_tool=dispatch_tool,
            params=params,
            surface_tool="search_knowledge",
            audit_params=audit_params,
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
        """读取授权结果集合中的 Entry 正文；原始语义候选或任意新 id 会被拒绝。"""
        state = ctx.deps.state
        unauthorized = sorted(set(entry_ids) - state.authorized_entry_ids)
        authorized = _authorized_list_for_entry_ids(state, entry_ids)
        if unauthorized or authorized is None:
            raise ModelRetry(
                "read_entries 必须按同一授权展示集合的完整顺序读取；语义候选必须先调用 "
                f"select_relevant_entries。未授权 entry_ids={unauthorized}"
            )
        try:
            state.ledger.reserve_entries(entry_ids)
        except BudgetExceeded as exc:
            _mark_budget_stop(state, exc, tool_name="read_entries")
            raise
        result = await _dispatch(ctx, "read_entries", {"entry_ids": entry_ids}, "entries")
        payload = result.get("payload", {})
        state.read_entry_ids.update(
            int(item["entry_id"]) for item in payload.get("items", [])
        )
        unavailable_only = (
            result.get("status") == "denied"
            and payload.get("unavailable_entry_ids")
            and not payload.get("denied_entry_ids")
        )
        if result.get("status") in {"partial", "error"} or unavailable_only:
            continuation = ContinuationState(
                task_type="read_entries",
                tool_name="read_entries",
                scope={
                    "entry_ids": entry_ids,
                    "authorized_result_handle": authorized[0],
                },
                completed_steps=[
                    {
                        "tool": "semantic_search",
                        "result_set_handle": authorized[0],
                    }
                ],
                pending_steps=[{"tool": "read_entries", "entry_ids": entry_ids}],
                confirmed=[{"entry_id": value} for value in sorted(state.authorized_entry_ids)],
                stop_reason=str(result.get("error") or "Entry 正文读取失败"),
            )
            state.stop(
                StopState(
                    status=TURN_PARTIAL_COMPLETED,
                    reason_code="search_succeeded_read_failed",
                    reason=str(result.get("error") or "搜索成功，但 Entry 正文读取失败"),
                    incomplete_steps=["搜索已完成；正文尚未完整读取"],
                    can_continue=True,
                    continuation=continuation,
                )
            )
        elif result.get("status") in {"completed", "empty"}:
            if state.active_continuation and state.active_continuation.task_type == "read_entries":
                state.continuation = None
                state.active_continuation = None
        return result

    @agent.tool
    async def read_evidence(
        ctx: RunContext[LoopDeps], entry_id: int, source_ids: list[int]
    ) -> dict:
        """当前轮重新核验已发现 Entry 的真实 Source 原文并创建 Evidence。"""
        if entry_id not in ctx.deps.state.authorized_entry_ids:
            raise ModelRetry("read_evidence 只能读取授权展示集合中的 Entry")
        if entry_id not in ctx.deps.state.read_entry_ids:
            raise ModelRetry("读取 Source 前必须先成功执行 read_entries")
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
        state.read_entry_ids.update(item.entry_id for item in output.items)
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
        if block.kind == "insufficient" or (
            block.kind == "text" and _entry_reference(block.text) is None
        ):
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
                query = record.payload.get("query") or {}
                if record.payload.get("match_status") == "not_found":
                    if query.get("path"):
                        title = (
                            f"{project_name} · 未找到完整路径「{query['path']}」对应的目录。"
                        )
                    else:
                        title = f"{project_name} · 未找到名为「{query.get('name')}」的目录。"
                else:
                    title = f"{project_name} · {semantics.get('display_name', '项目目录')}"
            else:
                scope = (
                    f"{semantics.get('project_name')} · "
                    if semantics.get("project_name")
                    else "全部项目 · "
                )
                title = (
                    f"{scope}直接相关正式记录"
                    if semantics.get("relevance_scope") == "direct"
                    else f"{scope}正式记录列表"
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
        elif block.kind == "text" and (reference := _entry_reference(block.text)):
            result_handle, position = reference
            record = state.result_sets[result_handle]
            items = record.payload.get("items", [])
            item = items[position - 1]
            content = item.get("content") or ""
            text = f"《{item.get('title', '未命名知识')}》正文：\n{content}"
            lines.append(text)
            rendered.append(
                {
                    "kind": "entry",
                    "handle": result_handle,
                    "position": position,
                    "label": "已读取知识正文",
                    "text": text,
                    "entry_id": item.get("entry_id"),
                    "title": item.get("title"),
                    "content": content,
                    "project_name": item.get("project_name"),
                    "node_path": item.get("node_path"),
                    "status": record.status,
                    "completeness": record.completeness,
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
        TURN_NOT_EXECUTED: "本轮查询未执行，以下说明具体原因和缺口。",
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
        if not record.displayable:
            continue
        if record.kind == "statistic":
            requested_blocks.append(
                {"kind": "statistic", "result_handle": handle, "label": "已确认统计"}
            )
        elif record.kind in {"list", "directories"}:
            requested_blocks.append(
                {"kind": "list", "result_handle": handle, "label": "已确认列表"}
            )
        elif record.kind == "entries":
            for position, item in enumerate(record.payload.get("items", []), 1):
                if item.get("content"):
                    requested_blocks.append(
                        {
                            "kind": "text",
                            "text": f"[[entry:{handle}:{position}]]",
                        }
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
        deterministic = render_directory_not_found(state)
        if deterministic is not None:
            # 目录定位的完整空结果已经是服务端确定性结论，不需要再派发收尾模型。
            state.instrumentation.phase = "solve"
            state.instrumentation.finalize_reason = None
            state.instrumentation.finalize_status = "not_needed"
            state.instrumentation.finalize_error = None
            state.instrumentation.finalize_failure = None
            text, blocks = deterministic
            status = TURN_COMPLETED
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
        if status in {TURN_NOT_EXECUTED, TURN_UNSUPPORTED, TURN_DENIED, TURN_FAILED}:
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
