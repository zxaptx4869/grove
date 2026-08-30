"""知识 Agent 单 Entry 修订草稿生成：只组合最终采用且当前有效的 Evidence。

约束：
- 输入只包含目标 Entry 当前字段、用户显式指令、原问题/原回答（编辑上下文）
  与服务端允许的最终采用 Evidence；
- 模型只能从服务端给出的句柄中选择，不得使用模型常识、联网知识或不可核验
  历史快照补充事实，不得输出 Workspace/项目/Entry/Source 对象标识，
  不得声称已执行写入；
- 模型不可用、输出非法或无实际差异时返回 (None, meta)，由应用层将
  Draft/Run 置为可重试失败，禁止用确定性文案或原回答伪装成功修订。
"""

import logging
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

ENTRY_REVISION_PROMPT_VERSION = "v1"
MAX_FIELD_CHARS = 8000


class EntryRevisionOutput(BaseModel):
    """模型输出的可编辑修订草稿：句柄必须属于服务端允许集合。"""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"]
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None
    applicable_condition: str | None = Field(default=None, max_length=8000)
    note: str | None = Field(default=None, max_length=8000)
    change_summary: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    selected_evidence_handles: list[str] = []


ENTRY_REVISION_SYSTEM_PROMPT = (
    "你是 Grove 的知识修订助手，负责把用户对单条正式知识的明确修订要求"
    "整理为可编辑的候选草稿。"
    "\n"
    "要求："
    "\n"
    "1. 只能基于目标 Entry 当前内容、用户修订指令和给定的核验 Evidence 原文"
    "组织草稿；不得使用模型自身知识、外部常识或联网内容补充事实。"
    "\n"
    "2. 原回答只作为编辑上下文参考，草稿修改必须能由 selected_evidence_handles "
    "中列出的证据原文支撑；无依据的表述不得写入草稿。"
    "\n"
    "3. selected_evidence_handles 只能从给定 Evidence 句柄中原样选择，至少一条，"
    "不得改写、编造或混入其他句柄。"
    "\n"
    "4. 不得输出 Workspace、项目、Source、Entry、Candidate、目录或数据库对象标识，"
    "不得声称任何内容已被保存或写入；你只负责生成候选草稿文本。"
    "\n"
    "5. 保留原 Entry 中仍然正确的内容，只按指令修改需要变化的部分；"
    "title 简洁明确，content 直接表达核心内容，不使用“根据以上内容”等无信息开场。"
    "\n"
    "6. change_summary 用一句话概括本次修改；reason 说明依据的 Evidence。"
    "\n"
    "7. main_type 从 knowledge / method / parameter / reminder 中选择，"
    "info_nature 从 fact / experience / advice / speculation / other 中选择；"
    "applicable_condition 与 note 没有变化时可返回 null。"
)


def _format_context(
    *,
    entry: dict,
    instruction: str,
    question: str,
    original_answer: str,
    evidences: list[dict],
) -> str:
    """组装修订上下文：目标 Entry + 用户指令 + 原回答 + 受限 Evidence。"""
    parts = [
        f"目标 Entry（当前正式内容）：\n{_format_entry(entry)}",
        f"用户修订指令：{instruction}",
        f"原问题：{question}",
        f"原回答（仅作编辑上下文，不得把无证据总结写入草稿）：{original_answer}",
        "可采用的核验 Evidence：",
    ]
    for item in evidences:
        parts.append(
            f"- 句柄 {item['handle']}｜来源「{item['source_title']}」｜原文「{item['quote']}」"
        )
    parts.append(
        "规则：selected_evidence_handles 只能使用上面列出的句柄；"
        "句柄必须完整原样返回。"
    )
    return "\n".join(parts)


def _format_entry(entry: dict) -> str:
    """把基线快照格式化为模型可读字段。"""
    lines = [
        f"标题：{entry.get('title') or ''}",
        f"核心内容：{entry.get('content') or ''}",
        f"主类型：{entry.get('main_type') or ''}",
        f"信息性质：{entry.get('info_nature') or ''}",
        f"适用条件：{entry.get('applicable_condition') or ''}",
        f"补充说明：{entry.get('note') or ''}",
    ]
    return "\n".join(lines)


async def run_entry_revision_agent(
    db,
    workspace_id: int,
    *,
    entry: dict,
    instruction: str,
    question: str,
    original_answer: str,
    evidences: list[dict],
) -> tuple[EntryRevisionOutput | None, StageMeta]:
    """运行修订草稿模型，返回 (草稿, 阶段可观测元数据)。

    模型不可用（未配置/TestModel/调用失败/非法输出）时返回 (None, meta)，
    由调用方将 Run/Draft 置为可重试失败，不生成伪草稿。
    """
    started = perf_counter()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            None,
            StageMeta(
                purpose="entry_revision",
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_context(
        entry=entry,
        instruction=instruction,
        question=question,
        original_answer=original_answer,
        evidences=evidences,
    )
    agent = Agent(
        text_model,
        output_type=EntryRevisionOutput,
        system_prompt=ENTRY_REVISION_SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0.3},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(
        text_model, "model", "unknown"
    )
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("修订草稿模型调用失败：%s", exc)
        return (
            None,
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            None,
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error="模型未返回结构化修订草稿",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose="entry_revision",
            provider="llm",
            model=str(model_name),
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
