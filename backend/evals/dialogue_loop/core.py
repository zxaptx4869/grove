"""实验的冻结合同、数据模型与共享预算。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

PROMPT_VERSION = "dialogue-loop-v3"
EXPERIMENT_VERSION = "prototype-v3"
INPUT_BYTES_LIMIT = 48_000
MODEL_INPUT_TOKENS_LIMIT = 12_000
INPUT_ESTIMATE_SOFT_LIMIT = 9_000
INPUT_ESTIMATE_VERSION = "openai-chat-projection-v1"
INPUT_ESTIMATE_METHOD = (
    "OpenAI 兼容请求投影的 JSON UTF-8 字节数除以 3 向上取整，"
    "另加消息、工具和固定协议安全余量"
)
HISTORY_ANSWER_CHARS_PER_TURN = 1_200
HISTORY_INPUT_TOKENS_TARGET = 5_000
OUTPUT_TOKENS_LIMIT = 2_000
PER_TURN_TEXT_REQUESTS = 12
PER_TURN_EMBEDDING_REQUESTS = 4
PER_TURN_TOOL_CALLS = 8
PER_TURN_ENTRY_READS = 30
PER_TURN_EVIDENCE_READS = 20
PER_TURN_SECONDS = 120.0
FINALIZE_SECONDS = 15.0
BATCH_TEXT_REQUESTS = 192
BATCH_EMBEDDING_REQUESTS = 64
MAX_TOOL_CONCURRENCY = 2

TURN_COMPLETED = "completed"
TURN_PARTIAL_COMPLETED = "partial_completed"
TURN_NOT_EXECUTED = "not_executed"
TURN_UNSUPPORTED = "unsupported"
TURN_DENIED = "denied"
TURN_FAILED = "failed"
TURN_TERMINAL_STATUSES = {
    TURN_COMPLETED,
    TURN_PARTIAL_COMPLETED,
    TURN_NOT_EXECUTED,
    TURN_UNSUPPORTED,
    TURN_DENIED,
    TURN_FAILED,
}


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    turns: tuple[str, ...]


SCENARIOS = (
    Scenario(
        "A",
        "统计和范围",
        (
            "我现在知识库里一共多少条知识",
            "分项目汇总给我",
            "其中房子装修项目有多少条",
            "回到全部项目，分别统计数量",
        ),
    ),
    Scenario(
        "B",
        "混合问答",
        (
            "甲醛是什么，我知识库里有说甲醛哪里来的，以及怎么除甲醛吗",
            "环保等级呢",
            "我的知识库里关于这些等级有哪些记录",
            "只根据我的知识库总结这些等级，没有的就说没找到",
        ),
    ),
    Scenario(
        "C",
        "列表与话题",
        (
            "列出房子装修项目最近更新的五条知识",
            "第三条展开说说",
            "先不查知识库，聊聊怎样记笔记更容易复习",
            "回到刚才那个五条列表，第三条的来源是什么",
        ),
    ),
)

# 变体不加入 Agent 提示词；只有显式选择第二版套件时才进入彩排或对照。
VARIANT_SCENARIOS = (
    Scenario(
        "D",
        "项目切换与明确类型",
        (
            "先告诉我房子装修项目一共有多少条正式记录",
            "换成新疆旅行项目呢",
            "这个项目里只算 method 类型",
            "取消类型限制，回到这个项目的全部正式记录",
        ),
    ),
    Scenario(
        "E",
        "话题切换后的列表引用变体",
        (
            "把房子装修项目最近更新的五条记录列给我",
            "展开第二项",
            "先别查库，聊聊怎样安排间隔复习",
            "回到前面的列表，第二项来自哪份材料",
        ),
    ),
)
ALL_SCENARIOS = (*SCENARIOS, *VARIANT_SCENARIOS)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextBlock(StrictModel):
    kind: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=4_000)
    note: str = Field(default="", max_length=500, exclude=True)


class StatisticBlock(StrictModel):
    kind: Literal["statistic"] = "statistic"
    result_handle: str
    label: str = Field(min_length=1, max_length=200)


class ListBlock(StrictModel):
    kind: Literal["list"] = "list"
    result_handle: str
    label: str = Field(min_length=1, max_length=200)


class EvidenceBlock(StrictModel):
    kind: Literal["evidence"] = "evidence"
    evidence_handle: str
    note: str = Field(default="", max_length=500)


class InsufficientBlock(StrictModel):
    kind: Literal["insufficient"] = "insufficient"
    text: str = Field(min_length=1, max_length=2_000)


OutputBlock = Annotated[
    TextBlock | StatisticBlock | ListBlock | EvidenceBlock | InsufficientBlock,
    Field(discriminator="kind"),
]


class DialogueAnswer(StrictModel):
    """模型只能排列可信句柄；真实数值、列表和原文由程序渲染。"""

    blocks: list[OutputBlock] = Field(min_length=1, max_length=12)
    needs_clarification: bool = False


class BudgetExceeded(RuntimeError):
    """冻结预算耗尽；调用不得派发。"""


@dataclass
class ContinuationState:
    """跨轮保存的可续任务；完整材料只留在当前进程内存。"""

    task_type: str
    tool_name: str
    scope: dict = field(default_factory=dict)
    completed_steps: list[dict] = field(default_factory=list)
    pending_steps: list[dict] = field(default_factory=list)
    confirmed: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    original_question: str | None = None
    resolved_references: list[dict] = field(default_factory=list)
    recoverable_material: dict = field(default_factory=dict, repr=False)
    validation_refs: dict = field(default_factory=dict, repr=False)

    def snapshot(self) -> dict:
        value = asdict(self)
        material = value.pop("recoverable_material", {})
        validation_refs = value.pop("validation_refs", {})
        value["material_summary"] = {
            "answer_basis": material.get("mode", "grove_material"),
            "result_handles": sorted(material.get("records", {})),
            "evidence_handles": sorted(material.get("evidence", {})),
            "entry_ids": validation_refs.get("entry_ids", []),
            "source_ids": validation_refs.get("source_ids", []),
            "fingerprint_count": len(validation_refs.get("fingerprints", {})),
        }
        return value


@dataclass
class StopState:
    """程序权威的当前轮停止原因和完成语义。"""

    status: Literal[
        "not_executed", "partial_completed", "unsupported", "denied", "failed"
    ]
    reason_code: str
    reason: str
    incomplete_steps: list[str] = field(default_factory=list)
    can_continue: bool = False
    continuation: ContinuationState | None = None

    def snapshot(self) -> dict:
        value = asdict(self)
        # “可继续”只表示存在可实际恢复的程序状态，不表示用户可以重新发问。
        value["can_continue"] = self.continuation is not None
        value["continuation"] = (
            self.continuation.snapshot() if self.continuation is not None else None
        )
        return value


@dataclass
class TurnBudget:
    text_requests: int = 0
    embedding_requests: int = 0
    tool_calls: int = 0
    entry_reads: set[int] = field(default_factory=set)
    evidence_reads: int = 0


@dataclass
class BudgetLedger:
    """单子进程持有累计批次计数，初值由父进程传入。"""

    batch_text_requests: int = 0
    batch_embedding_requests: int = 0
    active: TurnBudget | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def start_turn(self) -> TurnBudget:
        self.active = TurnBudget()
        return self.active

    async def reserve_text(self) -> None:
        async with self._lock:
            turn = self._require_turn()
            if turn.text_requests >= PER_TURN_TEXT_REQUESTS:
                raise BudgetExceeded("本轮文本模型请求预算已耗尽")
            if self.batch_text_requests >= BATCH_TEXT_REQUESTS:
                raise BudgetExceeded("整批文本模型请求预算已耗尽")
            turn.text_requests += 1
            self.batch_text_requests += 1

    async def reserve_embedding(self) -> None:
        async with self._lock:
            turn = self._require_turn()
            if turn.embedding_requests >= PER_TURN_EMBEDDING_REQUESTS:
                raise BudgetExceeded("本轮向量请求预算已耗尽")
            if self.batch_embedding_requests >= BATCH_EMBEDDING_REQUESTS:
                raise BudgetExceeded("整批向量请求预算已耗尽")
            turn.embedding_requests += 1
            self.batch_embedding_requests += 1

    async def reserve_tool(self) -> None:
        async with self._lock:
            turn = self._require_turn()
            if turn.tool_calls >= PER_TURN_TOOL_CALLS:
                raise BudgetExceeded("本轮工具动作预算已耗尽")
            turn.tool_calls += 1

    def reserve_entries(self, entry_ids: list[int]) -> None:
        turn = self._require_turn()
        proposed = turn.entry_reads | set(entry_ids)
        if len(proposed) > PER_TURN_ENTRY_READS:
            raise BudgetExceeded("本轮不同 Entry 读取预算已耗尽")
        turn.entry_reads = proposed

    def reserve_evidence(self, count: int) -> None:
        turn = self._require_turn()
        if turn.evidence_reads + count > PER_TURN_EVIDENCE_READS:
            raise BudgetExceeded("本轮 Evidence 读取预算已耗尽")
        turn.evidence_reads += count

    def snapshot(self) -> dict:
        turn = asdict(self._require_turn()) if self.active else None
        if turn is not None:
            turn["entry_reads"] = sorted(turn["entry_reads"])
        return {
            "batch_text_requests": self.batch_text_requests,
            "batch_embedding_requests": self.batch_embedding_requests,
            "turn": turn,
        }

    @property
    def active_text_requests(self) -> int:
        return self._require_turn().text_requests

    @property
    def active_tool_calls(self) -> int:
        return self._require_turn().tool_calls

    @property
    def remaining_tool_calls(self) -> int:
        return max(PER_TURN_TOOL_CALLS - self._require_turn().tool_calls, 0)

    @property
    def remaining_text_requests(self) -> int:
        turn = self._require_turn()
        return min(
            max(PER_TURN_TEXT_REQUESTS - turn.text_requests, 0),
            max(BATCH_TEXT_REQUESTS - self.batch_text_requests, 0),
        )

    def _require_turn(self) -> TurnBudget:
        if self.active is None:
            raise RuntimeError("尚未开始评测轮次")
        return self.active


def frozen_budget(messages_per_batch: int = 24) -> dict:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "input_bytes_per_turn": INPUT_BYTES_LIMIT,
        "model_input_tokens_per_request": MODEL_INPUT_TOKENS_LIMIT,
        "input_estimate_soft_limit": INPUT_ESTIMATE_SOFT_LIMIT,
        "input_estimate_version": INPUT_ESTIMATE_VERSION,
        "input_estimate_method": INPUT_ESTIMATE_METHOD,
        "history_answer_chars_per_turn": HISTORY_ANSWER_CHARS_PER_TURN,
        "history_input_tokens_target": HISTORY_INPUT_TOKENS_TARGET,
        "finalize_request_reserved": 1,
        "output_tokens_per_request": OUTPUT_TOKENS_LIMIT,
        "text_requests_per_turn": PER_TURN_TEXT_REQUESTS,
        "embedding_requests_per_turn": PER_TURN_EMBEDDING_REQUESTS,
        "tool_calls_per_turn": PER_TURN_TOOL_CALLS,
        "different_entries_per_turn": PER_TURN_ENTRY_READS,
        "evidence_per_turn": PER_TURN_EVIDENCE_READS,
        "solve_seconds_per_turn": PER_TURN_SECONDS,
        "finalize_seconds": FINALIZE_SECONDS,
        "text_requests_per_batch": BATCH_TEXT_REQUESTS,
        "embedding_requests_per_batch": BATCH_EMBEDDING_REQUESTS,
        "tool_concurrency": MAX_TOOL_CONCURRENCY,
        "messages_per_batch": messages_per_batch,
    }
