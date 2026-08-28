"""知识 Agent 回答组织器：基于已核验 Evidence 句柄生成结构化回答草稿。"""

import logging
from time import perf_counter

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models.knowledge_agent import PURPOSE_ANSWER
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

ANSWER_PROMPT_VERSION = "v1"


class KnowledgeCitationDraft(BaseModel):
    """回答模型选择的 Evidence 句柄；服务端最终校验。"""

    evidence_handle: str = ""


class KnowledgeConflictDraft(BaseModel):
    """冲突双方（Evidence 句柄）与说明。"""

    evidence_handle_a: str = ""
    evidence_handle_b: str = ""
    summary: str = ""


class KnowledgeAnswerDraft(BaseModel):
    """一次问答的结构化草稿。"""

    answer: str = ""
    citations: list[KnowledgeCitationDraft] = []
    conflicts: list[KnowledgeConflictDraft] = []
    insufficient: bool = False
    insufficient_note: str | None = None


KNOWLEDGE_ANSWER_SYSTEM_PROMPT = (
    "你是 Grove 的知识 Agent，负责基于已确认知识与服务端核验的原文证据回答用户问题。"
    "\n"
    "要求："
    "\n"
    "1. 只能基于给定的已确认 Entry 与核验原文回答；知识不足时明确标记 insufficient，"
    "不得使用模型自身知识悄悄补齐。"
    "\n"
    "2. 关键结论必须通过 citations 引用给定的 Evidence 句柄（形如 ev_xxxxxxxx），"
    "句柄必须原样使用，不得改写或编造。"
    "\n"
    "3. 不得自行生成 quote 或引号原文；引用原文以服务端提供的核验片段为准。"
    "\n"
    "4. 多条 Entry 说法矛盾时，用 conflicts 并列展示双方各自的 Evidence 句柄与各自观点，"
    "不要替用户裁决。"
    "\n"
    "5. 即时回答不是正式知识，不得修改任何正式数据。"
)


def _format_context(
    query: str,
    scope_label: str,
    entries: list[dict],
) -> str:
    """组装回答上下文：只包含已发现 Entry 与可引用 Evidence 句柄。"""
    parts = [f"问题：{query}", f"问答范围：{scope_label}", "可用已确认知识："]
    for item in entries:
        parts.append(f"- Entry {item['entry_id']}：{item['title']}")
        parts.append(f"  项目：{item['project_name']}")
        if item.get("node_path"):
            parts.append(f"  目录：{item['node_path']}")
        parts.append(f"  内容：{item['content'][:600]}")
        for evidence in item.get("evidences", []):
            parts.append(
                f"  来源「{evidence['source_title']}」核验原文："
                f"句柄 {evidence['handle']} 「{evidence['quote']}」"
            )
    parts.append(
        "引用规则：citations 只能使用上面列出的句柄；句柄必须完整原样返回；"
        "不要把原文片段当成句柄。"
    )
    return "\n".join(parts)


def _offline_answer() -> KnowledgeAnswerDraft:
    """离线确定性兜底：明确提示模型不可用，不编造内容。"""
    return KnowledgeAnswerDraft(
        answer="当前没有可用的文本模型，无法基于知识库生成带引用的回答。请先配置文本模型密钥，或检查模型服务状态。",
        insufficient=True,
        insufficient_note="文本模型不可用",
    )


async def run_knowledge_answer_agent(
    db,
    workspace_id: int,
    query: str,
    scope_label: str,
    entries: list[dict],
) -> tuple[KnowledgeAnswerDraft, StageMeta]:
    """运行回答 Agent，返回 (草稿, 阶段元数据)。"""
    started = perf_counter()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_answer(),
            StageMeta(
                purpose=PURPOSE_ANSWER,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_context(query, scope_label, entries)
    agent = Agent(
        text_model,
        output_type=KnowledgeAnswerDraft,
        system_prompt=KNOWLEDGE_ANSWER_SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0.4},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("知识 Agent 回答模型调用失败：%s", exc)
        return (
            _offline_answer(),
            StageMeta(
                purpose=PURPOSE_ANSWER,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_answer(),
            StageMeta(
                purpose=PURPOSE_ANSWER,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_ANSWER,
            provider="llm",
            model=str(model_name),
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
