"""语义重排 Agent：对确定性召回的候选按语义相关度排序。"""

import logging

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models import Entry
from app.services.ai_models import get_text_model

logger = logging.getLogger(__name__)


class SemanticRankResult(BaseModel):
    """单条语义重排结果。"""

    entry_id: int
    reason: str = ""


class SemanticRankingDraft(BaseModel):
    """一次语义重排的结构化结果。"""

    results: list[SemanticRankResult] = []


SEMANTIC_SYSTEM_PROMPT = """你是 Grove 的语义重排步骤。
请根据用户查询，对给定的候选 Entry 按语义相关度从高到低排序。

要求：
1. entry_id 必须是给定候选 Entry 的 id，不要输出不存在的 id。
2. 优先保留与查询同主题的候选；跨主题的候选仅在强相关时保留，拿不准的不保留，宁可少给。
3. 只保留与查询语义相关的候选；语义不相关的不要保留。
4. reason 用一句话说明该 Entry 与查询的关联，方便用户理解。
5. AI 输出永远是候选，不得修改任何正式数据。"""


def _format_context(query: str, candidates: list[Entry]) -> str:
    """组装语义重排的查询与候选上下文。"""
    parts = [f"查询：{query}", "候选 Entry："]
    for entry in candidates:
        parts.append(f"- Entry {entry.id}：{entry.title}")
        parts.append(f"  内容：{entry.content[:300]}")
    parts.append("请按语义相关度从高到低输出这些 Entry 的 id 与理由。")
    return "\n".join(parts)


def _offline_ranking(candidates: list[Entry]) -> SemanticRankingDraft:
    """离线确定性兜底：保持传入的召回顺序（即按召回分数降序）。"""
    return SemanticRankingDraft(
        results=[
            SemanticRankResult(entry_id=entry.id, reason="")
            for entry in candidates
        ]
    )


async def run_semantic_agent(
    db,
    workspace_id: int,
    query: str,
    candidates: list[Entry],
) -> tuple[SemanticRankingDraft, str, str | None, bool, str | None]:
    """运行语义重排 Agent，返回 (草稿, provider, model, 是否降级, 降级原因)。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return _offline_ranking(candidates), "offline", None, True, "未配置文本模型密钥"

    context = _format_context(query, candidates)
    agent = Agent(
        text_model,
        output_type=SemanticRankingDraft,
        system_prompt=SEMANTIC_SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("语义重排模型调用失败，降级为确定性结果：%s", exc)
        return (
            _offline_ranking(candidates),
            "llm",
            str(model_name),
            True,
            f"模型调用失败：{exc}",
        )
    if result.output is None:
        logger.warning("语义重排未返回结构化结果，降级为确定性结果")
        return (
            _offline_ranking(candidates),
            "llm",
            str(model_name),
            True,
            "模型未返回结构化结果",
        )
    return result.output, "llm", str(model_name), False, None
