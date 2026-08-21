"""Reader Agent：基于已确认 Entry 生成带引用的问答草稿。"""

import logging
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models import Entry
from app.services.ai_models import get_text_model

logger = logging.getLogger(__name__)


class ReaderCitationDraft(BaseModel):
    """单条回答引用。"""

    entry_id: int
    source_id: int
    quote: str = ""


class ReaderConflictDraft(BaseModel):
    """一组矛盾 Entry。"""

    entry_id_a: int
    entry_id_b: int
    summary: str = ""


class ReaderAnswerDraft(BaseModel):
    """一次问答的结构化结果。"""

    answer: str = ""
    citations: list[ReaderCitationDraft] = []
    insufficient: bool = False
    insufficient_note: str | None = None
    conflicts: list[ReaderConflictDraft] = []
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None


READER_SYSTEM_PROMPT = """你是 Grove 的 Reader Agent，负责基于已确认知识回答用户问题。

要求：
1. 只能基于给定的已确认 Entry 回答；知识库不足时明确说明，不得使用模型自身知识悄悄补齐。
2. 关键结论必须通过 citations 引用对应的 Entry（entry_id）与其 Source（source_id），
   quote 为原文片段。
3. 多条 Entry 说法矛盾时，用 conflicts 并列展示双方 Entry 与各自观点，不要替用户裁决。
4. citations 与 conflicts 的 entry_id 必须是给定的 Entry id。
5. citations 的 source_id 必须是给定 Entry 的「来源」列表中出现的 id，不得编造。
6. 为回答推荐主类型 main_type（knowledge/method/parameter/reminder）与
   信息性质 info_nature（fact/experience/advice/speculation/other），基于回答内容判断。
7. 即时回答不是正式知识，不得修改任何正式数据。"""


def _format_context(
    query: str,
    scope_label: str,
    entries: list[Entry],
    project_context_text: str | None,
) -> str:
    """组装问答上下文。"""
    parts = [f"问题：{query}", f"问答范围：{scope_label}"]
    if project_context_text:
        parts.append(f"项目上下文：{project_context_text}")
    parts.append("可用已确认 Entry：")
    for entry in entries:
        parts.append(f"- Entry {entry.id}：{entry.title}")
        parts.append(f"  内容：{entry.content[:300]}")
        source_refs: list[str] = []
        for evidence in entry.evidences:
            title = evidence.source.title if evidence.source else "未命名来源"
            source_refs.append(f"{evidence.source_id}（{title}）")
        if source_refs:
            parts.append(f"  来源：{'、'.join(source_refs)[:200]}")
    return "\n".join(parts)


def _offline_answer() -> ReaderAnswerDraft:
    """离线确定性兜底：明确提示模型不可用，不编造内容。"""
    return ReaderAnswerDraft(
        answer="当前没有可用的文本模型，无法基于知识库生成带引用的回答。请先配置文本模型密钥，或检查模型服务状态。",
        insufficient=True,
        insufficient_note="文本模型不可用",
    )


async def run_reader_agent(
    db,
    workspace_id: int,
    query: str,
    scope_label: str,
    entries: list[Entry],
    project_context_text: str | None = None,
) -> tuple[ReaderAnswerDraft, str, str | None, bool, str | None]:
    """运行 Reader Agent，返回 (草稿, provider, model, 是否降级, 降级原因)。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return _offline_answer(), "offline", None, True, "未配置文本模型密钥"

    context = _format_context(query, scope_label, entries, project_context_text)
    agent = Agent(
        text_model,
        output_type=ReaderAnswerDraft,
        system_prompt=READER_SYSTEM_PROMPT,
        retries=1,
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Reader 模型调用失败，降级为离线回答：%s", exc)
        return _offline_answer(), "llm", str(model_name), True, f"模型调用失败：{exc}"
    if result.output is None:
        logger.warning("Reader 未返回结构化结果，降级为离线回答")
        return _offline_answer(), "llm", str(model_name), True, "模型未返回结构化结果"
    return result.output, "llm", str(model_name), False, None
