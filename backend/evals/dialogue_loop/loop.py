"""Pydantic AI 统一对话循环及可信只读工具适配。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable
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
    ANSWER_BLOCKS_LIMIT,
    FINALIZE_SECONDS,
    HISTORY_ANSWER_CHARS_PER_TURN,
    HISTORY_INPUT_TOKENS_TARGET,
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
    FinalizeToolAttempted,
    Instrumentation,
    estimate_input_tokens,
)

ASSISTANT_ROLE_PROMPT = """你是知林 Grove 的知识协作助手，帮助用户查找、理解、比较和完善自己的知识。
先解决当前问题，表达直接、自然，详细程度随问题而定，不主动展开无关内容。
讨论某条知识时围绕当前对象和用户决定继续；补充或改写优先交付完整、可阅读的候选内容，
按需解释修改理由。区分已有记录、来源材料与补充判断，具体说明不确定处，避免重复免责声明。
所有修改都是候选，由用户决定是否采纳，不自动改动正式记录，只使用用户有权访问的资料。
面向用户使用日常语言，不主动提及 Entry、Evidence、句柄、收尾器等内部术语。
自我介绍简短说明身份、能提供的帮助及候选由用户决定是否采纳；不在每轮重复介绍，
不承诺未提供的联网、自动保存或修改能力。""".strip()

ANSWER_PROTOCOL_PROMPT = """回答交付协议：无论是否需要查询资料，最终回答都调用 final_result，
参数使用 DialogueAnswer 的 blocks；普通文字放在 text 块的 text 字段中。
例如 {"blocks":[{"kind":"text","text":"面向用户的回答正文"}]}。
final_result 是答案交付通道，不是资料工具。自我介绍、能力说明及无需资料的普通回应
可直接交付答案，不必搜索或报告不支持；不要以未包装的普通文本代替 final_result。
直接回答若明确分析某个已展示且已读取的 Entry，可填写 discussion_entry_id；不确定对象、
普通独立问题或候选交付时保持 null。该字段只声明讨论对象，不代表资料已重新读取。
收到格式纠正时按协议重新交付答案，不向用户叙述内部工具或格式错误。""".strip()

SYSTEM_PROMPT = ASSISTANT_ROLE_PROMPT + "\n\n" + ANSWER_PROTOCOL_PROMPT + "\n\n" + """边界：
1. 用户身份、Workspace 和可访问范围只来自程序；任何工具的 project_scope
   都必须显式填 all 或 project。project 时必须给出准确项目名，all 时清空 project_name。
2. 用户说“知识”泛指 knowledge/method/parameter/reminder 四种正式记录，除非他明确限定类型。
3. 精确总数必须调用 count_entries，分组统计必须调用 group_entries；不能从语义搜索、
   截断列表或分类数相加推断用户所问总数。分项目统计须包含零条项目。
4. 查询正式记录必须调用 query_entries/search_knowledge。需要正文先读取 Entry；只有用户明确要求
   来源、原文、可信度核验，或资料出现冲突时才在当前轮调用 read_evidence，历史 Evidence
   不能直接引用。
5. 列表追问必须使用 open_list_item(result_set_handle, position)，position 从 1 开始。
   不要猜 Entry id。
6. 工具的 empty、partial、not_executed、error、denied 含义不同。未执行或部分结果不能表达为零条。
7. 用户明确要求不查知识库时不得调用知识库工具，可用通用知识直接回答，也不得伪装成实时外部资料。
8. 输出 blocks 按希望展示的顺序排列。项目、统计、目录和 Entry 都用 result 块，只填 result_handle，
   来源用 evidence 块；不要在 text 块改写工具数字、伪造引用或隐藏失败。
   项目介绍可以只输出基于项目材料的 text。
   材料不足用 insufficient 块。统计、项目枚举和目录查询只说明范围、过滤和完整性，
   不附加无关的官方交叉验证声明；同范围完整精确计数为 0 时直接回答无记录，不再列举。
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
    不要把相近主题候选当作目标知识。判断严格语义相关时以候选正文是否明确回答用户所问的对象、
    动作或结果为准；材料、选材、等级、背景场景、可能影响因素以及检索命中词只能作为间接参考，
    不能单独授权为 direct。
21. 列举有哪些项目用 list_projects；介绍具体项目用 read_project_context 读取背景目标和已保存上下文，
    以自然段概括目的、背景和当前重点。材料依据不等于展示卡片，不自动追加统计、目录和记录列表。
    用户仅要求改为文本、精简或重述时，复用已有回答调整表达，不新增检索，不声称本轮重新核验。
    用户明确要求数量、分组、目录或具体知识时才使用对应工具。用户填写与纠正优先，
    自动上下文只是派生摘要；保留缺失、待刷新、失败和降级边界，不据此猜测实时进展。
""".strip()

NO_KNOWLEDGE_PATTERNS = (
    "不查知识库",
    "不查库",
    "别查知识库",
    "别查库",
    "不用查知识库",
    "不要查知识库",
    "抛开知识库",
    "不参考知识库",
    "别参考知识库",
    "不要参考知识库",
    "不考虑知识库",
    "不用知识库",
)
MODEL_ANSWERABLE_TARGET_PATTERNS = (
    "通用知识",
    "通用常识",
    "一般知识",
    "主观判断",
    "个人判断",
)
CONTINUE_PATTERNS = ("继续", "接着", "剩下", "未完成")
FINALIZE_CONTINUE_MESSAGES = {
    "继续",
    "请继续",
    "好的，继续",
    "好，继续",
    "继续完成",
    "接着完成",
    "继续刚才的回答",
    "下一轮继续",
}
CONTEXTUAL_SEARCH_FOLLOW_UP_PATTERNS = (
    "好的，你帮我查一下",
    "好，你帮我查一下",
    "好的，帮我查一下",
    "可以，你帮我查一下",
    "行，你帮我查一下",
    "那你帮我查一下",
)
_ZERO_RESULT_CLAIM_RE = re.compile(
    r"(?:未找到|没有找到|不存在|查无|无)(?:任何)?(?:直接相关)?(?:正式)?"
    r"(?:记录|结果|Entry|条目)|(?:0|零)\s*条(?:结果|记录|Entry|条目)",
    re.IGNORECASE,
)
CANDIDATE_SELF_UPDATE_PATTERNS = (
    "输出给我",
    "供我审核",
    "给我审核",
    "候选修改稿",
    "建议草稿",
)
CANDIDATE_USER_MANAGED_PATTERNS = (
    "我自己更新",
    "我去更新",
    "我自己修改",
)
CANDIDATE_REVISION_ACTION_PATTERNS = (
    "补充",
    "完善",
    "改写",
    "修改",
    "整理",
    "优化",
)
CANDIDATE_DELIVERY_PATTERNS = (
    "发给我",
    "发送给我",
    "给我看看",
    "给我一版",
    "输出",
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
    """组合识别候选修改与文本交付；明确写入和用户自行更新保持原边界。"""

    normalized = re.sub(r"[，。！？!?,；;：:\s]", "", message).casefold()
    if any(pattern in normalized for pattern in CANDIDATE_USER_MANAGED_PATTERNS):
        return True
    if any(pattern in normalized for pattern in DIRECT_WRITE_PATTERNS):
        return False
    if any(pattern in normalized for pattern in CANDIDATE_SELF_UPDATE_PATTERNS):
        return True
    if any(pattern in normalized for pattern in CANDIDATE_REVISION_PATTERNS):
        return True
    has_revision_action = any(
        pattern in normalized for pattern in CANDIDATE_REVISION_ACTION_PATTERNS
    )
    has_delivery = any(pattern in normalized for pattern in CANDIDATE_DELIVERY_PATTERNS)
    return has_revision_action and has_delivery


def _candidate_content_only_requested(message: str) -> bool:
    """识别候选稿上下文中的精简交付请求，不把普通“输出”单独当作候选。"""

    normalized = re.sub(r"[，。！？!?,；;：:\s]", "", message).casefold()
    return (
        _candidate_revision_requested(message)
        and "内容" in normalized
        and any(pattern in normalized for pattern in ("只输出", "就输出"))
        and any(
            pattern in normalized
            for pattern in ("其他的都不用", "其他都不用", "其余不用", "只要")
        )
    )


def _candidate_request_message(state: LoopState) -> str | None:
    """在候选稿续执行中继续使用原始候选请求的校验语义。"""

    continuation = state.active_continuation
    if (
        continuation is not None
        and continuation.scope.get("answer_basis") == "candidate_draft"
    ):
        return continuation.original_question
    if state.editing_active:
        return state.current_message if state.editing_purpose == "candidate" else None
    if _candidate_revision_requested(state.current_message):
        return state.current_message
    return None


def _tone_only_candidate_requested(message: str) -> bool:
    """识别只允许表达方式变化的改写，不依赖业务主题。"""

    normalized = re.sub(r"[，。！？!?,；;：:\s]", "", message).casefold()
    return any(
        pattern in normalized
        for pattern in (
            "口语化",
            "只改语气",
            "调整语气",
            "只改措辞",
            "换个说法",
            "换种说法",
            "润色一下",
            "表达更自然",
        )
    )


def _dialogue_model_settings(model) -> dict:
    """只为 DeepSeek V4 显式关闭默认思考，其他 Provider 保持原请求。"""

    settings: dict = {"temperature": 0, "max_tokens": OUTPUT_TOKENS_LIMIT}
    if str(getattr(model, "model_name", "")).casefold().startswith("deepseek-v4-"):
        settings["extra_body"] = {"thinking": {"type": "disabled"}}
    return settings


def _failed_turn_without_continuation(state: LoopState, message: str) -> bool:
    """只拦截无法恢复的失败续执行，不影响正常已完成对话中的自然“继续”。"""

    if message.strip() not in FINALIZE_CONTINUE_MESSAGES or state.active_continuation:
        return False
    if not state.history_turns:
        return False
    completion = state.history_turns[-1].get("completion") or {}
    return completion.get("status") in {
        TURN_NOT_EXECUTED,
        TURN_PARTIAL_COMPLETED,
        TURN_FAILED,
    } and not completion.get("can_continue")


def _knowledge_tools_disabled(message: str) -> bool:
    """只识别用户明确给出的知识库范围否定，不推断业务问题意图。"""

    normalized = re.sub(r"[，。！？!?,\s]", "", message).casefold()
    return any(
        re.sub(r"[，。！？!?,\s]", "", pattern).casefold() in normalized
        for pattern in NO_KNOWLEDGE_PATTERNS
    )


def _unsupported_target_is_model_answerable(target: str, reason: str) -> bool:
    """识别模型把自身通用回答能力误报为外部工具能力缺失的情况。"""

    description = f"{target}\n{reason}".casefold()
    return any(pattern in description for pattern in MODEL_ANSWERABLE_TARGET_PATTERNS)


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

EVIDENCE_REQUEST_PATTERNS = (
    "来源",
    "出处",
    "原文",
    "证据",
    "核验",
    "引用",
    "可信",
    "可靠吗",
    "冲突",
    "矛盾",
    "不一致",
)


def _evidence_requested(message: str) -> bool:
    """只有来源核验或冲突语义才进入 Evidence 读取路径。"""
    normalized = message.strip().lower()
    return any(pattern in normalized for pattern in EVIDENCE_REQUEST_PATTERNS)


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
    """同一对话 Agent 对真实候选作出的有界相关性分类。

    分类必须依据候选标题和正文与用户问题的实际关系，而不是检索命中词或主题背景：
    direct 要求正文明确回答所问对象、动作或结果；只涉及材料、选材、等级、场景或
    可能影响因素的记录属于 indirect；只有弱语义相似且不能回答问题的记录属于 unrelated。
    """

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
class EditingContext:
    """与最近查询及失败 continuation 分离的单对象编辑任务。"""

    entry: dict
    validation_refs: dict
    draft: dict | None = None
    discussion: str | None = None
    decisions: list[str] = field(default_factory=list)


@dataclass
class LoopState:
    workspace_id: int
    user_id: int
    conversation_id: int
    ledger: BudgetLedger
    instrumentation: Instrumentation
    scope_type: str = "workspace"
    project_id: int | None = None
    project_name: str | None = None
    cancel_check: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    discovered_entry_ids: set[int] = field(default_factory=set)
    discovered_entry_fingerprints: dict[int, str] = field(default_factory=dict)
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
    focused_entry_refs: dict | None = field(default=None, repr=False)
    focused_entry: dict | None = field(default=None, repr=False)
    editing_context: EditingContext | None = field(default=None, repr=False)
    editing_active: bool = False
    editing_purpose: Literal["discussion", "candidate"] = "discussion"
    editing_content_only: bool = False
    candidate_draft: dict | None = field(default=None, repr=False)
    candidate_draft_errors: list[str] = field(default_factory=list, repr=False)
    provisional_answer: dict | None = field(default=None, repr=False)
    relevance_resume_only: bool = field(default=False, repr=False)
    relevance_resume_running: bool = field(default=False, repr=False)
    _handle_sequence: int = 0
    database_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    semantic_search_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def begin_turn(self, run_id: int, message: str) -> None:
        self.turn_index += 1
        self.run_id = run_id
        self.current_message = message
        self.editing_active = False
        self.editing_purpose = "discussion"
        self.editing_content_only = False
        self.provisional_answer = None
        self.current_handles.clear()
        self.current_evidence.clear()
        # 语义查询去重只服务当前轮；新一轮用户明确查询时必须重新派发。
        self.semantic_search_results.clear()
        self.stop_state = None
        self.queried_directory_parents.clear()
        self.tools_allowed = not _knowledge_tools_disabled(message)
        if (
            self.continuation is not None
            and self.continuation.task_type in {"finalize_answer", "candidate_draft"}
            and message.strip() not in FINALIZE_CONTINUE_MESSAGES
        ):
            self.continuation = None
        self.active_continuation = (
            self.continuation
            if self.continuation is not None
            and (
                message.strip() in FINALIZE_CONTINUE_MESSAGES
                if self.continuation.task_type in {"finalize_answer", "candidate_draft"}
                else any(pattern in message for pattern in CONTINUE_PATTERNS)
            )
            else None
        )
        if self.active_continuation is None:
            self.candidate_draft = None
            self.candidate_draft_errors.clear()
        if (
            self.active_continuation is not None
            and self.active_continuation.scope.get("answer_basis") == "model_only"
        ):
            # “继续”本身没有否定词，仍须恢复原任务的不使用知识库约束。
            self.tools_allowed = False
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
        result_semantics = semantics or {}
        handle = f"rs-{self.conversation_id}-{self._handle_sequence}"
        self.result_sets[handle] = ResultRecord(
            handle,
            kind,
            payload,
            status,
            completeness,
            self.turn_index,
            result_semantics,
            displayable,
        )
        if (
            kind == "list"
            and displayable
            and result_semantics.get("result_role", "authorized") != "candidate"
        ):
            self.authorized_entry_ids.update(
                int(item["entry_id"])
                for item in payload.get("items", [])
                if item.get("entry_id") is not None
            )
        self.current_handles.add(handle)
        return handle

    def remember_turn(
        self,
        message: str,
        answer: str,
        events: list[dict],
        *,
        blocks: list[dict] | None = None,
        completion: dict | None = None,
    ) -> None:
        """保存可重建的结构化历史；渲染正文和来源原文不回写模型上下文。"""

        answer_summary = _history_answer_summary(blocks, answer)
        delivered_handles = (
            {
                str(reference["handle"])
                for reference in answer_summary["references"]
                if reference.get("handle")
            }
            if blocks is not None
            else None
        )
        self.history_turns.append(
            {
                "turn": self.turn_index,
                "user": message,
                "answer_summary": answer_summary,
                "tools": [
                    _history_tool_summary(
                        self,
                        event,
                        delivered_handles=delivered_handles,
                    )
                    for event in events
                ],
                "completion": _history_completion_summary(completion),
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


RECENT_ENTRY_DISPLAY_GROUPS = 2


def _ordered_subset_positions(available: list[int], requested: list[int]) -> list[int] | None:
    """返回保序子集在父集合中的 1-based 位置；重复、越界或重排均拒绝。"""

    if not requested or len(set(requested)) != len(requested):
        return None
    positions = []
    cursor = 0
    for entry_id in requested:
        try:
            index = available.index(entry_id, cursor)
        except ValueError:
            return None
        positions.append(index + 1)
        cursor = index + 1
    return positions


def _authorized_list_for_entry_ids(
    state: LoopState, entry_ids: list[int]
) -> tuple[str, ResultRecord] | None:
    """定位包含读取目标保序子集的最近授权展示集合。"""

    delivered_handles = recent_entry_reference_handles(state)
    eligible_handles = state.current_handles | delivered_handles
    for handle, record in reversed(list(state.result_sets.items())):
        if (
            handle not in eligible_handles
            or record.kind != "list"
            or not record.displayable
            or record.semantics.get("result_role", "authorized") == "candidate"
        ):
            continue
        available = [
            int(item["entry_id"])
            for item in record.payload.get("items", [])
            if item.get("entry_id") is not None
        ]
        if _ordered_subset_positions(available, entry_ids) is not None:
            return handle, record
    return None


def _entry_display_group(record: ResultRecord) -> str | None:
    """返回 Entry 结果所属的用户可见展示组，列表发现与正文读取仍保持区别。"""

    if (
        record.kind == "list"
        and record.displayable
        and record.semantics.get("result_role", "authorized") != "candidate"
        and any(item.get("entry_id") is not None for item in record.payload.get("items", []))
    ):
        return record.handle
    if record.kind == "entries" and record.displayable:
        parent = record.semantics.get("display_parent_handle")
        return str(parent) if parent else record.handle
    return None


def recent_entry_reference_handles(state: LoopState) -> set[str]:
    """按最终回答实际引用保留最近两组 Entry 材料。"""

    groups: dict[str, dict] = {}
    for turn in state.history_turns:
        turn_index = int(turn.get("turn") or 0)
        references = (turn.get("answer_summary") or {}).get("references") or []
        for reference in references:
            handle = reference.get("handle")
            record = state.result_sets.get(str(handle)) if handle else None
            if record is None:
                continue
            group = _entry_display_group(record)
            if group is None:
                continue
            value = groups.setdefault(
                group,
                {"turn_index": 0, "handles": set(), "handle_turns": {}},
            )
            value["turn_index"] = max(value["turn_index"], turn_index)
            value["handles"].add(record.handle)
            value["handle_turns"][record.handle] = max(
                turn_index,
                value["handle_turns"].get(record.handle, 0),
            )
            if group in state.result_sets:
                value["handles"].add(group)
    selected = sorted(
        groups.items(),
        key=lambda item: (item[1]["turn_index"], item[0]),
        reverse=True,
    )[:RECENT_ENTRY_DISPLAY_GROUPS]
    retained: set[str] = set()
    for group, value in selected:
        if group in state.result_sets:
            retained.add(group)
        latest_material: dict[str, tuple[int, str]] = {}
        for handle in value["handles"]:
            record = state.result_sets.get(handle)
            if record is None or record.kind != "entries":
                continue
            material = []
            deduplicable = bool(record.payload.get("items"))
            refs_by_entry = record.semantics.get("entry_validation_refs") or {}
            for item in record.payload.get("items", []):
                entry_id = str(item.get("entry_id"))
                refs = refs_by_entry.get(entry_id) or {}
                fingerprints = refs.get("fingerprints") or {}
                if not fingerprints:
                    deduplicable = False
                material.append(
                    {
                        "entry_id": entry_id,
                        "fingerprints": fingerprints,
                    }
                )
            key = (
                json.dumps(material, ensure_ascii=False, sort_keys=True)
                if deduplicable
                else f"handle:{handle}"
            )
            candidate = (int(value["handle_turns"].get(handle, 0)), handle)
            if candidate > latest_material.get(key, (-1, "")):
                latest_material[key] = candidate
        retained.update(handle for _, handle in latest_material.values())
    return retained


def _recent_displayed_entry_groups(state: LoopState) -> list[dict]:
    """给模型提供与用户实际展示顺序一致的、仅含已读取正文的对象提示。"""

    recent_handles = recent_entry_reference_handles(state) | state.current_handles
    groups: dict[str, dict] = {}
    for handle in recent_handles:
        record = state.result_sets[handle]
        if record.kind != "entries":
            continue
        parent_handle = str(record.semantics.get("display_parent_handle") or handle)
        parent = state.result_sets.get(parent_handle)
        parent_items = parent.payload.get("items", []) if parent is not None else []
        positions = record.semantics.get("display_positions") or {}
        group = groups.setdefault(
            parent_handle,
            {
                "result_set_handle": parent_handle,
                "turn_index": record.turn_index,
                "items": {},
            },
        )
        group["turn_index"] = max(group["turn_index"], record.turn_index)
        for fallback_position, entry in enumerate(record.payload.get("items", []), start=1):
            entry_id = entry.get("entry_id")
            if entry_id is None:
                continue
            position = positions.get(str(entry_id), fallback_position)
            title = entry.get("title")
            if parent_items and 1 <= int(position) <= len(parent_items):
                title = parent_items[int(position) - 1].get("title") or title
            group["items"][int(position)] = {
                "position": int(position),
                "entry_id": int(entry_id),
                "title": title,
            }
    return [
        {
            "result_set_handle": value["result_set_handle"],
            "items": [value["items"][position] for position in sorted(value["items"])],
        }
        for value in sorted(
            groups.values(),
            key=lambda item: (item["turn_index"], item["result_set_handle"]),
            reverse=True,
        )
    ]


async def _bind_entry_result_material(
    state: LoopState,
    record: ResultRecord,
    items: list[dict],
    *,
    parent_handle: str | None,
) -> None:
    """为两种正文读取结果统一附加身份、校验引用与父展示位置。"""

    if not items:
        return
    parent = state.result_sets.get(parent_handle) if parent_handle else None
    available = [
        int(item["entry_id"])
        for item in (parent.payload.get("items", []) if parent is not None else [])
        if item.get("entry_id") is not None
    ]
    entry_ids = [int(item["entry_id"]) for item in items]
    positions = _ordered_subset_positions(available, entry_ids) if available else None
    all_pairs = [
        (int(item["entry_id"]), int(source["source_id"]))
        for item in items
        for source in item.get("sources", [])
        if source.get("source_id") is not None
    ]
    all_refs = await _database_material_refs(state, entry_ids, all_pairs)
    per_entry_refs = {}
    for item in items:
        entry_id = int(item["entry_id"])
        pairs = [pair for pair in all_pairs if pair[0] == entry_id]
        source_ids = sorted({source_id for _, source_id in pairs})
        per_entry_refs[str(entry_id)] = {
            "workspace_id": state.workspace_id,
            "user_id": state.user_id,
            "entry_ids": [entry_id],
            "source_ids": source_ids,
            "source_pairs": [list(pair) for pair in pairs],
            "fingerprints": {
                key: value
                for key, value in all_refs["fingerprints"].items()
                if key == f"entry:{entry_id}" or key.startswith(f"evidence:{entry_id}:")
            },
        }
    record.semantics["entry_validation_refs"] = per_entry_refs
    if parent_handle is not None and positions is not None:
        record.semantics["display_parent_handle"] = parent_handle
        record.semantics["display_positions"] = {
            str(entry_id): position
            for entry_id, position in zip(entry_ids, positions, strict=True)
        }


def _displayed_entry_material(
    state: LoopState, result_set_handle: str, position: int
) -> tuple[dict, dict]:
    """从正文结果或其父展示集合解析唯一、已读取的 Entry 材料。"""

    allowed_handles = state.current_handles | recent_entry_reference_handles(state)
    record = state.result_sets.get(result_set_handle)
    if (
        record is None
        or result_set_handle not in allowed_handles
        or not record.displayable
        or record.status not in {"completed", "partial"}
    ):
        raise ValueError("只能从最近已展示的 Entry 正文结果中按有效序号选择对象")
    if record.kind == "entries":
        items = record.payload.get("items", [])
        if not 1 <= position <= len(items):
            raise ValueError("只能从最近已展示的 Entry 正文结果中按有效序号选择对象")
        entry = items[position - 1]
        refs = (record.semantics.get("entry_validation_refs") or {}).get(
            str(entry.get("entry_id"))
        )
        if not isinstance(refs, dict):
            raise ValueError("已展示对象缺少可复验的材料指纹，请重新读取核验")
        return entry, refs
    if record.kind != "list":
        raise ValueError("只能从最近已展示的 Entry 正文结果中按有效序号选择对象")
    items = record.payload.get("items", [])
    if not 1 <= position <= len(items):
        raise ValueError("只能从最近已展示的 Entry 正文结果中按有效序号选择对象")
    entry_id = int(items[position - 1]["entry_id"])
    matches = []
    for handle in allowed_handles:
        child = state.result_sets.get(handle)
        if child is None or child.kind != "entries" or not child.displayable:
            continue
        if child.semantics.get("display_parent_handle") != result_set_handle:
            continue
        if (child.semantics.get("display_positions") or {}).get(str(entry_id)) != position:
            continue
        entry = next(
            (
                item
                for item in child.payload.get("items", [])
                if int(item.get("entry_id", -1)) == entry_id
            ),
            None,
        )
        refs = (child.semantics.get("entry_validation_refs") or {}).get(str(entry_id))
        if entry is not None and isinstance(refs, dict):
            matches.append((child.turn_index, child.handle, entry, refs))
    if not matches:
        raise ValueError("该列表项只完成展示，尚未读取正文材料")
    _, _, entry, refs = max(matches, key=lambda item: (item[0], item[1]))
    return entry, refs


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
            status=(
                TURN_PARTIAL_COMPLETED
                if continuation is not None
                or _reliable_current_records(state)
                or state.current_evidence
                else TURN_NOT_EXECUTED
            ),
            reason_code=_budget_stop_reason(exc),
            reason=reason,
            incomplete_steps=[
                f"未执行：{tool_name}" if tool_name else "未完成剩余查询或读取步骤"
            ],
            can_continue=True,
            continuation=continuation,
        )
    )


def _effective_denied_events(events: list[dict]) -> list[dict]:
    """完整成功的同组读取只消解早先的临时拒绝，不删除审计。"""

    effective: list[dict] = []
    for index, event in enumerate(events):
        if event.get("status") != "denied":
            continue
        tool_name = event.get("shared_tool") or event.get("tool")
        params = event.get("shared_params") or event.get("params") or {}
        entry_ids = params.get("entry_ids") if isinstance(params, dict) else None
        if tool_name != "read_entries" or not isinstance(entry_ids, list):
            effective.append(event)
            continue
        normalized = list(dict.fromkeys(entry_ids))
        superseded = False
        for later in events[index + 1 :]:
            later_params = later.get("shared_params") or later.get("params") or {}
            later_ids = (
                later_params.get("entry_ids")
                if isinstance(later_params, dict)
                else None
            )
            if (
                (later.get("shared_tool") or later.get("tool")) == "read_entries"
                and later.get("status") in {"completed", "ok"}
                and isinstance(later_ids, list)
                and list(dict.fromkeys(later_ids)) == normalized
                and (later.get("result_summary") or {}).get("returned_count")
                == len(normalized)
            ):
                superseded = True
                break
        if not superseded:
            effective.append(event)
    return effective


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
    denied_events = _effective_denied_events(events)
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
    denied_events = _effective_denied_events(events)
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
    if _pending_semantic_candidates(state):
        return _pending_semantic_stop()
    incomplete = []
    for event in events:
        status = event.get("status")
        if status in {"partial", "error", "unavailable"}:
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


def _shorten_middle(text: str, limit: int) -> str:
    """同时保留结论开头和后续建议或候选边界结尾。"""

    if len(text) <= limit:
        return text
    marker = f"\n[历史回答已缩减；省略 {len(text) - limit} 字符]\n"
    remaining = max(limit - len(marker), 2)
    head = remaining * 2 // 3
    return f"{text[:head]}{marker}{text[-(remaining - head):]}"


def _bounded_history_value(value, *, string_limit: int = 400):
    """限制工具条件和错误文本，不改变对象 ID、顺序或统计数值。"""

    if isinstance(value, str):
        return _shorten_middle(value, string_limit)
    if isinstance(value, list):
        return [_bounded_history_value(item, string_limit=string_limit) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _bounded_history_value(item, string_limit=string_limit)
            for key, item in value.items()
        }
    return value


def _history_answer_summary(blocks: list[dict] | None, answer: str) -> dict:
    """从回答块提取历史语义，明确排除渲染后的正文与 Evidence 原文。"""

    if blocks is None:
        return {
            "narrative": _shorten_middle(answer, HISTORY_ANSWER_CHARS_PER_TURN),
            "references": [],
        }
    narrative = "\n".join(
        str(block.get("text", ""))
        for block in blocks
        if block.get("kind") in {"text", "insufficient"} and block.get("text")
    )
    references: list[dict] = []
    for block in blocks:
        kind = block.get("kind")
        if kind == "entry":
            references.append(
                {
                    "kind": kind,
                    "handle": block.get("handle"),
                    "position": block.get("position"),
                    "entry_id": block.get("entry_id"),
                    "title": block.get("title"),
                    "status": block.get("status"),
                }
            )
        elif kind == "evidence":
            references.append(
                {
                    "kind": kind,
                    "handle": block.get("handle"),
                    "entry_id": block.get("entry_id"),
                    "source_id": block.get("source_id"),
                }
            )
        elif kind in {"list", "statistic"}:
            references.append(
                {
                    "kind": kind,
                    "handle": block.get("handle"),
                    "status": block.get("status"),
                    "completeness": block.get("completeness"),
                }
            )
    return {
        "narrative": _shorten_middle(narrative, HISTORY_ANSWER_CHARS_PER_TURN),
        "references": references,
    }


def _history_completion_summary(completion: dict | None) -> dict | None:
    if not completion:
        return None
    return {
        "status": completion.get("status"),
        "reason_code": completion.get("reason_code"),
        "reason": _shorten_middle(str(completion.get("reason") or ""), 300),
        "incomplete_steps": [
            _shorten_middle(str(item), 200)
            for item in completion.get("incomplete_steps", [])[:8]
        ],
        "can_continue": bool(completion.get("can_continue")),
    }


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
                if key not in {
                    "items",
                    "internal_classifications",
                    "internal_classified_items",
                }
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


def _history_tool_summary(
    state: LoopState,
    event: dict,
    *,
    delivered_handles: set[str] | None = None,
) -> dict:
    summary = {
        "tool": event.get("tool"),
        "shared_tool": event.get("shared_tool"),
        "conditions": _bounded_history_value(event.get("params", {})),
        "executed_conditions": _bounded_history_value(
            event.get("shared_params", event.get("params", {}))
        ),
        "status": event.get("status"),
        "completeness": event.get("completeness", "unknown"),
        "result_handle": event.get("result_handle"),
        "error": _shorten_middle(str(event.get("error") or ""), 300),
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
        if record.displayable and (
            delivered_handles is None or record.handle in delivered_handles
        ):
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
    elif record.kind == "project_context":
        summary["project_name"] = payload.get("project_name")
        summary["project_id"] = payload.get("project_id")
    elif record.kind == "projects":
        summary["projects"] = payload.get("projects", [])
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


def _recent_history_messages(turns: list[dict]) -> list[ModelMessage]:
    """近期叙述可裁剪，失败文案不重新进入上下文。"""
    messages = []
    for turn in turns[-6:]:
        summary = turn.get("answer_summary") or {}
        completion = turn.get("completion") or {}
        content = {
            "历史用户原话": turn["user"],
            "历史回答（非事实依据）": (
                summary.get("narrative", "")
                if completion.get("status", "completed") == "completed" else ""
            ),
            "状态": completion.get("status"),
        }
        messages.append(ModelResponse(
            parts=[TextPart(content=json.dumps(content, ensure_ascii=False),
                            provider_name="grove-history",
                            provider_details={"optional_history": True})],
            metadata={"grove_optional_history": True, "turn": turn.get("turn")},
        ))
    return messages


def _trim_optional_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """先满足历史目标；完整请求还会按指令与工具定义再预留空间。"""
    while estimate_input_tokens(messages) > HISTORY_INPUT_TOKENS_TARGET:
        removable = next((i for i, m in enumerate(messages)
                          if (m.metadata or {}).get("grove_optional_history")), None)
        if removable is None:
            break
        messages.pop(removable)
    return messages


def build_compact_history(state: LoopState) -> list[ModelMessage]:
    """完整记录留在 state；模型只接收可裁剪近期叙述和必要对象摘要。"""
    turns = state.history_turns
    messages = []
    # 历史工具轨迹不重放；最近展示的有序集合另存为受保护的指代线索。
    latest_results = []
    for turn in reversed(turns):
        latest_results = [
            tool for tool in turn.get("tools", [])
            if tool.get("ordered_items") or tool.get("directory_items")
            or tool.get("projects") or tool.get("statistics")
        ]
        if latest_results:
            break
    if latest_results:
        latest_results = [{key: tool[key] for key in (
            "result_handle", "ordered_items", "directory_items", "projects",
            "directory_total_count", "directory_returned_count", "directory_has_more",
        ) if key in tool} for tool in latest_results if
            tool.get("ordered_items") or tool.get("directory_items") or tool.get("projects")]
        messages.append(ModelResponse(parts=[TextPart(content=json.dumps(
            {"最近展示结果（仅指代线索，引用须本轮复验）": latest_results},
            ensure_ascii=False, separators=(",", ":"),
        ))]))
    messages.extend(_recent_history_messages(turns))
    return _trim_optional_history(messages)


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


def resolve_answer_results(answer: DialogueAnswer, state: LoopState) -> DialogueAnswer:
    """只映射已授权结果的展示形态，不猜句柄、不将结果变成 Evidence。"""
    blocks = []
    for block in answer.blocks:
        if block.kind not in {"result", "list", "statistic"}:
            blocks.append(block.model_dump(mode="json"))
            continue
        record = state.result_sets.get(block.result_handle)
        if (
            record is None or record.handle not in state.current_handles
            or not record.displayable
            or record.status not in {"completed", "ok", "empty", "partial", "limited"}
        ):
            blocks.append(block.model_dump(mode="json"))
            continue
        if record.kind == "project_context":
            from evals.dialogue_loop.project_material import project_material_text

            blocks.append({"kind": "text", "text": project_material_text(record.payload)})
        elif record.kind in {"list", "directories", "projects", "statistic", "entries"}:
            blocks.append({
                "kind": "statistic" if record.kind == "statistic" else "list",
                "result_handle": record.handle, "label": "已确认结果",
            })
        else:
            blocks.append(block.model_dump(mode="json"))
    return DialogueAnswer.model_validate({
        "blocks": blocks or [{"kind": "insufficient", "text": "结果没有可展示正文"}],
        "needs_clarification": answer.needs_clarification,
        "discussion_entry_id": answer.discussion_entry_id,
    })


_WRITE_ACTION_PATTERN = r"(?:写入|保存|更新|修改|改动|覆盖)"
_WRITE_CLAIM_PATTERN = (
    rf"已(?:经)?{_WRITE_ACTION_PATTERN}|(?:写入|保存|更新|修改|覆盖)(?:好了|完成)"
)
_WRITE_CLAIM_RE = re.compile(_WRITE_CLAIM_PATTERN)
_CONFIRMED_STATUS_PATTERN = r"已(?:经)?(?:过)?(?:官方)?(?:确认|核验|验证)"
_STATUS_PATTERN = rf"(?:{_WRITE_CLAIM_PATTERN}|{_CONFIRMED_STATUS_PATTERN})"
_NEGATION_PATTERN = r"(?:不代表|不意味着|不等于|不是|并非|没有|不会|尚未|并未|未)"
_NEGATED_STATUS_SUBJECT_PATTERN = (
    r"(?:(?:它|这|该)(?:条|份|个)?(?:候选|内容|记录|版本|稿件)?[ \t]*)?"
)
_NEGATED_STATUS_RE = re.compile(
    rf"(?P<negations>(?:{_NEGATION_PATTERN}[ \t]*)+)"
    rf"{_NEGATED_STATUS_SUBJECT_PATTERN}"
    rf"{_STATUS_PATTERN}(?:[ \t]*(?:或者|以及|或|和|及|、)[ \t]*{_STATUS_PATTERN})*"
)
_DIRECT_WRITE_NEGATION_PATTERN = r"(?:并没有|没有|不会|尚未|并未|从未|未曾|不曾|未|不)"
_NEGATED_WRITE_RE = re.compile(
    rf"(?P<negations>(?:{_DIRECT_WRITE_NEGATION_PATTERN}[ \t]*)+)"
    rf"(?:实际|直接|擅自|主动|自动|替你|为你|已经|已)*[ \t]*{_WRITE_ACTION_PATTERN}"
)
_PROGRAM_UNWRITTEN_NOTE = "（以上为候选内容，尚未写入正式 Entry。）"
_PROGRAM_SOURCE_NOTE = "（模型补充属于候选判断，不代表 Source 原文。）"
_LEGACY_PROGRAM_SOURCE_NOTE = "（模型补充不属于 Source 原文。）"
_SOURCE_REFERENCE_RE = re.compile(r"(?:Source\s*原文|来源\s*原文)", re.IGNORECASE)
_POSITIVE_SOURCE_CLAIM_RE = re.compile(
    r"(?:模型(?:判断|分析|补充|建议)|新增(?:内容|判断|建议)|候选(?:判断|内容))"
    r"[^。！？；;\n]{0,24}"
    r"(?<!不)(?<!未)(?<!非)(?:来自|源自|属于|就是|等同于|依据于?)\s*"
    r"(?:Source|来源|原文)",
    re.IGNORECASE,
)


def _single_negation(match: re.Match, pattern: str = _NEGATION_PATTERN) -> bool:
    """嵌套否定不能被当作安全边界。"""
    return len(re.findall(pattern, match.group("negations"))) == 1


def _has_unwritten_boundary(text: str) -> bool:
    """识别模型已有的否定写入声明；漏识别时由程序补齐固定声明。"""
    return any(_single_negation(match) for match in _NEGATED_STATUS_RE.finditer(text)) or any(
        _single_negation(match, _DIRECT_WRITE_NEGATION_PATTERN)
        for match in _NEGATED_WRITE_RE.finditer(text)
    )


def _has_positive_write_claim(text: str) -> bool:
    """逐处校验完成声明，只豁免明确否定直接支配的紧邻并列状态。"""
    negated_spans = [
        match.span()
        for match in _NEGATED_STATUS_RE.finditer(text)
        # 嵌套否定不能按一次否定放行；不跨越正文、转折、换行或新主语。
        if _single_negation(match)
    ]
    return any(
        not any(start <= claim.start() and claim.end() <= end for start, end in negated_spans)
        for claim in _WRITE_CLAIM_RE.finditer(text)
    )


def _has_positive_source_claim(text: str) -> bool:
    """只拦截正文把模型判断直接归属于 Source 的明确正向陈述。"""

    return _POSITIVE_SOURCE_CLAIM_RE.search(text) is not None


def _has_source_reference(text: str) -> bool:
    """判断正文是否已经明确谈及 Source/来源原文，仅用于避免重复尾注。"""

    return _SOURCE_REFERENCE_RE.search(text) is not None


_LENGTH_MEASUREMENT_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|毫米|厘米|公分|米)",
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>kwh|kw|mah|mm|cm|db|a|v|w|h|m|%|"
    r"千瓦时|千瓦|毫安时|毫米|厘米|公分|分贝|安培|伏特|瓦|小时|米)",
    re.IGNORECASE,
)
_LENGTH_UNIT_ALIASES = {
    "mm": "mm",
    "毫米": "mm",
    "cm": "cm",
    "厘米": "cm",
    "公分": "cm",
    "m": "m",
    "米": "m",
}
_DIMENSION_TERMS = {
    "space": ("空间", "间隙", "余量", "空位"),
    "height": ("高度", "净高", "高出", "抬高", "增高"),
    "width": ("宽度", "净宽"),
    "depth": ("深度", "埋深"),
    "length": ("长度", "总长"),
    "distance": ("距离", "间距"),
    "thickness": ("厚度", "壁厚"),
    "diameter": ("直径", "管径", "口径"),
}
_UNCERTAINTY_GROUPS = (
    ("建议", "可以", "可考虑", "最好", "宜", "不妨"),
    ("大约", "约", "左右", "上下", "差不多"),
    ("可能", "也许", "或许", "通常", "一般", "不一定"),
    ("具体以", "为准", "取决于", "视情况", "视现场", "具体还得看", "看现场"),
)
_CERTAINTY_STRENGTHENERS = ("必须", "一定", "肯定", "绝对", "务必")
_QUANTITY_UNIT_ALIASES = {
    **_LENGTH_UNIT_ALIASES,
    "kwh": "kwh",
    "千瓦时": "kwh",
    "kw": "kw",
    "千瓦": "kw",
    "mah": "mah",
    "毫安时": "mah",
    "db": "db",
    "分贝": "db",
    "a": "a",
    "安培": "a",
    "v": "v",
    "伏特": "v",
    "w": "w",
    "瓦": "w",
    "h": "h",
    "小时": "h",
    "%": "%",
}
_ADJACENT_DIMENSIONS = {
    "height": ("高", "高出", "抬高", "增高"),
    "width": ("宽",),
    "depth": ("深",),
    "length": ("长",),
    "distance": ("距",),
    "thickness": ("厚",),
}


def _quantity_claims(text: str) -> Counter[tuple[str, str]]:
    """对只改语气的文本保留所有带单位数量及出现次数。"""

    claims: Counter[tuple[str, str]] = Counter()
    for match in _QUANTITY_RE.finditer(text):
        number = format(Decimal(match.group("number")).normalize(), "f")
        unit = _QUANTITY_UNIT_ALIASES[match.group("unit").casefold()]
        claims[(number, unit)] += 1
    return claims


def _measurement_dimensions(text: str) -> dict[tuple[str, str], Counter[str]]:
    """提取长度数量所修饰的通用尺寸维度。"""

    dimensions: dict[tuple[str, str], Counter[str]] = {}
    for match in _LENGTH_MEASUREMENT_RE.finditer(text):
        number = format(Decimal(match.group("number")).normalize(), "f")
        unit = _LENGTH_UNIT_ALIASES[match.group("unit").casefold()]
        clause_start = max(
            text.rfind(mark, 0, match.start()) for mark in "。！？；;\n"
        ) + 1
        following = [
            position
            for mark in "。！？；;\n"
            if (position := text.find(mark, match.end())) >= 0
        ]
        clause_end = min(following) if following else len(text)
        clause = text[clause_start:clause_end]
        found = {
            dimension
            for dimension, terms in _DIMENSION_TERMS.items()
            if any(term in clause for term in terms)
        } or {"unspecified"}
        relative_start = match.start() - clause_start
        relative_end = match.end() - clause_start
        before = clause[:relative_start].rstrip()
        after = clause[relative_end:].lstrip()
        for dimension, markers in _ADJACENT_DIMENSIONS.items():
            if any(before.endswith(marker) for marker in markers) or any(
                after.startswith(marker) for marker in markers
            ):
                found.discard("unspecified")
                found.add(dimension)
        dimensions.setdefault((number, unit), Counter()).update(found)
    return dimensions


def _candidate_semantic_errors(
    answer: DialogueAnswer, state: LoopState, candidate_message: str
) -> list[str]:
    """对仅改表达的候选执行有限、确定性事实保护。"""

    if (
        not _tone_only_candidate_requested(candidate_message)
        or state.editing_context is None
    ):
        return []
    baseline = state.editing_context.entry.get("content") or ""
    saved_draft = state.editing_context.draft
    if isinstance(saved_draft, dict):
        try:
            draft_answer = DialogueAnswer.model_validate(saved_draft)
        except (TypeError, ValueError):
            draft_answer = None
        if draft_answer is not None:
            draft_text = "\n".join(
                block.text
                for block in draft_answer.blocks
                if block.kind in {"text", "insufficient"}
            )
            if draft_text:
                baseline = draft_text
    original = str(baseline)
    candidate = "\n".join(
        block.text for block in answer.blocks if block.kind == "text"
    )
    errors: list[str] = []
    if _quantity_claims(original) != _quantity_claims(candidate):
        errors.append("只改语气必须保留原记录的数量事实及出现次数")
    original_dimensions = _measurement_dimensions(original)
    candidate_dimensions = _measurement_dimensions(candidate)
    for measurement, expected in original_dimensions.items():
        actual = candidate_dimensions.get(measurement)
        if actual != expected:
            number, unit = measurement
            errors.append(
                f"只改语气不能改变数量所属的尺寸含义：{number}{unit}"
            )
            break
    original_soft = [
        group for group in _UNCERTAINTY_GROUPS if any(term in original for term in group)
    ]
    missing_soft = any(
        not any(term in candidate for term in group) for group in original_soft
    )
    strengthened = (
        bool(original_soft)
        and not any(term in original for term in _CERTAINTY_STRENGTHENERS)
        and any(term in candidate for term in _CERTAINTY_STRENGTHENERS)
    )
    if missing_soft or strengthened:
        errors.append("只改语气必须保留原记录的程度或不确定性")
    return errors


async def _project_material_errors(state: LoopState, handles: set[str]) -> list[str]:
    """发送或恢复项目介绍前复验成员权限和已保存快照，不增加资料工具动作。"""
    from evals.dialogue_loop.project_material import read_project_material

    errors = []
    for handle in handles:
        record = state.result_sets.get(handle)
        if record is None or record.kind != "project_context":
            continue
        try:
            async with state.database_lock:
                current = await read_project_material(
                    state.workspace_id, state.user_id, record.payload["project_name"],
                )
            if current != record.payload:
                errors.append("项目背景或上下文已变化，需要重新读取")
        except ValueError:
            errors.append("项目介绍已失去访问权限或项目身份不再唯一")
    return errors


def _pending_semantic_stop() -> StopState:
    """搜索已执行不等于结果已授权；预算停止不能伪装成查无结果。"""
    return StopState(
        status=TURN_PARTIAL_COMPLETED, reason_code="relevance_selection_pending",
        reason="搜索已执行，但相关性确认尚未完成，不能判断这些候选是否回答当前问题",
        incomplete_steps=["搜索候选的相关性授权尚未完成"], can_continue=False,
    )


def _pending_semantic_candidates(state: LoopState) -> set[str]:
    """成功召回但尚未完成三分授权的当前轮候选。"""
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
    return candidate_handles - selected_candidates


def _capture_provisional_answer(answer: DialogueAnswer, state: LoopState) -> None:
    """只保存独立通过边界检查的普通文本，不接纳整份非法输出。"""

    if _candidate_request_message(state) is not None:
        return
    pending_handles = _pending_semantic_candidates(state)
    pending_titles = {
        str(item.get("title") or "").strip()
        for handle in pending_handles
        for item in state.result_sets[handle].payload.get("items", [])
    }
    general_markers = (
        "模型通用",
        "通用知识",
        "通用常识",
        "一般知识",
        "通用分析",
        "不是 Grove",
        "并非 Grove",
        "不代表 Grove",
        "不属于 Source",
    )
    safe_blocks = []
    for block in answer.blocks:
        if block.kind != "text":
            continue
        text = block.text.strip()
        if (
            not text
            or _entry_reference(text) is not None
            or _has_positive_write_claim(text)
            or any(title and title in text for title in pending_titles)
        ):
            continue
        if pending_handles and not any(marker in text for marker in general_markers):
            continue
        safe_blocks.append(block.model_dump(mode="json"))
    if safe_blocks:
        state.provisional_answer = DialogueAnswer.model_validate(
            {"blocks": safe_blocks}
        ).model_dump(mode="json")


def _provisional_answer(state: LoopState) -> DialogueAnswer | None:
    if not state.provisional_answer:
        return None
    try:
        return DialogueAnswer.model_validate(state.provisional_answer)
    except (TypeError, ValueError):
        return None


async def _create_relevance_continuation(
    state: LoopState,
    message: str,
    current_events: list[dict],
) -> ContinuationState:
    """保存已成功查询的内部候选，续接时只恢复三分筛选。"""

    handles = sorted(_pending_semantic_candidates(state))
    records = {
        handle: {
            "handle": record.handle,
            "kind": record.kind,
            "payload": record.payload,
            "status": record.status,
            "completeness": record.completeness,
            "turn_index": record.turn_index,
            "semantics": record.semantics,
            "displayable": record.displayable,
        }
        for handle in handles
        if (record := state.result_sets.get(handle)) is not None
    }
    if not records:
        raise ValueError("没有可恢复的语义候选")
    entry_ids = sorted(
        {
            int(item["entry_id"])
            for record in records.values()
            for item in record["payload"].get("items", [])
            if item.get("entry_id") is not None
        }
    )
    validation_refs = await _database_material_refs(state, entry_ids, [])
    material = {
        "mode": "relevance_selection",
        "records": records,
        "record_fingerprints": {
            handle: _material_fingerprint(record) for handle, record in records.items()
        },
        "events": [
            event
            for event in current_events
            if event.get("result_handle") in records
            and event.get("status") in {"completed", "ok", "limited", "empty"}
        ],
        "provisional_answer": state.provisional_answer,
    }
    return ContinuationState(
        task_type="relevance_selection",
        tool_name="select_relevant_entries",
        scope={
            "workspace_id": state.workspace_id,
            "user_id": state.user_id,
            "scope_type": state.scope_type,
            "project_id": state.project_id,
            "candidate_handles": handles,
        },
        completed_steps=[
            {"tool": event.get("tool"), "result_handle": event.get("result_handle")}
            for event in material["events"]
        ],
        pending_steps=[
            {"step": "select_relevant_entries", "candidate_result_handle": handle}
            for handle in handles
        ],
        confirmed=[{"entry_id": entry_id} for entry_id in entry_ids],
        stop_reason="relevance_selection_pending",
        original_question=message,
        recoverable_material=material,
        validation_refs=validation_refs,
    )


async def _attach_relevance_continuation(
    state: LoopState,
    message: str,
    current_events: list[dict],
) -> bool:
    try:
        continuation = await _create_relevance_continuation(
            state, message, current_events
        )
    except Exception as exc:  # noqa: BLE001
        state.instrumentation.finalize_failure = {
            "category": "continuation_material_invalid",
            "message": str(exc),
            "exception_chain": [],
            "validation": None,
            "public_response": None,
        }
        return False
    stop = _pending_semantic_stop()
    stop.can_continue = True
    stop.continuation = continuation
    state.stop_state = stop
    state.continuation = continuation
    return True


def output_errors(answer: DialogueAnswer, state: LoopState) -> list[str]:
    """返回句柄边界错误；供一次模型纠正与无模型反例测试共用。"""
    answer = resolve_answer_results(answer, state)
    errors = []
    if state.editing_active and any(
        block.kind not in {"text", "insufficient"}
        or (block.kind == "text" and _entry_reference(block.text) is not None)
        for block in answer.blocks
    ):
        errors.append("当前对象讨论或候选交付只能输出文本，不得扩展展示其他结果集合")
    if not state.tools_allowed and any(
        block.kind in {"result", "statistic", "list", "evidence"}
        or (block.kind == "text" and _entry_reference(block.text) is not None)
        for block in answer.blocks
    ):
        errors.append("本轮明确不使用知识库，回答不得引用 Grove 结果、Entry 或 Evidence")
    for block in answer.blocks:
        if block.kind in {"result", "statistic", "list"}:
            record = state.result_sets.get(block.result_handle)
            expected = block.kind
            if record is None or block.result_handle not in state.current_handles:
                errors.append(f"{block.result_handle} 不是当前轮结果")
            elif record.status not in {"completed", "ok", "empty", "partial", "limited"}:
                errors.append(f"{block.result_handle} 不是可用结果")
            elif block.kind == "result":
                errors.append(f"{block.result_handle} 不支持结果展示，不能替代 Evidence")
            elif not record.displayable:
                errors.append(f"{block.result_handle} 是内部候选，不能进入主答案")
            elif expected == "list" and record.kind not in {
                "list", "directories", "projects", "entries"
            }:
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
        elif block.kind == "evidence":
            if block.evidence_handle not in state.current_evidence:
                errors.append(f"{block.evidence_handle} 不是当前轮核验 Evidence")
                continue
            claim = state.instrumentation.legacy_reference_claims.get(
                block.evidence_handle
            )
            evidence = state.evidence.get(block.evidence_handle)
            if claim is not None and (
                evidence is None
                or evidence.get("entry_id") != claim["entry_id"]
                or evidence.get("source_id") != claim["source_id"]
            ):
                state.instrumentation.finalize_compatibility = None
                errors.append(
                    f"{block.evidence_handle} 的旧式引用声明与当前轮 Evidence 关系不一致"
                )
    answer_text = "\n".join(
        block.text
        for block in answer.blocks
        if block.kind in {"text", "insufficient"}
    )
    if _pending_semantic_candidates(state):
        if _ZERO_RESULT_CLAIM_RE.search(answer_text):
            errors.append("未筛选语义候选不能表达为零条、查无结果或不存在记录")
        if state.instrumentation.phase != "finalize":
            errors.append("语义候选必须先完整调用 select_relevant_entries 形成授权集合")
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
            (block.kind == "text" and _entry_reference(block.text))
            or (block.kind == "list"
                and (record := state.result_sets.get(block.result_handle)) is not None
                and record.kind == "entries" and record.handle in state.current_handles)
            for block in answer.blocks
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
        empty_direct_result = any(
            handle in state.current_handles
            and record.semantics.get("relevance_scope") == "direct"
            and not record.payload.get("items")
            for handle, record in state.result_sets.items()
        )
        if empty_direct_result and not any(
            block.kind == "insufficient" for block in answer.blocks
        ):
            errors.append("定义型问题没有直接相关正式记录时必须明确说明结果不足")
    candidate_message = _candidate_request_message(state)
    if candidate_message is not None:
        draft_text = "\n".join(
            block.text for block in answer.blocks if block.kind == "text"
        )
        candidate_body = draft_text.replace(_PROGRAM_UNWRITTEN_NOTE, "").replace(
            _PROGRAM_SOURCE_NOTE, ""
        )
        content_only = (state.editing_content_only
                        or _candidate_content_only_requested(candidate_message))
        has_unwritten_boundary = _has_unwritten_boundary(draft_text)
        has_write_claim = _has_positive_write_claim(draft_text)
        missing: list[str] = []
        if not has_unwritten_boundary:
            missing.append("未写入状态")
        if has_write_claim:
            errors.append("候选修改稿不得声称已经写入或修改正式记录")
        if _has_positive_source_claim(candidate_body):
            errors.append("候选正文不得把模型判断声称为 Source 或来源原文")
        if not content_only:
            original_terms = (
                "原记录",
                "现有记录",
                "已有记录",
                "原内容",
                "现有内容",
                "当前记录",
                "原文",
            )
            suggestion_terms = (
                "建议",
                "补充",
                "新增",
                "可以增加",
                "可考虑",
                "候选",
                "修改后",
            )
            if not any(term in candidate_body for term in original_terms):
                missing.append("原记录与现有内容")
            if not any(term in candidate_body for term in suggestion_terms):
                missing.append("新增建议")
        if content_only and (
            len(answer.blocks) != 1 or any(block.kind != "text" for block in answer.blocks)
        ):
            missing.append("精简候选稿只能包含一个文本块")
        if missing:
            errors.append(f"候选修改稿缺少：{'、'.join(missing)}")
        errors.extend(_candidate_semantic_errors(answer, state, candidate_message))
    return errors


def _candidate_boundary(
    answer: DialogueAnswer, *, content_only: bool
) -> DialogueAnswer:
    """统一附加程序确定的未写入与来源边界；精简候选另收敛为单文本块。"""
    if not all(block.kind == "text" and _entry_reference(block.text) is None
               for block in answer.blocks):
        return answer
    if not answer.blocks:
        return answer
    if not content_only:
        payload = answer.model_dump(mode="json")
        text = "\n".join(block.text for block in answer.blocks)
        suffixes = []
        if not _has_unwritten_boundary(text):
            suffixes.append(_PROGRAM_UNWRITTEN_NOTE)
        if not _has_source_reference(text):
            suffixes.append(_PROGRAM_SOURCE_NOTE)
        if suffixes:
            payload["blocks"][-1]["text"] = (
                payload["blocks"][-1]["text"].rstrip() + "\n" + "\n".join(suffixes)
            )
        return DialogueAnswer.model_validate(payload)

    text = "\n".join(block.text for block in answer.blocks)
    if text.rstrip().endswith(_LEGACY_PROGRAM_SOURCE_NOTE):
        prefix = text.rstrip()[: -len(_LEGACY_PROGRAM_SOURCE_NOTE)].rstrip()
        if _has_source_reference(prefix):
            text = prefix
    if not _has_unwritten_boundary(text):
        text += "\n" + _PROGRAM_UNWRITTEN_NOTE
    if not _has_source_reference(text):
        text += "\n" + _PROGRAM_SOURCE_NOTE
    return DialogueAnswer.model_validate({
        "blocks": [{"kind": "text", "text": text}],
        "needs_clarification": answer.needs_clarification,
    })


def _safe_candidate_recovery(answer: DialogueAnswer) -> bool:
    """失败后仅允许普通候选文本进入下一轮恢复材料。"""

    if not answer.blocks:
        return False
    text = "\n".join(
        block.text for block in answer.blocks if block.kind in {"text", "insufficient"}
    )
    return (
        all(
            block.kind in {"text", "insufficient"}
            and (block.kind != "text" or _entry_reference(block.text) is None)
            for block in answer.blocks
        )
        and not _has_positive_write_claim(text)
        and not _has_positive_source_claim(text)
    )


def _sync_candidate_recovery(
    state: LoopState,
    draft: dict | None,
    errors: list[str],
) -> None:
    """将安全候选与其缺口作为一组写入所有恢复消费者。"""

    state.candidate_draft = draft
    state.candidate_draft_errors = list(errors)
    if (
        draft is not None
        and state.editing_active
        and state.editing_purpose == "candidate"
        and state.editing_context is not None
    ):
        state.editing_context.draft = draft
    seen: set[int] = set()
    for continuation in (state.active_continuation, state.continuation):
        if (
            continuation is None
            or continuation.task_type != "candidate_draft"
            or id(continuation) in seen
        ):
            continue
        seen.add(id(continuation))
        continuation.recoverable_material["candidate_draft"] = draft
        continuation.recoverable_material["candidate_draft_errors"] = list(errors)


def _content_only_boundary(answer: DialogueAnswer) -> DialogueAnswer:
    """兼容既有精简候选调用点。"""
    return _candidate_boundary(answer, content_only=True)


def _candidate_finalizer_text_only(
    answer: DialogueAnswer, state: LoopState
) -> DialogueAnswer:
    """候选稿收尾只保留普通文本，多余资料块既不引用也不执行。"""

    candidate_message = _candidate_request_message(state)
    if candidate_message is None or state.instrumentation.phase != "finalize":
        return answer
    text_blocks = [
        block
        for block in answer.blocks
        if block.kind == "text" and _entry_reference(block.text) is None
    ]
    if not text_blocks:
        return answer
    content_only = (state.editing_content_only
                        or _candidate_content_only_requested(candidate_message))
    normalized_blocks = (
        [
            {
                "kind": "text",
                "text": "\n".join(block.text for block in text_blocks),
            }
        ]
        if content_only
        else [block.model_dump(mode="json") for block in text_blocks]
    )
    if len(normalized_blocks) == len(answer.blocks) and all(
        block.kind == "text" for block in answer.blocks
    ):
        return answer
    normalized = DialogueAnswer.model_validate(
        {
            "blocks": normalized_blocks,
            "needs_clarification": answer.needs_clarification,
        }
    )
    discarded = [
        block.kind
        for block in answer.blocks
        if block.kind != "text" or _entry_reference(block.text) is not None
    ]
    compatibility = {
        "kind": "candidate_text_only",
        "status": "normalized",
        "discarded_blocks": discarded,
        "preserved_text_blocks": len(normalized.blocks),
    }
    state.instrumentation.finalize_compatibility = compatibility
    if state.instrumentation.logs and state.instrumentation.logs[-1].finalize_only:
        state.instrumentation.logs[-1].response_compatibility = compatibility
    return normalized


def list_position_entry_id(state: LoopState, result_set_handle: str, position: int) -> int:
    """将会话内有序列表位置解析为真实 Entry id。"""
    record = state.result_sets.get(result_set_handle)
    items = record.payload.get("items", []) if record and record.kind == "list" else []
    allowed_handles = state.current_handles | recent_entry_reference_handles(state)
    if (
        record is None
        or result_set_handle not in allowed_handles
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


def _zero_count_proof(state: LoopState, query_params: dict) -> ResultRecord | None:
    """精确零值只证明当前轮同结构范围为空，不赋予任何额外读取权限。"""
    query_set = {**query_params["entry_set"], "semantic_query": None}
    query_set["main_types"] = sorted(query_set.get("main_types") or [])
    for event in reversed(state.tool_events):
        record = state.result_sets.get(event.get("result_handle"))
        params = event.get("shared_params") or {}
        if (
            event.get("turn_index") != state.turn_index
            or event.get("shared_tool") != "aggregate_entries"
            or params.get("operation") != "count" or params.get("group_by") is not None
            or record is None or record.handle not in state.current_handles
            or record.turn_index != state.turn_index or not record.displayable
            or record.kind != "statistic" or record.completeness != "complete"
            or record.status not in {"completed", "empty"}
            or type(record.payload.get("value")) is not int or record.payload["value"] != 0
            or record.payload.get("truncated") or record.payload.get("has_more")
        ):
            continue
        count_set = dict(params.get("entry_set") or {})
        count_set["main_types"] = sorted(count_set.get("main_types") or [])
        if count_set != query_set:
            continue
        if any(params.get(key) != query_params.get(key)
               for key in ("project_id", "node_id", "node_scope")):
            continue
        return record
    return None


async def _reuse_zero_count(state: LoopState, params: dict, audit_params: dict) -> dict | None:
    proof = _zero_count_proof(state, params) if state.tools_allowed else None
    if proof is None:
        return None
    # 缓存仅在当前轮复用；成员撤权仍须即时拒绝，不把旧结果当作新授权。
    await _database_material_refs(state, [], [])
    payload = {"items": [], "total_count": 0, "returned_count": 0, "has_more": False}
    semantics = {
        **_result_semantics("query_entries", params, payload),
        "completeness": "complete", "result_role": "authorized", "has_more": False,
        "zero_count_handle": proof.handle,
    }
    handle = state.store_result("list", payload, "empty", "complete", semantics=semantics)
    event = {
        "tool": "query_entries", "result_handle": handle, "status": "empty",
        "completeness": "complete", "params": audit_params,
        "reason_code": "zero_count_reused", "zero_count_handle": proof.handle,
        "error": None, "duration_ms": 0, "turn_index": state.turn_index,
        "result_summary": {"total_count": 0, "returned_items": 0},
    }
    state.tool_events.append(event)
    return {**event, "payload": payload, "result_role": "authorized",
            "note": "同范围完整精确总计为 0，列表结论已完成；未执行重复读取或语义搜索。"}


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
    if state.relevance_resume_only:
        raise ModelRetry(
            "续执行只允许完成 select_relevant_entries，禁止重复搜索或读取资料"
        )
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
        if state.cancel_check is not None:
            await state.cancel_check()

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
                scope_type=state.scope_type,
                project_id=state.project_id,
                project_name=state.project_name,
                discovered_entry_ids=state.discovered_entry_ids,
                discovered_entry_fingerprints=state.discovered_entry_fingerprints,
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
        reusable = (
            existing is not None
            and existing.handle in state.current_handles
            and existing.turn_index == state.turn_index
            and existing.status in {"completed", "empty", "limited"}
            and existing.semantics.get("search_key") == search_key
        )
        if reusable:
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
        if (
            record is not None
            and result.get("status") in {"completed", "empty", "limited"}
        ):
            state.semantic_search_results[search_key] = record.handle
        return result


async def select_editing_context(
    state: LoopState, action: Literal["edit", "resume", "suspend"], content_only: bool = False,
    purpose: Literal["discussion", "candidate"] | None = None,
    result_set_handle: str | None = None,
    position: int | None = None,
) -> dict:
    """由当前 Agent 表达语义选择，程序固定对象、复验权限并保存用户原始决定。"""
    if action == "suspend":
        state.editing_active = False
        state.editing_content_only = False
        state.candidate_draft = None
        state.candidate_draft_errors.clear()
        if state.continuation and state.continuation.task_type == "candidate_draft":
            state.continuation = None
            state.active_continuation = None
        return {"status": "completed", "editing": "suspended"}
    if not state.tools_allowed and purpose != "discussion":
        raise ModelRetry("本轮不使用知识库时，对象选择只能用于通用讨论")
    task = state.editing_context
    task_refs_verified = False
    if result_set_handle is not None or position is not None:
        if result_set_handle is None or position is None:
            raise ModelRetry("按已展示位置选择对象时必须同时提供结果句柄和序号")
        try:
            entry, saved_refs = _displayed_entry_material(
                state, result_set_handle, position
            )
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc
        try:
            entry_id = int(entry["entry_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelRetry("已展示对象缺少有效 Entry 身份") from exc
        if entry_id not in state.authorized_entry_ids or entry_id not in state.discovered_entry_ids:
            raise ModelRetry("已展示对象不在当前授权和发现集合")
        pairs = [
            (entry_id, int(source["source_id"]))
            for source in entry.get("sources", [])
            if source.get("source_id") is not None
        ]
        current_refs = await _database_material_refs(state, [entry_id], pairs)
        if saved_refs != current_refs:
            raise ModelRetry("已展示对象或来源材料发生变化，请重新读取核验")
        if task is not None and int(task.entry.get("entry_id", -1)) == entry_id:
            task.entry = entry
            task.validation_refs = current_refs
        else:
            task = EditingContext(entry=entry, validation_refs=current_refs)
        task_refs_verified = True
        state.focused_entry = entry
        state.focused_entry_refs = current_refs
    if action == "edit" and state.focused_entry is not None and (
        task is None or task.entry["entry_id"] != state.focused_entry["entry_id"]
    ):
        entry = state.focused_entry
        if entry["entry_id"] not in state.authorized_entry_ids:
            raise ModelRetry("编辑对象不在授权结果集合")
        pairs = [(entry["entry_id"], source["source_id"])
                 for source in entry.get("sources", []) if source.get("source_id")]
        refs = await _database_material_refs(state, [entry["entry_id"]], pairs)
        if state.focused_entry_refs is None or state.focused_entry_refs != refs:
            raise ModelRetry("已打开对象或来源发生变化，请重新打开核验")
        task = EditingContext(entry=entry, validation_refs=refs)
    if task is None:
        raise ModelRetry("没有已选编辑对象，请先用授权列表位置打开具体 Entry")
    if task.entry["entry_id"] not in state.authorized_entry_ids:
        raise ModelRetry("编辑对象已经不在授权集合")
    if not task_refs_verified:
        try:
            current = await _database_material_refs(
                state, task.validation_refs["entry_ids"],
                [tuple(pair) for pair in task.validation_refs["source_pairs"]],
            )
            if current != task.validation_refs:
                raise ValueError("编辑对象或来源材料已变化，需要重新打开核验")
        except Exception as exc:
            state.editing_active = False
            state.candidate_draft = None
            state.continuation = None
            state.active_continuation = None
            raise ModelRetry(str(exc)) from exc
    state.editing_context = task
    state.editing_active = True
    state.editing_purpose = purpose or (
        "candidate" if content_only or _candidate_revision_requested(state.current_message)
        else "discussion"
    )
    state.editing_content_only = content_only
    state.candidate_draft = task.draft if state.editing_purpose == "candidate" else None
    state.candidate_draft_errors.clear()
    state.continuation = None
    state.active_continuation = None
    if state.current_message not in task.decisions:
        task.decisions.append(state.current_message)
    handle = None
    if state.tools_allowed:
        handle = state.store_result("entries", {"items": [task.entry]}, "completed", "limited")
    return {"status": "completed", "result_handle": handle, "entry": task.entry,
            "candidate_draft": state.candidate_draft, "purpose": state.editing_purpose,
            "user_decisions": task.decisions, "content_only": content_only}


async def _persist_discussion_answer(state: LoopState, answer: DialogueAnswer) -> None:
    """保存 Agent 明确关联到已读 Entry 的成功分析，不根据用户措辞猜测对象。"""

    text = "\n".join(
        block.text for block in answer.blocks if block.kind in {"text", "insufficient"}
    ).strip()
    if not text:
        return
    target_id = answer.discussion_entry_id
    task = state.editing_context if state.editing_active else None
    if task is not None and state.editing_purpose == "discussion":
        task_id = int(task.entry["entry_id"])
        if target_id is not None and target_id != task_id:
            raise ModelRetry("讨论对象与已经复验的当前 Entry 不一致")
    elif target_id is not None:
        matches = []
        for handle in state.current_handles | recent_entry_reference_handles(state):
            record = state.result_sets[handle]
            if record.kind != "entries" or not record.displayable:
                continue
            for item in record.payload.get("items", []):
                if int(item.get("entry_id", -1)) != target_id:
                    continue
                refs = (record.semantics.get("entry_validation_refs") or {}).get(
                    str(target_id)
                )
                if isinstance(refs, dict):
                    matches.append((record.turn_index, record.handle, item, refs))
        if not matches:
            raise ModelRetry("讨论对象不是最近已展示且已读取的 Entry")
        _, _, entry, refs = max(matches, key=lambda item: (item[0], item[1]))
        if (
            target_id not in state.authorized_entry_ids
            or target_id not in state.discovered_entry_ids
        ):
            raise ModelRetry("讨论对象不在当前授权和发现集合")
        pairs = [
            (target_id, int(source["source_id"]))
            for source in entry.get("sources", [])
            if source.get("source_id") is not None
        ]
        current_refs = await _database_material_refs(state, [target_id], pairs)
        if refs != current_refs:
            raise ModelRetry("讨论对象或来源材料发生变化，请重新读取核验")
        if state.editing_context is not None and int(
            state.editing_context.entry.get("entry_id", -1)
        ) == target_id:
            task = state.editing_context
            task.entry = entry
            task.validation_refs = current_refs
        else:
            task = EditingContext(entry=entry, validation_refs=current_refs)
        state.editing_context = task
        state.focused_entry = entry
        state.focused_entry_refs = current_refs
    else:
        return
    if state.current_message not in task.decisions:
        task.decisions.append(state.current_message)
    task.discussion = text


def preserve_editing_draft(state: LoopState, answer: DialogueAnswer) -> None:
    """兼容实验台调用，并统一写入候选稿及其当前缺口。"""

    if (
        state.editing_active
        and state.editing_context is not None
        and _candidate_request_message(state) is not None
    ):
        _sync_candidate_recovery(
            state,
            answer.model_dump(mode="json"),
            list(state.candidate_draft_errors),
        )


def build_agent(model) -> Agent[LoopDeps, DialogueAnswer]:
    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        instructions=SYSTEM_PROMPT,
        retries=1,
        model_settings=_dialogue_model_settings(model),
        max_concurrency=MAX_TOOL_CONCURRENCY,
        tool_timeout=PER_TURN_SECONDS,
    )

    @agent.instructions
    def editing_context_instruction(ctx: RunContext[LoopDeps]) -> str:
        state = ctx.deps.state
        task = state.editing_context
        recent_entry_sets = _recent_displayed_entry_groups(state)
        available_indirect_sets = []
        for handle in recent_entry_reference_handles(state):
            record = state.result_sets.get(handle)
            counts = record.semantics.get("classification_counts", {}) if record else {}
            if (
                record is not None
                and record.kind == "list"
                and record.semantics.get("relevance_scope") == "direct"
                and int(counts.get("indirect", 0)) > 0
                and record.payload.get("internal_classified_items")
            ):
                available_indirect_sets.append(
                    {
                        "result_set_handle": handle,
                        "indirect_count": int(counts["indirect"]),
                    }
                )
        context = {
            "current_entry": {k: state.focused_entry.get(k) for k in ("entry_id", "title")}
            if state.focused_entry else None,
            "saved_draft_entry": {k: task.entry.get(k) for k in ("entry_id", "title")}
            if task else None,
            "has_saved_draft": bool(task and task.draft),
            "editing_active": state.editing_active,
            "recent_displayed_entries": recent_entry_sets,
            "available_indirect_sets": available_indirect_sets,
        }
        if state.editing_active and task is not None:
            context.update(candidate_draft=task.draft, user_decisions=task.decisions)
        no_knowledge_boundary = (
            "本轮明确不使用知识库：不得调用搜索、Entry/Source 读取或 Evidence；仅当用户按刚才"
            "展示内容进行通用讨论时，可用 editing_context 的 result_set_handle 与 position 选择"
            "对象并做权限和指纹安全复验，purpose 必须为 discussion。"
            if not state.tools_allowed
            else ""
        )
        return (
            "当前对象与最近查询结果是独立状态。围绕当前条目讨论补充时保持同一 Entry，"
            "不得自行扩大到整套知识。讨论补充点用 "
            "editing_context(action=edit, purpose=discussion)，"
            "生成或继续候选用 purpose=candidate；工具复验后由独立回答器直接回答，不继续资料循环。"
            "明确要求来源正文核验时先按既有工具取得 Evidence，不把普通讨论当成核验。"
            "明确返回已保存原稿用 resume；新轮查询新主题不激活旧对象，不套旧候选约束。"
            "用户只要精简正文时设置 content_only=true。选择动作由你理解用户语义，"
            "不得根据历史错误推断用户同意扩大范围。保存的旧材料只是线索，工具复验后才能使用。"
            "如果不调用 editing_context 而直接完成某个已读 Entry 的分析，必须在 final_result 填写"
            "该对象的 discussion_entry_id；独立问题或对象不明确时保持 null。"
            "只有用户明确要求查看刚才已分类的间接相关记录时，才可对 available_indirect_sets 中"
            "的句柄调用 select_relevant_entries，设置 relevance_scope=indirect 且 "
            "classifications=[]；"
            "不得为此重新搜索，也不得在默认回答中展示或读取这些记录。"
            + no_knowledge_boundary
            + json.dumps(context, ensure_ascii=False)
        )

    @agent.tool
    async def editing_context(
        ctx: RunContext[LoopDeps], action: Literal["edit", "resume", "suspend"],
        content_only: bool = False,
        purpose: Literal["discussion", "candidate"] | None = None,
        result_set_handle: str | None = None,
        position: int | None = None,
    ) -> dict:
        """复验当前 Entry 后直接收尾：discussion 讨论补充点，candidate 生成候选，不写记录。"""
        state = ctx.deps.state
        if state.relevance_resume_only:
            raise ModelRetry("续执行只允许完成语义候选筛选，不能切换编辑对象")
        await state.ledger.reserve_tool()
        result = await select_editing_context(
            state, action, content_only, purpose, result_set_handle, position
        )
        state.tool_events.append({
            "tool": "editing_context", "status": "completed", "completeness": "limited",
            "result_handle": result.get("result_handle"), "turn_index": state.turn_index,
            "params": {"action": action, "purpose": state.editing_purpose,
                       "content_only": content_only}, "error": None, "duration_ms": 0,
        })
        if action != "suspend":
            state.instrumentation.begin_finalize("current_entry_ready")
            raise FinalizeRequired("current_entry_ready")
        return result

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
        state = ctx.deps.state
        if state.instrumentation.phase == "finalize":
            return ""
        resume_material = ""
        continuation = state.active_continuation
        if continuation is not None and continuation.task_type == "relevance_selection":
            candidates = {
                handle: record.payload.get("items", [])
                for handle, record in state.result_sets.items()
                if handle in state.current_handles
                and record.semantics.get("result_role") == "candidate"
            }
            resume_material = (
                "当前是已复验候选的续执行。候选材料如下；只调用 "
                "select_relevant_entries 完成每个句柄的全量三分，禁止搜索、读取或"
                "切换上下文："
                + json.dumps(candidates, ensure_ascii=False)
            )
        return (
            "语义候选先用 select_relevant_entries 全量三分；仅 direct 授权句柄可展示或读取，"
            "无 direct 不凑数。分类必须逐项阅读候选标题和正文：direct 只表示正文明确回答用户"
            "所问对象、动作或结果；只讨论相关材料、选材、等级、背景场景或可能影响因素的是"
            "indirect；只有弱语义相似且不能回答问题的是 unrelated。检索命中词、matched_fields、"
            "项目背景或共享主题词本身都不足以判定 direct。同义查询只用一个搜索入口，查询后再"
            "选择和读取。"
            "定义问题先答概念再列直接记录，并区分通用知识、正式记录与 Source。"
            + resume_material
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
    def model_only_discussion_instruction(ctx: RunContext[LoopDeps]) -> str:
        if ctx.deps.state.tools_allowed:
            return ""
        return (
            "用户明确要求本轮不使用知识库。不要调用搜索、目录、Entry 或 Evidence 工具；"
            "模型通用知识和带清晰边界的主观分析仍属于可用回答能力，不得仅因无法核验外部"
            "标准原文而调用 report_unsupported。请直接用 final_result 回答，并明确内容属于"
            "模型通用分析，不是 Grove 正式记录、Source 原文、实时外部资料或权威核验。"
            "只有任务确实依赖未提供的联网、外部原文读取、写入或其他未注册能力时，才报告不支持。"
        )

    @agent.instructions
    def candidate_revision_instruction(ctx: RunContext[LoopDeps]) -> str:
        if not _candidate_revision_requested(ctx.deps.state.current_message):
            return ""
        semantic_limit = (
            "用户只要求调整表达方式：必须保留原文的事实关系、"
            "数量所属的尺寸含义及建议、约数、可能性等限定；"
            "原文含糊时保留含糊，不得改成更窄或更确定的结论。"
            if _tone_only_candidate_requested(ctx.deps.state.current_message)
            else ""
        )
        if _candidate_content_only_requested(ctx.deps.state.current_message):
            return (
                "当前是候选稿的精简交付请求，不是写入正式记录。只调用 final_result 一次，"
                "且只输出一个 text 块：正文主体为补充后的候选知识内容，末尾用最短说明明确"
                "尚未写入知识库，并说明模型补充不属于 Source 原文。不要输出 Evidence、Entry、"
                "list、statistic、insufficient 或其他说明块，不要调用资料或写入工具。"
                + semantic_limit
            )
        return (
            "当前请求只要求生成候选修改稿，用户将自行审核或更新，不是写入正式记录。"
            "不要调用 report_unsupported 或任何写入工具；直接用 final_result 的 text 块输出，"
            "优先给出完整的修改后候选正文，明确尚未写入知识库；在正文中自然区分现有内容与"
            "新增建议，并简短说明来源边界，不强制固定章节，按用户需要解释修改理由。"
            "如果只是改写而没有新增事实，用一句自然说明即可。"
            + semantic_limit
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
        """目标确实依赖联网、写入或未注册只读能力时，记录能力不足并停止。"""

        if ctx.deps.state.relevance_resume_only:
            raise ModelRetry("续执行只允许完成语义候选筛选，不能改报能力不足")

        if _candidate_revision_requested(ctx.deps.state.current_message):
            raise ModelRetry(
                "当前用户只要求生成供审核的候选修改稿，不是写入请求。请不要调用 "
                "report_unsupported，改用 final_result 输出候选稿，并明确尚未写入知识库。"
            )
        if (
            not ctx.deps.state.tools_allowed
            and _unsupported_target_is_model_answerable(target, reason)
        ):
            raise ModelRetry(
                "用户明确要求不使用知识库，但通用知识和带边界的主观分析仍可直接回答。"
                "请不要调用 report_unsupported；改用 final_result，并明确这不是 Grove "
                "正式记录、外部实时资料或权威核验。"
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
        classifications: list[RelevanceDecision] | None = None,
        relevance_scope: Literal["direct", "indirect"] = "direct",
    ) -> dict:
        """筛选语义候选，或按明确请求激活同次筛选的 indirect 集合。

        必须覆盖候选中的每个 entry_id 且不得新增或重复。direct 要求候选正文明确回答
        用户所问的对象、动作或结果；只涉及相关材料、选材、等级、背景场景或可能影响
        因素的内容必须是 indirect；只有弱语义相似且不能回答问题的内容是 unrelated。
        检索命中词、matched_fields 或项目背景不能单独证明 direct。

        用户明确要求查看刚才的间接相关记录时，candidate_result_handle 传入已展示的 direct
        结果句柄，relevance_scope 设为 indirect 且 classifications 传空列表；工具复用原分类并
        重新复验权限、范围、对象和指纹，只返回标题列表，不读取给模型正文。
        """

        state = ctx.deps.state
        candidate_result_handle = _none_if_string_null(candidate_result_handle) or ""
        record = state.result_sets.get(candidate_result_handle)
        if relevance_scope == "indirect":
            if classifications:
                raise ModelRetry("激活已分类间接记录时 classifications 必须为空")
            if (
                record is None
                or candidate_result_handle not in recent_entry_reference_handles(state)
                or record.kind != "list"
                or not record.displayable
                or record.semantics.get("relevance_scope") != "direct"
            ):
                raise ModelRetry("只能从最近实际展示的 direct 结果激活间接相关记录")
            indirect_items = list(record.payload.get("internal_classified_items") or [])
            if not indirect_items:
                raise ModelRetry("该结果没有可复用的间接相关记录")
            try:
                await state.ledger.reserve_tool()
                entry_ids = [int(item["entry_id"]) for item in indirect_items]
                state.ledger.reserve_entries(entry_ids)
                verified = await _revalidate_discovered_entries(state, entry_ids)
            except BudgetExceeded as exc:
                _mark_budget_stop(
                    state,
                    exc,
                    tool_name="select_relevant_entries",
                    params={"candidate_result_handle": candidate_result_handle},
                )
                raise
            denied = verified.get("denied_entry_ids") or []
            unavailable = verified.get("unavailable_entry_ids") or []
            verified_ids = [int(item["entry_id"]) for item in verified.get("items", [])]
            if denied or unavailable or verified_ids != entry_ids:
                event = {
                    "tool": "select_relevant_entries",
                    "shared_tool": "select_relevant_entries",
                    "status": "denied" if denied else "unavailable",
                    "completeness": "unknown",
                    "params": {
                        "candidate_result_handle": candidate_result_handle,
                        "relevance_scope": "indirect",
                    },
                    "result_summary": {
                        "candidate_count": len(indirect_items),
                        "returned_count": 0,
                    },
                    "reason_code": "classified_results_invalid",
                    "error": "间接相关记录的权限、范围、对象或指纹已经变化",
                    "duration_ms": 0,
                    "turn_index": state.turn_index,
                }
                state.tool_events.append(event)
                return event
            payload = {
                **{
                    key: value
                    for key, value in record.payload.items()
                    if key not in {
                        "items",
                        "internal_classifications",
                        "internal_classified_items",
                        "returned_count",
                        "has_more",
                    }
                },
                "items": indirect_items,
                "returned_count": len(indirect_items),
                "has_more": False,
            }
            semantics = {
                **record.semantics,
                "relevance_scope": "indirect",
                "display_name": "间接相关正式记录",
                "source_result_handle": candidate_result_handle,
                "total_count": len(indirect_items),
                "returned_count": len(indirect_items),
                "has_more": False,
            }
            handle = state.store_result(
                "list",
                payload,
                "completed",
                record.completeness,
                semantics=semantics,
                displayable=True,
            )
            event = {
                "tool": "select_relevant_entries",
                "shared_tool": "select_relevant_entries",
                "result_handle": handle,
                "status": "completed",
                "completeness": record.completeness,
                "params": {
                    "candidate_result_handle": candidate_result_handle,
                    "relevance_scope": "indirect",
                },
                "result_summary": {
                    "candidate_count": len(indirect_items),
                    "returned_count": len(indirect_items),
                    "classification_counts": record.semantics.get(
                        "classification_counts", {}
                    ),
                    "has_more": False,
                },
                "reason_code": "indirect_results_authorized",
                "error": None,
                "duration_ms": 0,
                "turn_index": state.turn_index,
            }
            state.tool_events.append(event)
            return {
                **event,
                "result_role": "authorized",
                "relevance_scope": "indirect",
                "payload": _model_payload("list", payload),
            }
        if (
            record is None
            or candidate_result_handle not in state.current_handles
            or record.kind != "list"
            or record.semantics.get("result_role") != "candidate"
        ):
            raise ModelRetry("candidate_result_handle 不是当前可分类的语义候选")
        classifications = classifications or []
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
        indirect_items = [
            {**item, "relevance_level": "indirect"}
            for item in candidate_items
            if by_id[int(item["entry_id"])].relevance == "indirect"
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
            "internal_classified_items": indirect_items,
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
    async def read_project_context(ctx: RunContext[LoopDeps], project_name: str) -> dict:
        """介绍具体项目：只读背景目标、已保存上下文及用户纠正，不生成或刷新，不查记录。"""
        from app.db.session import async_session_factory
        from app.services.knowledge_agent.observability import next_tool_sequence, record_tool_call
        from evals.dialogue_loop.project_material import read_project_material

        state = ctx.deps.state
        if state.relevance_resume_only:
            raise ModelRetry("续执行只允许完成语义候选筛选，不能重复读取项目介绍")
        state.instrumentation.emit_activity("querying")
        try:
            await state.ledger.reserve_tool()
        except BudgetExceeded as exc:
            _mark_budget_stop(state, exc, tool_name="read_project_context",
                              params={"project_name": project_name})
            raise
        event = {"tool": "read_project_context", "params": {"project_name": project_name},
                 "turn_index": state.turn_index, "duration_ms": 0, "error": None}
        if not state.tools_allowed:
            event.update(status="not_executed", reason_code="tools_disallowed_by_user",
                         error="用户明确要求本轮不查知识库")
        else:
            try:
                async with state.database_lock:
                    payload = await read_project_material(
                        state.workspace_id, state.user_id, project_name,
                    )
            except ValueError as exc:
                event.update(status="denied", reason_code="project_context_unavailable",
                             error=str(exc))
            else:
                handle = state.store_result(
                    "project_context", payload, "completed", "complete",
                    semantics={"subject": "project_context", "project_name": project_name},
                )
                event.update(status="completed", completeness="complete", result_handle=handle)
        async with state.database_lock:
            async with async_session_factory() as db:
                await record_tool_call(
                    db, run_id=state.run_id, sequence=await next_tool_sequence(db, state.run_id),
                    tool_name="read_project_context", status=event["status"],
                    result_summary=("只读项目介绍" if event["status"] == "completed"
                                    else event["error"]),
                )
                await db.commit()
        state.tool_events.append(event)
        if event.get("result_handle"):
            return {**event, "payload": payload}
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
        if state.relevance_resume_only:
            raise ModelRetry("续执行只允许完成语义候选筛选，不能重复枚举项目")
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
            "projects", payload, "completed" if rows else "empty", "complete",
            semantics={"subject": "projects", "query_object": "项目", "completeness": "complete"},
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
        empty_result = await _reuse_zero_count(ctx.deps.state, params, audit_params)
        if empty_result is not None:
            return empty_result
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
                "read_entries 只能按同一授权展示集合的原相对顺序读取全部或保序子集；"
                "语义候选必须先调用 "
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
        returned_items = payload.get("items", [])
        result_record = state.result_sets.get(result.get("result_handle"))
        if (
            returned_items
            and result_record is not None
            and "completeness" in result_record.semantics
        ):
            await _bind_entry_result_material(
                state,
                result_record,
                returned_items,
                parent_handle=authorized[0],
            )
        unavailable_only = (
            result.get("status") == "unavailable"
            and payload.get("unavailable_entry_ids")
            and not payload.get("denied_entry_ids")
        )
        if (
            result.get("status") in {"partial", "error", "unavailable"}
            or unavailable_only
        ):
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
        if not _evidence_requested(ctx.deps.state.current_message):
            # 普通 Entry/追问不强制读取 Evidence；保留审计事件，避免模型重试并消费预算。
            event = {
                "tool": "read_evidence",
                "shared_tool": "read_evidence",
                "status": "not_executed",
                "completeness": "unknown",
                "params": {"entry_id": entry_id, "source_ids": source_ids},
                "error": "普通回答无需来源核验，已跳过 Evidence 读取",
                "reason_code": "evidence_not_required",
                "duration_ms": 0,
                "turn_index": ctx.deps.state.turn_index,
            }
            ctx.deps.state.tool_events.append(event)
            return event
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
        if state.relevance_resume_only:
            raise ModelRetry("续执行只允许完成语义候选筛选，不能重复打开列表对象")
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
                    scope_type=state.scope_type,
                    project_id=state.project_id,
                    project_name=state.project_name,
                    discovered_entry_ids=state.discovered_entry_ids,
                    discovered_entry_fingerprints=state.discovered_entry_fingerprints,
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
        if output.items:
            record = state.result_sets[handle]
            await _bind_entry_result_material(
                state,
                record,
                payload["items"],
                parent_handle=result_set_handle,
            )
            state.focused_entry = payload["items"][0]
            state.focused_entry_refs = record.semantics["entry_validation_refs"][
                str(entry_id)
            ]
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
        state = ctx.deps.state
        previous_draft = state.candidate_draft
        previous_errors = list(state.candidate_draft_errors)
        candidate_message = _candidate_request_message(state)
        if candidate_message is not None:
            answer = _candidate_boundary(
                answer,
                content_only=(
                    state.editing_content_only
                    or _candidate_content_only_requested(candidate_message)
                ),
            )
        answer = resolve_answer_results(answer, state)
        errors = output_errors(answer, ctx.deps.state)
        errors.extend(await _project_material_errors(state, state.current_handles))
        if errors:
            _capture_provisional_answer(answer, state)
            if candidate_message is not None and _safe_candidate_recovery(answer):
                _sync_candidate_recovery(
                    state, answer.model_dump(mode="json"), list(errors)
                )
            elif candidate_message is not None:
                _sync_candidate_recovery(state, previous_draft, previous_errors)
            else:
                state.candidate_draft_errors = list(errors)
            state.instrumentation.finalize_compatibility = None
            message = "；".join(errors)
            state.instrumentation.record_validation_failure(
                "reference_validation", message, answer.model_dump(mode="json")
            )
            raise ModelRetry(message)
        if candidate_message is not None and state.instrumentation.phase != "finalize":
            _sync_candidate_recovery(state, answer.model_dump(mode="json"), [])
        elif candidate_message is None:
            await _persist_discussion_answer(state, answer)
        return answer

    return agent


FINALIZER_SYSTEM_PROMPT = (
    ASSISTANT_ROLE_PROMPT + "\n\n" + ANSWER_PROTOCOL_PROMPT + "\n\n"
    + """当前程序阶段为独立收尾，面向用户仍保持知识协作助手身份。
你只能组织最终 DialogueAnswer，不能调用搜索、目录、Entry 或 Evidence 等任何资料工具，
也不能声称执行了外部核验。无法支持的结论用 insufficient 明确说明。
知识库正式记录、Source 原文与模型分析必须区分，读到来源不等于通过官方交叉验证。
AI 回答或候选修改稿不得声称已经写入正式 Entry。
唯一合法输出顶层是 DialogueAnswer 的 blocks、needs_clarification，以及可选的
discussion_entry_id；只有明确分析某个已展示且已读取 Entry 时才填写该 ID，独立问题或对象
不明确时保持 null。不要输出 answer_summary、completion 或其他自创顶层字段。text 块只填写
kind 与 text，不要添加 note。
结构化材料只选 result 块的 result_handle，程序决定项目、统计、目录或 Entry 展示，
不要猜类型。统计、项目枚举和目录结果只说明范围、过滤和完整性；
项目介绍使用背景目标和已保存上下文，以自然段概括，不必把依据逐个展示成列表。
除非用户明确询问来源核验，不附加官方交叉验证免责声明。""".strip()
)


def build_finalizer_agent(model) -> Agent[LoopDeps, DialogueAnswer]:
    """构造程序级无资料工具 finalizer，只保留结构化输出与引用校验。"""

    agent = Agent(
        model,
        deps_type=LoopDeps,
        output_type=DialogueAnswer,
        instructions=FINALIZER_SYSTEM_PROMPT,
        retries=0,
        model_settings=_dialogue_model_settings(model),
        max_concurrency=1,
        tool_timeout=FINALIZE_SECONDS,
    )

    @agent.instructions
    def answer_basis_instruction(ctx: RunContext[LoopDeps]) -> str:
        state = ctx.deps.state
        draft_instruction = ""
        candidate_message = _candidate_request_message(state)
        if state.candidate_draft and candidate_message is not None:
            gaps = "；".join(state.candidate_draft_errors)
            if _tone_only_candidate_requested(candidate_message):
                revision_basis = (
                    "以上一版候选为内容基准，保留其中的事实、数量归属和限定，只完成表达调整。"
                )
            else:
                revision_basis = (
                    "按用户已明确采纳的分析纠正或补充内容；候选可以与原 Entry 不同，"
                    "不要为了贴合原记录而保留已指出的问题。"
                )
            draft_instruction = (
                "上一阶段已有候选修改稿。它始终只是模型候选；当前 Entry 与 Source 只用于"
                "安全复验、溯源和识别内容边界，不能把候选新增判断升格为正式记录或来源事实。"
                "保留安全内容并修正已记录的缺口；不要因为缺少固定标题而丢弃整篇稿件。"
                + revision_basis
                + (f"当前缺口：{gaps}。" if gaps else "")
            )
        if candidate_message is not None:
            semantic_limit = (
                "这是仅调整表达的任务：保留原记录的事实关系、"
                "数量所属的尺寸含义和建议、约数、可能性等限定，"
                "不得将含糊表达改成更窄或更确定的结论。必须实际完成用户要求的"
                "语气、措辞或精简调整，不能原样重放上一版候选。"
                if _tone_only_candidate_requested(candidate_message)
                else (
                    "这是按分析纠正或补充内容的任务：允许候选与原 Entry 不同，"
                    "但必须区分原记录、模型判断和候选未写入状态。"
                )
            )
            return (
                ("当前是候选稿收尾。保留已保存的候选文本，"
                 if state.candidate_draft else
                 "根据已复验的当前 Entry、用户决定与要求生成候选稿，")
                + "不得输出或引用"
                "Evidence、Entry、列表、统计或其他 Grove 句柄；保存的对象关系只供程序"
                "复验，不是模型的当前轮可引用材料。"
                "用自然的一两句话说明候选基于现有记录、是否有模型增补及"
                "尚未写入，不要堆叠固定章节。"
                + semantic_limit
                + draft_instruction
            )
        if state.editing_active and state.editing_context is not None:
            return (
                "本轮是针对当前唯一 Entry 的普通讨论；围绕该条目解释可补充点，"
                "不要扩展成整个知识库盘点，不要求候选稿章节。材料里的用户决定必须保留。"
                "只输出 text 或 insufficient；分析不等于来源核验，不能声称已写入。"
            )
        if state.tools_allowed:
            return (
                "程序已经取得并核验本轮可用材料。真实统计、列表、正文和来源只能使用"
                "当前材料中已有且获授权的句柄；不得引用历史轮次的材料句柄。"
                + draft_instruction
            )
        return (
            "用户明确要求本轮不使用知识库。只能根据模型通用知识和对话中用于识别讨论对象的"
            "有界叙述作答；这些历史叙述不是可引用证据。只能输出 text 或 insufficient 块，"
            "不得输出统计、列表、Entry、Evidence 或任何 Grove 句柄，不得声称查询、读取、"
            "实时核验或得到 Grove 正式记录与 Source 支持。请明确这是模型通用分析及其边界。"
            + draft_instruction
        )

    @agent.instructions
    def candidate_content_only_instruction(ctx: RunContext[LoopDeps]) -> str:
        candidate_message = _candidate_request_message(ctx.deps.state)
        if candidate_message is None or not (
            ctx.deps.state.editing_content_only
            or _candidate_content_only_requested(candidate_message)
        ):
            return ""
        return (
            "用户只要补充后的候选知识内容。只输出一个 text 块，不得输出或引用 Evidence、"
            "Entry、list、statistic、insufficient；末尾仅保留尚未写入和模型补充不属于"
            "Source 原文的简短边界说明。"
        )

    @agent.output_validator
    async def validate_output(ctx: RunContext[LoopDeps], answer: DialogueAnswer) -> DialogueAnswer:
        state = ctx.deps.state
        previous_draft = state.candidate_draft
        previous_errors = list(state.candidate_draft_errors)
        answer = _candidate_finalizer_text_only(answer, state)
        answer = resolve_answer_results(answer, state)
        candidate_message = _candidate_request_message(state)
        if candidate_message is not None:
            answer = _candidate_boundary(
                answer,
                content_only=(
                    state.editing_content_only
                    or _candidate_content_only_requested(candidate_message)
                ),
            )
        errors = output_errors(answer, state)
        errors.extend(await _project_material_errors(state, state.current_handles))
        if errors:
            _capture_provisional_answer(answer, state)
            if _candidate_request_message(state) is not None:
                if _safe_candidate_recovery(answer):
                    _sync_candidate_recovery(
                        state, answer.model_dump(mode="json"), list(errors)
                    )
                else:
                    _sync_candidate_recovery(state, previous_draft, previous_errors)
            else:
                state.candidate_draft_errors = list(errors)
            if not (
                state.instrumentation.finalize_compatibility
                and state.instrumentation.finalize_compatibility.get("kind")
                == "candidate_text_only"
            ):
                state.instrumentation.finalize_compatibility = None
            message = "；".join(errors)
            state.instrumentation.record_validation_failure(
                "reference_validation", message, answer.model_dump(mode="json")
            )
            raise ModelRetry(message)
        if _candidate_request_message(state) is not None:
            _sync_candidate_recovery(state, answer.model_dump(mode="json"), [])
        else:
            await _persist_discussion_answer(state, answer)
        if _candidate_request_message(state) is None:
            state.candidate_draft_errors.clear()
        return answer

    return agent


def _clean_structural_boilerplate(answer: DialogueAnswer, state: LoopState) -> DialogueAnswer:
    """仅清理纯结构查询中已知的独立模板句，不删除范围、错误或来源分析。"""
    handles = [block.result_handle for block in answer.blocks
               if block.kind in {"list", "statistic"}]
    if _evidence_requested(state.current_message):
        return answer
    if not handles or any(block.kind not in {"text", "list", "statistic"}
                          for block in answer.blocks):
        return answer
    if any(
        handle not in state.current_handles or (record := state.result_sets.get(handle)) is None
        or not record.displayable or record.kind not in {"statistic", "directories", "projects"}
        or record.status not in {"completed", "empty"} or record.completeness != "complete"
        for handle in handles
    ):
        return answer
    redundant = {
        "该统计不代表对记录内容做过官方交叉验证。",
        "该统计仅为知识库正式记录的计数结果，不代表对记录内容做过官方交叉验证。",
    }
    blocks = []
    for block in answer.blocks:
        if block.kind == "text":
            sentences = re.split(r"(?<=[。！？])", block.text)
            cleaned = "".join(sentence for sentence in sentences
                              if re.sub(r"\s+", "", sentence) not in redundant).strip()
            if cleaned:
                blocks.append(block.model_copy(update={"text": cleaned}))
        else:
            blocks.append(block)
    return answer.model_copy(update={"blocks": blocks})


def render_answer(answer: DialogueAnswer, state: LoopState) -> tuple[str, list[dict]]:
    """按模型块顺序以真实工具数据渲染，不接受模型填写数字或原文。"""
    answer = _clean_structural_boilerplate(resolve_answer_results(answer, state), state)
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
                    "result_type": record.kind,
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
            if record.kind == "entries":
                for position, item in enumerate(record.payload.get("items", []), 1):
                    if not item.get("content"):
                        continue
                    entry_answer = DialogueAnswer.model_validate({"blocks": [{
                        "kind": "text", "text": f"[[entry:{record.handle}:{position}]]",
                    }]})
                    entry_text, entry_blocks = render_answer(entry_answer, state)
                    lines.append(entry_text)
                    rendered.extend(entry_blocks)
                continue
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
            elif record.kind == "projects":
                title = "当前 Workspace 可访问项目"
            else:
                scope = (
                    f"{semantics.get('project_name')} · "
                    if semantics.get("project_name")
                    else "全部项目 · "
                )
                relevance_scope = semantics.get("relevance_scope")
                if relevance_scope == "direct":
                    title = f"{scope}直接相关正式记录"
                elif relevance_scope == "indirect":
                    title = f"{scope}间接相关正式记录"
                else:
                    title = f"{scope}正式记录列表"
            lines.append(title)
            items = (
                record.payload.get("projects", [])
                if record.kind == "projects"
                else record.payload.get("items", [])
            )
            for index, item in enumerate(items, 1):
                if record.kind == "directories":
                    lines.append(f"{index}. {item.get('name', '未命名')}（{item.get('path', '')}）")
                elif record.kind == "projects":
                    lines.append(
                        f"{index}. {item.get('name', '未命名项目')}"
                        f"（{item.get('status', '未知状态')}）"
                    )
                else:
                    lines.append(
                        f"{index}. {item.get('title', '未命名')}"
                        f"（{item.get('project_name', '未知项目')}）"
                    )
            rendered.append(
                {
                    "kind": "list",
                    "result_type": record.kind,
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
            "tool_attempted": "收尾模型尝试调用资料工具，程序已拦截",
            "material_invalid": "续执行材料已失效",
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
    model_only = (
        stop.continuation is not None
        and stop.continuation.scope.get("answer_basis") == "model_only"
    )
    status_text = (
        "本轮未生成可展示的通用知识回答，以下说明具体原因和续执行方式。"
        if model_only
        else {
        TURN_NOT_EXECUTED: "本轮查询未执行，以下说明具体原因和缺口。",
        TURN_PARTIAL_COMPLETED: "本轮已部分完成，以下只保留程序确认的结果。",
        TURN_UNSUPPORTED: "当前工具能力不支持完整处理这个任务。",
        TURN_DENIED: "当前权限或数据范围不允许执行这个任务。",
        TURN_FAILED: "本轮遇到系统故障，以下仅保留已经确认的结果。",
        }[stop.status]
    )
    requested_blocks: list[dict] = [{"kind": "text", "text": status_text}]
    candidate_failure = (
        _candidate_request_message(state) is not None
        or (
            stop.continuation is not None
            and stop.continuation.scope.get("answer_basis") == "candidate_draft"
        )
    )
    suppress_saved_material = (
        candidate_failure or stop.reason_code == "continuation_material_invalid"
    )
    provisional = None if suppress_saved_material else _provisional_answer(state)
    if provisional is not None:
        requested_blocks.append(
            {
                "kind": "text",
                "text": (
                    "已保留通过文本边界检查的内容；原完整输出仍未通过结构校验："
                ),
            }
        )
        requested_blocks.extend(
            block.model_dump(mode="json") for block in provisional.blocks
        )
    candidate_text, candidate_blocks = _render_candidate_draft(state)
    if candidate_text and candidate_failure:
        requested_blocks.append(
            {
                "kind": "text",
                "text": "已保留上一阶段生成的候选稿，但尚未通过最终边界校验：",
            }
        )
        requested_blocks.extend(candidate_blocks)
    if not suppress_saved_material:
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
            elif record.kind in {"list", "directories", "projects"}:
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
    if (
        stop.can_continue
        and stop.continuation is not None
        and stop.continuation.task_type in {"finalize_answer", "candidate_draft"}
    ):
        continuation_text = (
            "可以在下一轮说“继续”或“下一轮继续”，系统将保持不使用知识库，"
            "只根据已保存的有界对话上下文重试最终回答。"
            if model_only
            else "可以在下一轮说“继续”或“下一轮继续”，系统将只整理已保存的候选稿，"
            "不重复查询、来源读取或引入新的 Evidence。"
            if stop.continuation.scope.get("answer_basis") == "candidate_draft"
            else "可以在下一轮说“继续”或“下一轮继续”，系统将只根据已保存材料"
            "重试最终回答，不会重复已完成的查询或来源读取。"
        )
    elif stop.can_continue and stop.continuation is not None:
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
    if len(requested_blocks) > ANSWER_BLOCKS_LIMIT:
        omitted = len(requested_blocks) - ANSWER_BLOCKS_LIMIT
        insufficient = dict(requested_blocks[-1])
        suffix = f"另有 {omitted} 项已确认材料保留在本轮恢复状态中，未在失败摘要中重复展示。"
        base = str(insufficient["text"])
        insufficient["text"] = f"{base[: max(1, 2_000 - len(suffix))]}{suffix}"
        requested_blocks = [
            *requested_blocks[: ANSWER_BLOCKS_LIMIT - 1],
            insufficient,
        ]
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


def _material_fingerprint(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finalize_failure_reason(state: LoopState) -> tuple[str, str]:
    status = state.instrumentation.finalize_status
    mapping = {
        "tool_attempted": ("finalize_tool_attempted", "收尾模型尝试调用资料工具"),
        "invalid_output": ("finalize_output_invalid", "收尾输出未通过结构或引用校验"),
        "timed_out": ("finalize_timeout", "收尾请求超过时间预算"),
        "failed": ("finalize_system_failure", "收尾模型请求发生系统故障"),
        "not_dispatched": ("finalize_budget_boundary", "收尾请求受预算或输入上限阻止"),
        "cancelled": ("finalize_cancelled", "收尾请求被取消"),
    }
    return mapping.get(status, (f"finalize_{status}", "最终回答尚未完成"))


def _candidate_draft_answer(state: LoopState) -> DialogueAnswer | None:
    """读取当前轮已生成的候选稿；非法结构不进入恢复或展示路径。"""

    if not state.candidate_draft:
        return None
    try:
        return DialogueAnswer.model_validate(state.candidate_draft)
    except (TypeError, ValueError):
        return None


def _render_candidate_draft(state: LoopState) -> tuple[str, list[dict]]:
    """仅保留候选稿中的安全文本，避免失败收尾展示伪造 Evidence。"""

    answer = _candidate_draft_answer(state)
    if answer is None:
        return "", []
    safe_blocks = []
    for block in answer.blocks:
        if block.kind in {"text", "insufficient"}:
            if block.kind == "text" and (reference := _entry_reference(block.text)):
                handle, position = reference
                record = state.result_sets.get(handle)
                if (
                    handle not in state.current_handles
                    or record is None
                    or record.kind != "entries"
                    or not 1 <= position <= len(record.payload.get("items", []))
                    or not record.payload["items"][position - 1].get("content")
                ):
                    continue
            safe_blocks.append(block)
        elif block.kind == "evidence" and block.evidence_handle in state.current_evidence:
            safe_blocks.append(block)
    if not safe_blocks:
        return "", []
    safe_answer = DialogueAnswer.model_validate(
        {"blocks": [block.model_dump(mode="json") for block in safe_blocks]}
    )
    return render_answer(safe_answer, state)


def _continuation_material(state: LoopState, current_events: list[dict]) -> dict:
    """复制 finalizer 可恢复材料；完整内容只留在当前进程内存。"""

    selected: set[str] = set()
    focused_id = state.editing_context.entry["entry_id"] if (
        state.editing_active and state.editing_context is not None
    ) else None
    target_entry_ids = {
        int(item["entry_id"])
        for handle, item in state.evidence.items()
        if handle in state.current_evidence and item.get("entry_id") is not None
    }
    for handle in state.current_handles:
        record = state.result_sets.get(handle)
        if record is None or not record.displayable:
            continue
        if focused_id is not None and (
            record.kind != "entries"
            or {item.get("entry_id") for item in record.payload.get("items", [])} != {focused_id}
        ):
            continue
        selected.add(handle)
        target_entry_ids.update(
            int(item["entry_id"])
            for item in record.payload.get("items", [])
            if item.get("entry_id") is not None
        )
    if target_entry_ids and focused_id is None:
        for handle, record in state.result_sets.items():
            if not record.displayable or record.kind not in {"list", "entries"}:
                continue
            record_ids = {
                int(item["entry_id"])
                for item in record.payload.get("items", [])
                if item.get("entry_id") is not None
            }
            if record_ids & target_entry_ids:
                selected.add(handle)
    records = {
        handle: {
            "kind": record.kind,
            "payload": record.payload,
            "status": record.status,
            "completeness": record.completeness,
            "turn_index": record.turn_index,
            "semantics": record.semantics,
            "displayable": record.displayable,
        }
        for handle in selected
        if (record := state.result_sets.get(handle)) is not None
    }
    evidence = {
        handle: item
        for handle, item in state.evidence.items()
        if handle in state.current_evidence and focused_id is None
    }
    known_events = {
        event.get("result_handle"): event
        for event in state.tool_events
        if event.get("result_handle") in selected
    }
    for event in current_events:
        handle = event.get("result_handle")
        if handle in selected:
            known_events[handle] = event
    return {
        "mode": "grove_material",
        "records": records,
        "evidence": evidence,
        "events": list(known_events.values()),
        "provisional_answer": state.provisional_answer,
        "record_fingerprints": {
            handle: _material_fingerprint(record) for handle, record in records.items()
        },
    }


def _candidate_continuation_material(
    state: LoopState, current_events: list[dict]
) -> dict:
    """补入最近一轮已确认关系，仅供候选稿续执行复验。"""

    material = _continuation_material(state, current_events)
    if not material["evidence"] and state.history_turns:
        previous = state.history_turns[-1]
        references = (previous.get("answer_summary") or {}).get("references", [])
        referenced_pairs: set[tuple[int, int]] = set()
        for reference in references:
            if reference.get("kind") != "evidence":
                continue
            handle = str(reference.get("handle") or "")
            evidence = state.evidence.get(handle)
            if (
                evidence is None
                or evidence.get("entry_id") not in state.authorized_entry_ids
                or evidence.get("source_id") is None
            ):
                continue
            material["evidence"][handle] = evidence
            referenced_pairs.add(
                (int(evidence["entry_id"]), int(evidence["source_id"]))
            )
        if referenced_pairs:
            for tool in previous.get("tools", []):
                handle = str(tool.get("result_handle") or "")
                record = state.result_sets.get(handle)
                if record is None or not record.displayable or record.kind != "evidence":
                    continue
                record_pairs = {
                    (int(item["entry_id"]), int(item["source_id"]))
                    for item in record.payload.get("items", [])
                    if item.get("entry_id") is not None
                    and item.get("source_id") is not None
                }
                if not (record_pairs & referenced_pairs):
                    continue
                serialized = {
                    "kind": record.kind,
                    "payload": record.payload,
                    "status": record.status,
                    "completeness": record.completeness,
                    "turn_index": record.turn_index,
                    "semantics": record.semantics,
                    "displayable": record.displayable,
                }
                material["records"][handle] = serialized
                material["record_fingerprints"][handle] = _material_fingerprint(
                    serialized
                )
    if state.editing_active and state.editing_context is not None:
        entry_id = int(state.editing_context.entry["entry_id"])
        matching = [
            (handle, record)
            for handle, record in material["records"].items()
            if record.get("kind") == "entries"
            and {
                int(item["entry_id"])
                for item in record.get("payload", {}).get("items", [])
                if item.get("entry_id") is not None
            }
            == {entry_id}
        ]
        if matching:
            handle, record = max(
                matching,
                key=lambda item: (int(item[1].get("turn_index", 0)), item[0]),
            )
            material["records"] = {handle: record}
            material["record_fingerprints"] = {
                handle: _material_fingerprint(record)
            }
            material["evidence"] = {}
            material["editing_context"] = {
                "entry_id": entry_id,
                "entry_handle": handle,
                "decisions": list(state.editing_context.decisions[-4:]),
                "discussion": state.editing_context.discussion,
            }
    # 关系与句柄只留给程序复验，不注入候选稿 finalizer。
    material["events"] = []
    return material


def _model_only_context_turns(state: LoopState) -> list[dict]:
    """复制无资料收尾所需的近期叙述，不携带工具或 Grove 引用元数据。"""
    return [
        {
            "turn": turn.get("turn"),
            "user": str(turn.get("user") or ""),
            "answer_summary": {
                "narrative": (turn.get("answer_summary") or {}).get("narrative", ""),
            },
            "completion": _history_completion_summary(turn.get("completion")),
        }
        for turn in state.history_turns[-6:]
    ]


def _model_only_history(
    state: LoopState,
    message: str,
    context_turns: list[dict] | None = None,
) -> list[ModelMessage]:
    """无资料收尾复用同一裁剪协议，当前问题始终受保护。"""
    turns = context_turns if context_turns is not None else _model_only_context_turns(state)
    messages = _recent_history_messages(turns)
    messages.append(ModelRequest(parts=[UserPromptPart(content=message)]))
    return _trim_optional_history(messages)


async def _database_material_refs(
    state: LoopState,
    entry_ids: list[int],
    source_pairs: list[tuple[int, int]],
) -> dict:
    """直接复验已保存材料，不创建新 Evidence 或模型资料工具事件。"""

    from sqlalchemy.orm import selectinload

    from app.db.session import async_session_factory
    from app.models import Attachment, Entry, EntrySourceEvidence, Project, Source, WorkspaceMember
    from app.services.knowledge_agent.evidence import available_attachment_text

    fingerprints: dict[str, str] = {}
    async with state.database_lock:
        async with async_session_factory() as db:
            member = (
                await db.execute(
                    select(WorkspaceMember.id).where(
                        WorkspaceMember.workspace_id == state.workspace_id,
                        WorkspaceMember.user_id == state.user_id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                raise ValueError("当前用户已不再属于原 Workspace")
            entry_conditions = [
                Entry.id.in_(entry_ids or [-1]),
                Project.workspace_id == state.workspace_id,
            ]
            if state.scope_type == "project":
                if state.project_id is None:
                    raise ValueError("当前项目范围缺少项目身份")
                entry_conditions.append(Entry.project_id == state.project_id)
            entries = (
                await db.execute(
                    select(Entry)
                    .join(Project, Entry.project_id == Project.id)
                    .where(*entry_conditions)
                )
            ).scalars().all()
            by_entry = {int(entry.id): entry for entry in entries}
            missing = sorted(set(entry_ids) - set(by_entry))
            if missing:
                raise ValueError(f"Entry 已删除或移出当前 Workspace：{missing}")
            for entry_id in entry_ids:
                entry = by_entry[entry_id]
                fingerprints[f"entry:{entry_id}"] = _material_fingerprint(
                    {
                        "entry_id": entry_id,
                        "project_id": int(entry.project_id),
                        "node_id": int(entry.node_id),
                        "title": entry.title,
                        "content": entry.content,
                        "updated_at": entry.updated_at.isoformat(),
                    }
                )

            source_ids = sorted({source_id for _, source_id in source_pairs})
            source_conditions = [
                Source.id.in_(source_ids or [-1]),
                Source.workspace_id == state.workspace_id,
            ]
            if state.scope_type == "project":
                source_conditions.append(Source.project_id == state.project_id)
            sources = (
                await db.execute(
                    select(Source)
                    .options(selectinload(Source.attachments))
                    .where(*source_conditions)
                )
            ).scalars().all()
            by_source = {int(source.id): source for source in sources}
            relations = (
                await db.execute(
                    select(EntrySourceEvidence).where(
                        EntrySourceEvidence.entry_id.in_(entry_ids or [-1]),
                        EntrySourceEvidence.source_id.in_(source_ids or [-1]),
                    )
                )
            ).scalars().all()
            by_pair = {
                (int(relation.entry_id), int(relation.source_id)): relation
                for relation in relations
            }
            for entry_id, source_id in source_pairs:
                relation = by_pair.get((entry_id, source_id))
                source = by_source.get(source_id)
                if relation is None or source is None:
                    raise ValueError(
                        f"Entry {entry_id} 与 Source {source_id} 的来源关系已失效"
                    )
                attachment = (
                    await db.get(Attachment, relation.attachment_id)
                    if relation.attachment_id is not None
                    else None
                )
                if attachment is None and source.attachments:
                    attachment = source.attachments[0]
                attachment_text = available_attachment_text(attachment)
                if not attachment_text:
                    raise ValueError(f"Source {source_id} 已没有可复验的 Attachment 文本")
                fingerprints[f"evidence:{entry_id}:{source_id}"] = _material_fingerprint(
                    {
                        "entry_id": entry_id,
                        "source_id": source_id,
                        "source_title": source.title,
                        "source_updated_at": source.updated_at.isoformat(),
                        "relation_id": int(relation.id),
                        "relation_quote": relation.quote or "",
                        "attachment_id": int(attachment.id),
                        "attachment_text": attachment_text,
                    }
                )
            await db.rollback()
    return {
        "workspace_id": state.workspace_id,
        "user_id": state.user_id,
        "entry_ids": entry_ids,
        "source_ids": sorted({source_id for _, source_id in source_pairs}),
        "source_pairs": [list(pair) for pair in source_pairs],
        "fingerprints": fingerprints,
    }


async def _revalidate_discovered_entries(
    state: LoopState, entry_ids: list[int]
) -> dict:
    """复验已分类对象；正文只用于指纹校验，不进入筛选工具返回。"""

    from app.db.session import async_session_factory
    from app.services.knowledge_agent.tools import RunToolContext, read_entries

    async with state.database_lock:
        async with async_session_factory() as db:
            tool_ctx = RunToolContext(
                run_id=state.run_id,
                workspace_id=state.workspace_id,
                owner_user_id=state.user_id,
                scope_type=state.scope_type,
                project_id=state.project_id,
                project_name=state.project_name,
                discovered_entry_ids=state.discovered_entry_ids,
                discovered_entry_fingerprints=state.discovered_entry_fingerprints,
            )
            output = await read_entries(db, tool_ctx, entry_ids)
            await db.rollback()
    return output.model_dump(mode="json")


def _editing_scope(state: LoopState) -> dict:
    """只在活动任务中保存交付语义，公开续执行不包含稿件正文。"""
    if not state.editing_active or state.editing_context is None:
        return {}
    return {
        "editing_active": True,
        "editing_content_only": state.editing_content_only,
        "editing_purpose": state.editing_purpose,
        "editing_entry_id": state.editing_context.entry["entry_id"],
    }


async def _create_finalize_continuation(
    state: LoopState,
    message: str,
    current_events: list[dict],
) -> ContinuationState:
    candidate_draft = _candidate_draft_answer(state)
    if candidate_draft is not None:
        material = _candidate_continuation_material(state, current_events)
        entry_ids = sorted(
            {
                int(item["entry_id"])
                for record in material["records"].values()
                for item in record["payload"].get("items", [])
                if item.get("entry_id") is not None
            }
            | {
                int(item["entry_id"])
                for item in material["evidence"].values()
                if item.get("entry_id") is not None
            }
        )
        source_pairs = sorted(
            {
                (int(item["entry_id"]), int(item["source_id"]))
                for item in material["evidence"].values()
                if item.get("entry_id") is not None and item.get("source_id") is not None
            }
        )
        if state.editing_active and state.editing_context is not None:
            entry_ids = state.editing_context.validation_refs["entry_ids"]
            source_pairs = [tuple(pair) for pair in
                            state.editing_context.validation_refs["source_pairs"]]
        validation_refs = await _database_material_refs(state, entry_ids, source_pairs)
        resolved = []
        for handle, record in material["records"].items():
            if record["kind"] != "list":
                continue
            for position, item in enumerate(record["payload"].get("items", []), 1):
                if item.get("entry_id") in entry_ids:
                    resolved.append(
                        {
                            "result_handle": handle,
                            "position": position,
                            "entry_id": item.get("entry_id"),
                            "title": item.get("title"),
                        }
                    )
        reason_code, reason = _finalize_failure_reason(state)
        return ContinuationState(
            task_type="candidate_draft",
            tool_name="finalize_answer",
            scope={
                "workspace_id": state.workspace_id,
                "user_id": state.user_id,
                "scope_type": state.scope_type,
                "project_id": state.project_id,
                "answer_basis": "candidate_draft",
                **_editing_scope(state),
                "authorized_entry_ids": sorted(state.authorized_entry_ids),
            },
            completed_steps=[
                {"step": "candidate_draft_generated"},
                *[
                    {"tool": event.get("tool"), "result_handle": event.get("result_handle")}
                    for event in current_events
                    if event.get("status") in {"completed", "ok", "limited", "empty"}
                ],
            ],
            pending_steps=[{"step": "finalize_candidate_draft"}],
            confirmed=[{"entry_id": entry_id} for entry_id in validation_refs["entry_ids"]]
            + [{"source_id": source_id} for source_id in validation_refs["source_ids"]],
            stop_reason=f"{reason_code}: {reason}",
            original_question=message,
            resolved_references=resolved,
            recoverable_material={
                **material,
                "mode": "candidate_draft",
                "candidate_draft": state.candidate_draft,
                "candidate_draft_errors": list(state.candidate_draft_errors),
            },
            validation_refs=validation_refs,
        )
    if not state.tools_allowed:
        reason_code, reason = _finalize_failure_reason(state)
        return ContinuationState(
            task_type="finalize_answer",
            tool_name="finalize_answer",
            scope={
                "workspace_id": state.workspace_id,
                "user_id": state.user_id,
                "answer_basis": "model_only",
            },
            completed_steps=[{"step": "model_only_context_preserved"}],
            pending_steps=[{"step": "finalize_answer"}],
            stop_reason=f"{reason_code}: {reason}",
            original_question=message,
            recoverable_material={
                "mode": "model_only",
                "history_turns": _model_only_context_turns(state),
                "records": {},
                "evidence": {},
                "events": [],
                "provisional_answer": state.provisional_answer,
            },
            validation_refs={"mode": "model_only"},
        )
    material = _continuation_material(state, current_events)
    entry_ids = sorted(
        {
            int(item["entry_id"])
            for record in material["records"].values()
            for item in record["payload"].get("items", [])
            if item.get("entry_id") is not None
        }
        | {
            int(item["entry_id"])
            for item in material["evidence"].values()
            if item.get("entry_id") is not None
        }
    )
    source_pairs = sorted(
        {
            (int(item["entry_id"]), int(item["source_id"]))
            for item in material["evidence"].values()
            if item.get("entry_id") is not None and item.get("source_id") is not None
        }
    )
    if state.editing_active and state.editing_context is not None:
        entry_ids = state.editing_context.validation_refs["entry_ids"]
        source_pairs = [tuple(pair) for pair in
                        state.editing_context.validation_refs["source_pairs"]]
    validation_refs = await _database_material_refs(state, entry_ids, source_pairs)
    resolved = []
    for handle, record in material["records"].items():
        if record["kind"] != "list":
            continue
        for position, item in enumerate(record["payload"].get("items", []), 1):
            if item.get("entry_id") in entry_ids:
                resolved.append(
                    {
                        "result_handle": handle,
                        "position": position,
                        "entry_id": item.get("entry_id"),
                        "title": item.get("title"),
                    }
                )
    reason_code, reason = _finalize_failure_reason(state)
    return ContinuationState(
        task_type="finalize_answer",
        tool_name="finalize_answer",
        scope={
            "workspace_id": state.workspace_id,
            "user_id": state.user_id,
            "scope_type": state.scope_type,
            "project_id": state.project_id,
            "answer_basis": "grove_material",
            **_editing_scope(state),
            "authorized_entry_ids": sorted(state.authorized_entry_ids),
        },
        completed_steps=[
            {"tool": event.get("tool"), "result_handle": event.get("result_handle")}
            for event in current_events
            if event.get("status") in {"completed", "ok", "limited", "empty"}
        ],
        pending_steps=[{"step": "finalize_answer"}],
        confirmed=[
            {"entry_id": entry_id} for entry_id in validation_refs["entry_ids"]
        ]
        + [{"source_id": source_id} for source_id in validation_refs["source_ids"]],
        stop_reason=f"{reason_code}: {reason}",
        original_question=message,
        resolved_references=resolved,
        recoverable_material=material,
        validation_refs=validation_refs,
    )


def _restore_finalize_editing_context(
    state: LoopState, continuation: ContinuationState
) -> str | None:
    """只从已通过句柄、授权与数据库指纹复验的单条 Entry 重建任务。"""

    if not continuation.scope.get("editing_active"):
        return None
    material = continuation.recoverable_material
    saved = material.get("editing_context")
    if not isinstance(saved, dict):
        if (
            continuation.task_type == "finalize_answer"
            and state.editing_context is not None
            and state.editing_context.entry.get("entry_id")
            == continuation.scope.get("editing_entry_id")
        ):
            return None
        return "候选续执行缺少可恢复的编辑对象"
    expected_entry_id = continuation.scope.get("editing_entry_id")
    if saved.get("entry_id") != expected_entry_id:
        return "候选续执行的编辑对象不匹配"
    handle = saved.get("entry_handle")
    record = state.result_sets.get(handle) if isinstance(handle, str) else None
    if record is None or record.kind != "entries" or not record.displayable:
        return "候选续执行的 Entry 句柄已失效"
    items = [
        item
        for item in record.payload.get("items", [])
        if item.get("entry_id") == expected_entry_id
    ]
    if len(items) != 1 or len(record.payload.get("items", [])) != 1:
        return "候选续执行必须唯一定位当前 Entry"
    decisions = saved.get("decisions")
    if not isinstance(decisions, list) or any(
        not isinstance(item, str) for item in decisions
    ):
        return "候选续执行的用户要求已失效"
    state.editing_context = EditingContext(
        entry=items[0],
        validation_refs=continuation.validation_refs,
        draft=material.get("candidate_draft"),
        discussion=(
            saved.get("discussion")
            if isinstance(saved.get("discussion"), str)
            else None
        ),
        decisions=decisions or [continuation.original_question],
    )
    return None


async def _validate_finalize_continuation(
    state: LoopState, continuation: ContinuationState
) -> tuple[bool, str | None]:
    if continuation.task_type not in {"finalize_answer", "candidate_draft"}:
        return False, "续执行任务类型不匹配"
    if continuation.scope.get("workspace_id") != state.workspace_id:
        return False, "续执行 Workspace 与当前范围不一致"
    if continuation.scope.get("user_id") != state.user_id:
        return False, "续执行用户与当前身份不一致"
    if continuation.scope.get("editing_active") and (
        continuation.scope.get("scope_type") != state.scope_type
        or continuation.scope.get("project_id") != state.project_id
    ):
        return False, "续执行项目范围与当前任务不一致"
    material = continuation.recoverable_material
    if material.get("provisional_answer") is not None:
        try:
            provisional = DialogueAnswer.model_validate(material["provisional_answer"])
        except (TypeError, ValueError):
            return False, "续执行中保留的普通文本结构已失效"
        if any(block.kind != "text" for block in provisional.blocks):
            return False, "续执行中保留的内容包含未经授权的结构化结果"
    answer_basis = continuation.scope.get("answer_basis", "grove_material")
    if answer_basis == "model_only":
        if material.get("mode") != "model_only":
            return False, "无资料续执行的回答依据已失效"
        if any(material.get(key) for key in ("records", "evidence", "events")):
            return False, "无资料续执行不能携带 Grove 材料或工具事件"
        if continuation.validation_refs.get("mode") != "model_only":
            return False, "无资料续执行的校验范围不匹配"
        if not continuation.original_question:
            return False, "无资料续执行缺少原始问题"
        if not isinstance(material.get("history_turns"), list):
            return False, "无资料续执行缺少可恢复的对话上下文"
        return True, None
    if answer_basis == "candidate_draft":
        if material.get("mode") != "candidate_draft":
            return False, "候选稿续执行的回答依据已失效"
        if _candidate_draft_answer(state) is None and not material.get("candidate_draft"):
            return False, "候选稿续执行缺少可恢复的候选文本"
        try:
            DialogueAnswer.model_validate(material.get("candidate_draft"))
        except (TypeError, ValueError):
            return False, "候选稿续执行的文本结构已失效"
    elif answer_basis != "grove_material":
        return False, "续执行回答依据不受支持"
    if (
        not material.get("records")
        and not material.get("evidence")
        and not material.get("candidate_draft")
        and not material.get("provisional_answer")
    ):
        return False, "续执行没有保存可恢复材料"
    project_errors = await _project_material_errors(state, set(material.get("records", {})))
    if project_errors:
        return False, "；".join(project_errors)
    for handle, expected in material.get("record_fingerprints", {}).items():
        record = state.result_sets.get(handle)
        if record is None or not record.displayable:
            return False, f"结果句柄已失效或不可展示：{handle}"
        actual = _material_fingerprint(
            {
                "kind": record.kind,
                "payload": record.payload,
                "status": record.status,
                "completeness": record.completeness,
                "turn_index": record.turn_index,
                "semantics": record.semantics,
                "displayable": record.displayable,
            }
        )
        if actual != expected:
            return False, f"结果句柄材料已变化：{handle}"
    authorized = set(continuation.scope.get("authorized_entry_ids", []))
    if not set(continuation.validation_refs.get("entry_ids", [])).issubset(authorized):
        return False, "续执行材料包含未授权 Entry"
    if not authorized.issubset(state.authorized_entry_ids):
        return False, "授权结果集合已经变化"
    try:
        current = await _database_material_refs(
            state,
            list(continuation.validation_refs.get("entry_ids", [])),
            [tuple(pair) for pair in continuation.validation_refs.get("source_pairs", [])],
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if current.get("fingerprints") != continuation.validation_refs.get("fingerprints"):
        return False, "Entry、Source、来源关系或材料版本已经变化"
    editing_error = _restore_finalize_editing_context(state, continuation)
    if editing_error is not None:
        return False, editing_error
    return True, None


async def _validate_relevance_continuation(
    state: LoopState, continuation: ContinuationState
) -> tuple[bool, str | None]:
    if continuation.task_type != "relevance_selection":
        return False, "续执行任务类型不匹配"
    expected_scope = {
        "workspace_id": state.workspace_id,
        "user_id": state.user_id,
        "scope_type": state.scope_type,
        "project_id": state.project_id,
    }
    if any(continuation.scope.get(key) != value for key, value in expected_scope.items()):
        return False, "续执行 Workspace、用户或项目范围已经变化"
    material = continuation.recoverable_material
    records = material.get("records") if material.get("mode") == "relevance_selection" else None
    if not isinstance(records, dict) or not records:
        return False, "续执行缺少可恢复的语义候选"
    if material.get("provisional_answer") is not None:
        try:
            provisional = DialogueAnswer.model_validate(material["provisional_answer"])
        except (TypeError, ValueError):
            return False, "续执行中保留的普通文本结构已失效"
        if any(block.kind != "text" for block in provisional.blocks):
            return False, "续执行中保留的内容包含未经授权的结构化结果"
    expected_handles = set(continuation.scope.get("candidate_handles", []))
    if set(records) != expected_handles:
        return False, "候选句柄集合已经变化"
    entry_ids = []
    for handle, record in records.items():
        if (
            not isinstance(record, dict)
            or record.get("handle") != handle
            or record.get("kind") != "list"
            or record.get("displayable") is not False
            or (record.get("semantics") or {}).get("result_role") != "candidate"
        ):
            return False, f"候选句柄已失效：{handle}"
        if _material_fingerprint(record) != material.get("record_fingerprints", {}).get(
            handle
        ):
            return False, f"候选句柄材料已变化：{handle}"
        entry_ids.extend(
            int(item["entry_id"])
            for item in (record.get("payload") or {}).get("items", [])
            if item.get("entry_id") is not None
        )
    if sorted(set(entry_ids)) != sorted(continuation.validation_refs.get("entry_ids", [])):
        return False, "候选 Entry 集合已经变化"
    try:
        current = await _database_material_refs(state, sorted(set(entry_ids)), [])
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if current.get("fingerprints") != continuation.validation_refs.get("fingerprints"):
        return False, "候选 Entry 的权限、范围或版本已经变化"
    return True, None


def _restore_relevance_candidates(
    state: LoopState, continuation: ContinuationState
) -> None:
    for handle, raw in continuation.recoverable_material["records"].items():
        state.result_sets[handle] = ResultRecord(
            handle=handle,
            kind=str(raw["kind"]),
            payload=raw["payload"],
            status=str(raw["status"]),
            completeness=str(raw["completeness"]),
            turn_index=state.turn_index,
            semantics=raw.get("semantics") or {},
            displayable=False,
        )
        state.current_handles.add(handle)
    state.provisional_answer = continuation.recoverable_material.get(
        "provisional_answer"
    )


async def _run_relevance_continuation(
    agent: Agent[LoopDeps, DialogueAnswer],
    finalizer: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    history_estimate: int,
    before_logs: int,
    before_events: int,
    started: float,
) -> tuple[dict, list[ModelMessage]]:
    """复验并恢复未完成三分筛选；资料查询在该模式下禁止派发。"""

    continuation = state.active_continuation
    assert continuation is not None and continuation.task_type == "relevance_selection"
    valid, invalid_reason = await _validate_relevance_continuation(state, continuation)
    if not valid:
        state.continuation = None
        state.active_continuation = None
        stop = StopState(
            status=TURN_NOT_EXECUTED,
            reason_code="continuation_material_invalid",
            reason=invalid_reason or "续执行候选已经失效",
            incomplete_steps=["旧候选不能安全复用，需要重新发起查询"],
            can_continue=False,
        )
        state.stop_state = stop
        text, blocks = _verified_failure_output(state, stop)
        completion = state.completion_snapshot(TURN_NOT_EXECUTED)
        state.remember_turn(message, text, [], blocks=blocks, completion=completion)
        return {
            "message": message,
            "status": TURN_NOT_EXECUTED,
            "answer": text,
            "blocks": blocks,
            "error": None,
            "error_details": None,
            "solve_error": None,
            "solve_failure": None,
            "duration_ms": int((perf_counter() - started) * 1000),
            "usage": None,
            "budget": state.ledger.snapshot(),
            "tool_calls": [],
            "model_calls": [
                asdict(item) for item in state.instrumentation.logs[before_logs:]
            ],
            "context": {
                "history_estimated_input_tokens": history_estimate,
                "history_turns": len(state.history_turns),
                "continuation_mode": "relevance_selection",
            },
            "finalization": state.instrumentation.finalization_snapshot(),
            "completion": completion,
        }, build_compact_history(state)

    _restore_relevance_candidates(state, continuation)
    original_message = continuation.original_question or message
    state.current_message = original_message
    state.relevance_resume_only = True
    state.relevance_resume_running = True
    try:
        turn, new_history = await run_turn(
            agent, state, original_message, history, finalizer
        )
    finally:
        state.relevance_resume_only = False
        state.relevance_resume_running = False
        state.current_message = message
        state.active_continuation = None
    turn["message"] = message
    turn.setdefault("context", {})["continuation_mode"] = "relevance_selection"
    if turn.get("status") == TURN_COMPLETED:
        state.continuation = None
    return turn, new_history


async def _attach_finalize_continuation(
    state: LoopState,
    message: str,
    current_events: list[dict],
) -> bool:
    if _pending_semantic_candidates(state):
        return False
    if state.instrumentation.finalize_status in {"not_needed", "completed", "cancelled"}:
        return False
    if (
        state.tools_allowed
        and not _reliable_current_records(state)
        and not state.current_evidence
        and _candidate_draft_answer(state) is None
        and _provisional_answer(state) is None
    ):
        return False
    try:
        continuation = await _create_finalize_continuation(state, message, current_events)
    except Exception as exc:  # noqa: BLE001
        if state.instrumentation.finalize_failure is None:
            state.instrumentation.finalize_failure = {
                "category": "continuation_material_invalid",
                "message": str(exc),
                "exception_chain": [],
                "validation": None,
                "public_response": None,
            }
        return False
    state.continuation = continuation
    reason_code, reason = _finalize_failure_reason(state)
    if state.stop_state is None:
        state.stop_state = StopState(
            status=TURN_PARTIAL_COMPLETED,
            reason_code=reason_code,
            reason=reason,
        )
    model_only = continuation.scope.get("answer_basis") == "model_only"
    state.stop_state.status = TURN_NOT_EXECUTED if model_only else TURN_PARTIAL_COMPLETED
    state.stop_state.reason_code = reason_code
    state.stop_state.reason = reason
    state.stop_state.can_continue = True
    state.stop_state.continuation = continuation
    state.stop_state.incomplete_steps = [
        "通用知识回答尚未生成"
        if model_only
        else "来源已取得，可信度分析尚未完成"
        if state.current_evidence
        else "材料已取得，最终回答尚未完成"
    ]
    return True


def _current_material_history(
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
    *,
    model_only_context: list[dict] | None = None,
) -> list[ModelMessage]:
    """把求解阶段已取得的当前轮材料重建为合法配对消息。"""
    if not state.tools_allowed and not (
        state.editing_active and state.editing_context is not None
    ):
        messages = _model_only_history(state, message, model_only_context)
        provisional = _provisional_answer(state)
        if provisional is not None:
            messages.append(ModelRequest(parts=[UserPromptPart(content=json.dumps({
                "已通过文本边界检查的待收尾内容": provisional.model_dump(mode="json"),
                "边界": "只保留这些普通文本；原完整输出未通过合同校验。",
            }, ensure_ascii=False))]))
        return messages
    draft = _candidate_draft_answer(state)
    candidate_only = draft is not None and _candidate_request_message(state) is not None
    messages = [ModelRequest(parts=[UserPromptPart(content=message)])]
    focused = state.editing_active and state.editing_context is not None
    if not candidate_only and not focused and state.history_turns:
        messages = [
            ModelRequest(parts=[UserPromptPart(content=json.dumps({
                "近期用户问题（仅理解指代，不是本轮查询材料）":
                    [turn["user"] for turn in state.history_turns[-3:]],
            }, ensure_ascii=False))]),
            *messages,
        ]
    if focused:
        messages.append(ModelRequest(parts=[UserPromptPart(content=json.dumps({
            "当前唯一讨论对象": state.editing_context.entry,
            "用户决定": state.editing_context.decisions,
            "上次针对该对象的讨论（模型分析）": state.editing_context.discussion,
            "交付模式": state.editing_purpose,
            "边界": (
                "仅围绕此 Entry 回答。补充讨论是模型分析，"
                "不表示 Source 已核验或已写入。"
                + (
                    "只调整表达；保留原文事实关系、数量维度和程度/不确定性。"
                    if _tone_only_candidate_requested(message)
                    else ""
                )
            ),
        }, ensure_ascii=False))]))
    if draft is not None:
        draft_text = "\n".join(
            block.text
            for block in draft.blocks
            if block.kind in {"text", "insufficient"}
        )
        if draft_text:
            draft_instruction = (
                "上一阶段已生成候选修改稿。只调整表达，必须以上一版候选为内容基准，"
                "保留事实、数量归属和限定：\n"
                if _tone_only_candidate_requested(message)
                else "上一阶段已生成候选修改稿。按用户已经明确采纳的分析纠正或补充内容，"
                "候选允许与原 Entry 不同，并修复已记录缺口：\n"
            )
            messages.append(
                ModelRequest(
                    parts=[
                        UserPromptPart(
                            content=draft_instruction + draft_text
                        )
                    ]
                )
            )
    provisional = _provisional_answer(state)
    if provisional is not None and draft is None:
        messages.append(ModelRequest(parts=[UserPromptPart(content=json.dumps({
            "已通过文本边界检查的待收尾内容": provisional.model_dump(mode="json"),
            "边界": (
                "保留这些普通文本；原完整输出未通过合同校验，未筛选候选不得进入回答。"
            ),
        }, ensure_ascii=False))]))
    if candidate_only or focused:
        current_events = []
    for index, event in enumerate(current_events, 1):
        handle = event.get("result_handle")
        if handle not in state.current_handles and event.get("status") not in {
            "denied",
            "error",
            "not_executed",
        }:
            continue
        record = state.result_sets.get(handle)
        if record is not None and not record.displayable:
            continue
        tool_name = event.get("tool") or "unknown_tool"
        call_id = f"finalize-{state.turn_index}-{index}"
        content = _history_tool_summary(state, event)
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
    finalizer: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    current_events: list[dict],
    reason: str,
    *,
    model_only_context: list[dict] | None = None,
) -> object:
    """在独立时间窗内用当前轮已核验材料做唯一一次无工具收尾。"""
    state.instrumentation.begin_finalize(reason)
    before_logs = len(state.instrumentation.logs)
    project_errors = await _project_material_errors(state, state.current_handles)
    if project_errors:
        raise ValueError("；".join(project_errors))
    material_history = _current_material_history(
        state,
        message,
        history,
        current_events,
        model_only_context=model_only_context,
    )
    finalizer_prompt = (
        "求解阶段已停止。用户明确要求不使用知识库；请只基于通用知识和有界对话叙述"
        "完成回答，并清楚说明它不是 Grove 材料或外部权威核验。"
        if not state.tools_allowed
        else (
            "求解阶段已停止。请以上一版候选为内容基准，只完成用户要求的表达调整。"
            if _tone_only_candidate_requested(message)
            else "求解阶段已停止。请按已保存的分析和候选稿完成纠正或补充。"
        )
        if _candidate_draft_answer(state) is not None
        else "求解阶段已停止。请只根据本轮已获得并核验的材料收尾。"
    )
    try:
        async with asyncio.timeout(FINALIZE_SECONDS):
            return await finalizer.run(
                finalizer_prompt,
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
        if isinstance(exc, FinalizeToolAttempted):
            pass
        elif state.instrumentation.finalize_response_received:
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


async def _run_finalize_continuation(
    finalizer: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    history_estimate: int,
    before_logs: int,
    before_events: int,
    started: float,
) -> tuple[dict, list[ModelMessage]]:
    """只复验并重试最终回答，不重新执行已完成的资料步骤。"""

    continuation = state.active_continuation
    assert continuation is not None and continuation.task_type in {
        "finalize_answer",
        "candidate_draft",
    }
    valid, invalid_reason = await _validate_finalize_continuation(state, continuation)
    solve_error = None
    solve_failure = None
    usage = None
    error_details = None
    if not valid:
        state.continuation = None
        state.active_continuation = None
        state.instrumentation.finalize_status = "material_invalid"
        state.instrumentation.finalize_error = invalid_reason
        stop = StopState(
            status=TURN_NOT_EXECUTED,
            reason_code="continuation_material_invalid",
            reason=invalid_reason or "续执行材料已经失效",
            incomplete_steps=["旧材料不能安全复用，需要重新核验"],
            can_continue=False,
        )
        state.stop(stop)
        text, blocks = _verified_failure_output(state, stop)
        status = TURN_NOT_EXECUTED
        error = None
    else:
        material = continuation.recoverable_material
        state.provisional_answer = material.get("provisional_answer")
        candidate_only = continuation.scope.get("answer_basis") == "candidate_draft"
        state.editing_active = bool(continuation.scope.get("editing_active"))
        state.editing_content_only = bool(continuation.scope.get("editing_content_only"))
        state.editing_purpose = continuation.scope.get("editing_purpose", "discussion")
        if candidate_only:
            _sync_candidate_recovery(
                state,
                material.get("candidate_draft"),
                list(material.get("candidate_draft_errors", [])),
            )
        else:
            state.current_handles.update(material.get("records", {}))
            state.current_evidence.update(material.get("evidence", {}))
        try:
            result = await _finalize_once(
                finalizer,
                state,
                continuation.original_question or message,
                history,
                [] if candidate_only else list(material.get("events", [])),
                "continuation_finalize_only",
                model_only_context=(
                    material.get("history_turns", [])
                    if continuation.scope.get("answer_basis") == "model_only"
                    else None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            reason_code, reason = _finalize_failure_reason(state)
            model_only = continuation.scope.get("answer_basis") == "model_only"
            no_progress = False
            if candidate_only:
                current_pair = {
                    "candidate_draft": state.candidate_draft,
                    "candidate_draft_errors": list(state.candidate_draft_errors),
                }
                current_signature = _material_fingerprint(current_pair)
                previous_signature = material.get("last_recovery_signature")
                no_progress = previous_signature == current_signature
                if no_progress:
                    reason_code = "candidate_recovery_no_progress"
                    reason = "连续两次恢复得到相同的安全候选和缺口，本次没有进展"
                    state.continuation = None
                    state.active_continuation = None
                else:
                    material["last_recovery_signature"] = current_signature
            continuation.stop_reason = f"{reason_code}: {reason}"
            stop = StopState(
                status=TURN_NOT_EXECUTED if model_only else TURN_PARTIAL_COMPLETED,
                reason_code=reason_code,
                reason=reason,
                incomplete_steps=[
                    "通用知识回答尚未生成"
                    if model_only
                    else "来源已取得，可信度分析尚未完成"
                    if material.get("evidence")
                    else "材料已取得，最终回答尚未完成"
                ],
                can_continue=not no_progress,
                continuation=None if no_progress else continuation,
            )
            state.stop(stop)
            text, blocks = _verified_failure_output(state, stop)
            status = TURN_NOT_EXECUTED if model_only else TURN_PARTIAL_COMPLETED
            error = None
            error_details = state.instrumentation.finalize_failure or {
                "category": reason_code,
                "message": str(exc),
            }
        else:
            text, blocks = render_answer(result.output, state)
            state.instrumentation.complete_finalize()
            state.continuation = None
            state.active_continuation = None
            state.candidate_draft = None
            state.candidate_draft_errors.clear()
            state.stop_state = None
            status = TURN_COMPLETED
            error = None
            usage = asdict(result.usage) if result.usage is not None else None
    current_events = state.tool_events[before_events:]
    completion = state.completion_snapshot(status)
    state.remember_turn(
        message,
        text,
        current_events,
        blocks=blocks,
        completion=completion,
    )
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
            "continuation_mode": "finalize_only",
        },
        "finalization": state.instrumentation.finalization_snapshot(),
        "completion": completion,
    }, new_history


async def run_turn(
    agent: Agent[LoopDeps, DialogueAnswer],
    state: LoopState,
    message: str,
    history: list[ModelMessage],
    finalizer: Agent[LoopDeps, DialogueAnswer] | None = None,
) -> tuple[dict, list[ModelMessage]]:
    """执行一轮；超限、模型失败和 usage 缺失均显式保留。"""
    finalizer = finalizer or build_finalizer_agent(agent.model)
    if state.history_turns:
        history = build_compact_history(state)
    history = _without_historical_system_prompts(history)
    history_estimate = estimate_input_tokens(history)
    before_logs = len(state.instrumentation.logs)
    before_events = len(state.tool_events)
    started = perf_counter()
    solve_error = None
    solve_failure = None
    error_details = None
    if _failed_turn_without_continuation(state, message):
        stop = StopState(
            status=TURN_NOT_EXECUTED,
            reason_code="continuation_not_available",
            reason="当前没有可恢复的未完成步骤",
            incomplete_steps=["未找到可续执行的最终回答状态"],
            can_continue=False,
        )
        state.stop(stop)
        text, blocks = _verified_failure_output(state, stop)
        completion = state.completion_snapshot(TURN_NOT_EXECUTED)
        state.remember_turn(
            message,
            text,
            [],
            blocks=blocks,
            completion=completion,
        )
        return {
            "message": message,
            "status": TURN_NOT_EXECUTED,
            "answer": text,
            "blocks": blocks,
            "error": None,
            "error_details": None,
            "solve_error": None,
            "solve_failure": None,
            "duration_ms": int((perf_counter() - started) * 1000),
            "usage": None,
            "budget": state.ledger.snapshot(),
            "tool_calls": [],
            "model_calls": [],
            "context": {
                "history_estimated_input_tokens": history_estimate,
                "input_estimates": [],
                "history_turns": len(state.history_turns),
                "solve_seconds_limit": PER_TURN_SECONDS,
                "finalize_seconds_limit": FINALIZE_SECONDS,
                "continuation_mode": "not_available",
            },
            "finalization": state.instrumentation.finalization_snapshot(),
            "completion": completion,
        }, build_compact_history(state)
    if state.active_continuation is not None and state.active_continuation.task_type in {
        "finalize_answer",
        "candidate_draft",
    }:
        return await _run_finalize_continuation(
            finalizer,
            state,
            message,
            history,
            history_estimate,
            before_logs,
            before_events,
            started,
        )
    if (
        state.active_continuation is not None
        and state.active_continuation.task_type == "relevance_selection"
        and not state.relevance_resume_running
    ):
        return await _run_relevance_continuation(
            agent,
            finalizer,
            state,
            message,
            history,
            history_estimate,
            before_logs,
            before_events,
            started,
        )
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
                    finalizer,
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
        budget_reason = _budget_stop_reason(exc)
        if (
            budget_reason == "input_hard_limit"
            and not _reliable_current_records(state)
            and not state.current_evidence
        ):
            state.instrumentation.begin_finalize("input_hard_limit")
            state.instrumentation.finalize_status = "not_dispatched"
            state.instrumentation.finalize_error = str(exc)
            text, blocks = _verified_failure_output(state)
            status = state.stop_state.status if state.stop_state else TURN_NOT_EXECUTED
            error = None
            error_details = solve_failure
            usage = None
        elif not state.instrumentation.context_policy_enabled:
            text, blocks = _verified_failure_output(state)
            status = TURN_PARTIAL_COMPLETED
            error = None
            error_details = solve_failure
            usage = None
        else:
            try:
                result = await _finalize_once(
                    finalizer,
                    state,
                    message,
                    history,
                    state.tool_events[before_events:],
                    budget_reason,
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
                    finalizer,
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
    pending_semantic = bool(_pending_semantic_candidates(state))
    if (
        event_stop is not None
        and event_stop.reason_code == "relevance_selection_pending"
        and status == TURN_COMPLETED
        and not any(block.get("kind") == "insufficient" for block in blocks)
    ):
        # 无工具收尾已经完整回答了当前任务；内部候选从未授权，也不作为空结果展示。
        event_stop = None
        state.stop_state = None
    elif pending_semantic and (
        event_stop is not None
        or status != TURN_COMPLETED
        or any(block.get("kind") == "insufficient" for block in blocks)
    ):
        if await _attach_relevance_continuation(state, message, current_events):
            event_stop = state.stop_state
    if event_stop is not None:
        state.stop(event_stop)
        status = event_stop.status
        if (status in {TURN_NOT_EXECUTED, TURN_UNSUPPORTED, TURN_DENIED, TURN_FAILED}
                or event_stop.reason_code == "relevance_selection_pending"):
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
    if await _attach_finalize_continuation(state, message, current_events):
        status = TURN_PARTIAL_COMPLETED
        error = None
        text, blocks = _verified_failure_output(state, state.stop_state)
    elif status == TURN_COMPLETED:
        state.candidate_draft = None
        state.candidate_draft_errors.clear()
    completion = state.completion_snapshot(status)
    state.remember_turn(
        message,
        text,
        current_events,
        blocks=blocks,
        completion=completion,
    )
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
        "completion": completion,
    }, new_history
