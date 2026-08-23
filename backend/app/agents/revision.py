"""修订建议 Agent：为单条已确认 Entry 生成并对话调整修订草稿。"""

import logging
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models import Entry
from app.schemas.entry import RevisionChatMessage
from app.services.ai_models import get_text_model

logger = logging.getLogger(__name__)


class RevisionDraft(BaseModel):
    """对目标 Entry 的建议修订草稿。"""

    title: str | None = None
    content: str | None = None
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = None
    note: str | None = None
    change_summary: str = ""
    reason: str = ""
    external_supplemented: bool = False


class RevisionReplyDraft(BaseModel):
    """一轮修订建议的结构化结果。"""

    intent: Literal["discuss", "propose"] = "discuss"
    reply_text: str = ""
    draft: RevisionDraft | None = None


REVISION_SYSTEM_PROMPT = """你是 Grove 的修订建议 Agent，为单条已确认 Entry 提出修订建议。

要求：
1. 结合给定 Entry 的内容与其来源证据，并可使用 AI 自身知识（外部知识）进行求证与补充；
   回复中必须区分「材料/知识库内容」与「AI 知识补充」（如标注「这部分是 AI 知识，建议核实」）；
   草稿使用外部知识时 external_supplemented 必须为 true；不得编造来源证据，引用必须真实存在。
2. 输出始终是候选草稿（draft），不得声称已修改正式 Entry；正式修改由用户确认后执行。
3. draft 给出建议的最终字段值；未建议修改的字段留空（表示保持现状）；
   change_summary 用一句话说明改了什么；reason 说明为什么建议这样改。
4. 每次回复必须显式二选一：
   - intent=discuss：用户提问、求证、讨论、质疑或分析时使用，只返回 reply_text，
     draft 必须为 null，不得强行生成草稿；
   - intent=propose：用户明确要求修改（补充、精简、改写法、加条件、修正内容等）时使用，
     返回更新后的完整草稿；未涉及部分保持原值。
5. 如果用户要求修改但没有实质改进空间，intent=discuss，reply_text 直接说明无需修改。
6. 首次对话同样适用以上规则：首条指令是讨论或提问时 intent=discuss。
7. reply_text 是对用户的自然回复，说明理解与处理结果，不得提及内部字段或输出格式
   （如 intent、draft、JSON、null、结构等）。"""


def _format_entry_context(entry: Entry) -> str:
    """组装目标 Entry 与来源证据上下文。"""
    parts = [
        f"目标 Entry {entry.id}：{entry.title}",
        f"内容：{entry.content}",
        f"主类型：{entry.main_type}",
    ]
    if entry.info_nature:
        parts.append(f"信息性质：{entry.info_nature}")
    if entry.applicable_condition:
        parts.append(f"适用条件：{entry.applicable_condition}")
    if entry.note:
        parts.append(f"补充说明：{entry.note}")
    if entry.evidences:
        parts.append("来源证据：")
        for evidence in entry.evidences:
            source_title = evidence.source.title if evidence.source else "未命名来源"
            parts.append(f"- 来源「{source_title}」：{evidence.quote or '（无引用片段）'}")
    return "\n".join(parts)


def _format_conversation(
    instruction: str | None,
    messages: list[RevisionChatMessage],
    current_draft: dict | None,
) -> str:
    """组装对话与当前草稿上下文。"""
    parts: list[str] = []
    if instruction:
        parts.append(f"用户本轮指令：{instruction}")
    if messages:
        parts.append("历史对话：")
        for message in messages:
            role = "用户" if message.role == "user" else "AI"
            parts.append(f"- {role}：{message.content}")
    if current_draft:
        parts.append("当前草稿：")
        for key, value in current_draft.items():
            if value:
                parts.append(f"- {key}：{value}")
    return "\n".join(parts)


def _offline_reply(reason: str) -> tuple[RevisionReplyDraft, str, str | None, bool, str]:
    """离线确定性兜底：明确提示模型不可用，不生成草稿。"""
    return (
        RevisionReplyDraft(
            reply_text="当前没有可用的文本模型，无法生成修订建议。请先配置文本模型密钥，或检查模型服务状态。"
        ),
        "offline",
        None,
        True,
        reason,
    )


async def run_revision_agent(
    db,
    workspace_id: int,
    entry: Entry,
    instruction: str | None,
    messages: list[RevisionChatMessage],
    current_draft: dict | None,
) -> tuple[RevisionReplyDraft, str, str | None, bool, str | None]:
    """运行修订建议 Agent，返回 (回复草稿, provider, model, 是否降级, 降级原因)。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return _offline_reply("未配置文本模型密钥")

    context_parts = [_format_entry_context(entry)]
    conversation = _format_conversation(instruction, messages, current_draft)
    if conversation:
        context_parts.append(conversation)
    context = "\n\n".join(context_parts)

    agent = Agent(
        text_model,
        output_type=RevisionReplyDraft,
        system_prompt=REVISION_SYSTEM_PROMPT,
        retries=1,
        model_settings={"temperature": 0.3},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("修订建议模型调用失败，降级返回：%s", exc)
        return _offline_reply(f"模型调用失败：{exc}")
    if result.output is None:
        logger.warning("修订建议未返回结构化结果，降级返回")
        return _offline_reply("模型未返回结构化结果")
    return result.output, "llm", str(model_name), False, None
