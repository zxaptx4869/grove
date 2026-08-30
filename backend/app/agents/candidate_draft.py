"""候选草稿生成 Agent：只组合服务端允许的 Evidence，输出可编辑草稿。

约束：
- 输入只包含原问题、原回答（编辑上下文）、目标项目标签与受限 Evidence；
- 模型只能从服务端给出的句柄中选择，不得输出 Workspace/项目/对象 ID；
- 模型只生成草稿，任何 Source/Candidate/Entry/目录写入都由应用服务在用户确认后执行；
- 模型不可用或非法输出时由应用层决定确定性降级或稳定失败，不伪装成功。
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

CANDIDATE_DRAFT_PROMPT_VERSION = "v1"
MAX_DRAFT_CONTENT_CHARS = 8000


class CandidateDraftOutput(BaseModel):
    """模型输出的可编辑草稿：句柄必须属于服务端允许集合。"""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"]
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None
    selected_evidence_handles: list[str] = []


CANDIDATE_DRAFT_SYSTEM_PROMPT = (
    "你是 Grove 的知识整理助手，负责把一次带引用的知识 Agent 回答整理为可编辑的候选草稿。"
    "\n"
    "要求："
    "\n"
    "1. 只能基于给定的目标项目与核验原文证据组织草稿；不得使用模型自身知识或外部常识补齐。"
    "\n"
    "2. 原回答只作为编辑上下文参考，草稿事实必须能由 selected_evidence_handles 中列出的"
    "证据原文支撑；无依据的内容不得写入草稿。"
    "\n"
    "3. selected_evidence_handles 只能从给定 Evidence 句柄中原样选择，至少一条，"
    "不得改写、编造或混入其他句柄。"
    "\n"
    "4. 不得输出 Workspace、项目、Source、Entry、Candidate 或目录对象标识，"
    "不得要求或建议任何数据库写入；你只负责生成草稿文本。"
    "\n"
    "5. title 简洁明确（建议不超过 30 字）；content 直接表达可确认的核心内容，"
    "不使用“根据以上内容”“以下草稿”等无信息开场。"
    "\n"
    "6. main_type 从 knowledge / method / parameter / reminder 中选择，"
    "info_nature 从 fact / experience / advice / speculation / other 中选择。"
)


def _format_context(
    *,
    question: str,
    original_answer: str,
    target_project_label: str,
    evidences: list[dict],
) -> str:
    """组装草稿上下文：目标项目 + 原问题/原回答 + 受限 Evidence。"""
    parts = [
        f"目标项目：{target_project_label}",
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


def _clip_draft_text(text: str, limit: int = MAX_DRAFT_CONTENT_CHARS) -> str:
    """确定性截断草稿正文：优先在换行处截断，保证不超过 schema 上限。"""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    cut = stripped[:limit]
    newline = cut.rfind("\n")
    if newline >= limit // 2:
        cut = cut[:newline]
    return cut.rstrip()


def seed_draft_from_answer(
    *,
    question: str,
    original_answer: str,
    handles: list[str],
) -> CandidateDraftOutput:
    """模型不可用时的确定性可编辑 seed：绑定全部有效句柄并显式降级标识。"""
    title = (original_answer.strip().splitlines() or [""])[0][:50] or "整理知识草稿"
    return CandidateDraftOutput(
        title=title,
        content=_clip_draft_text(original_answer) or "（原回答为空，请编辑后确认）",
        main_type="knowledge",
        info_nature=None,
        selected_evidence_handles=list(handles),
    )


async def run_candidate_draft_agent(
    db,
    workspace_id: int,
    *,
    question: str,
    original_answer: str,
    target_project_label: str,
    evidences: list[dict],
) -> tuple[CandidateDraftOutput | None, StageMeta]:
    """运行草稿生成模型，返回 (草稿, 阶段可观测元数据)。

    模型不可用（未配置/TestModel/调用失败/非法输出）时返回 (None, meta)，
    由调用方决定确定性 seed 降级或稳定失败；本函数不把失败伪装为成功。
    """
    started = perf_counter()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            None,
            StageMeta(
                purpose="draft_candidate",
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_context(
        question=question,
        original_answer=original_answer,
        target_project_label=target_project_label,
        evidences=evidences,
    )
    agent = Agent(
        text_model,
        output_type=CandidateDraftOutput,
        system_prompt=CANDIDATE_DRAFT_SYSTEM_PROMPT,
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
        logger.warning("候选草稿模型调用失败：%s", exc)
        return (
            None,
            StageMeta(
                purpose="draft_candidate",
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
                purpose="draft_candidate",
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error="模型未返回结构化草稿",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose="draft_candidate",
            provider="llm",
            model=str(model_name),
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
