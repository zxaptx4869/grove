"""Organizing Agent：把 Source 文本解析为结构化候选草稿。"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryImage
from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from app.models import Attachment, Project, Source
from app.services.ai_models import get_text_model, get_vision_model
from app.services.attachment_storage import AttachmentStorage


class EvidenceRefDraft(BaseModel):
    """候选证据引用。"""

    attachment_id: int
    quote: str


class CandidateDraft(BaseModel):
    """单条候选草稿。"""

    candidate_kind: Literal["recommended", "other"] = "recommended"
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    main_type: Literal["knowledge", "method", "parameter", "reminder"]
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = None
    note: str | None = None
    evidence: list[EvidenceRefDraft] = []
    reason: str = ""
    risk_flags: list[str] = []


class ExtractionDraft(BaseModel):
    """一次整理的结构化候选结果。"""

    source_title: str = ""
    candidates: list[CandidateDraft] = []
    discarded_count: int = 0
    discarded_reason_summary: str | None = None


class _OCRText(BaseModel):
    """视觉模型抽取出的图片文字。"""

    text: str


SYSTEM_PROMPT = """你是 Grove 的整理 Agent。请把用户提供的原始材料拆分为可独立理解和使用的候选知识。

要求：
1. 语义上不同的信息不要强行合并，但也不要逐句拆碎。
2. 只输出默认应进入确认队列的推荐候选，或保存意图不明确的其他发现；
   广告、寒暄、无法理解或明显无关的内容不要输出为候选。
3. 每条候选必须通过 evidence 引用其来源的 attachment_id 和原文/OCR 片段。
4. main_type 只使用 knowledge（知识）、method（方法）、parameter（参数）、reminder（提醒）。
5. source_title 生成简洁、可识别的标题，不超过 120 字。
6. AI 输出永远是候选，不直接成为正式知识。"""


def _format_context(
    source: Source,
    sections: list[tuple[int, str]],
    project: Project | None,
) -> str:
    """把 Source 与附件文本组装为 Agent 输入。"""
    parts: list[str] = []
    if source.note:
        parts.append(f"采集说明：{source.note}")
    if project is not None and project.description:
        parts.append(f"项目说明：{project.description}")
    parts.append("原始材料：")
    for attachment_id, text in sections:
        parts.append(f"\n[附件 {attachment_id}]\n{text}")
    return "\n".join(parts)


def _offline_draft(source: Source, sections: list[tuple[int, str]]) -> ExtractionDraft:
    """离线确定性候选，仅用于未配置密钥时的验收。"""
    if not sections:
        return ExtractionDraft(
            source_title=source.title,
            candidates=[],
            discarded_count=0,
            discarded_reason_summary="没有可解析的文本附件",
        )
    first_id, first_text = sections[0]
    first_text = (first_text or "").strip()
    if not first_text:
        first_text = source.note or source.title
    return ExtractionDraft(
        source_title=first_text[:40],
        candidates=[
            CandidateDraft(
                candidate_kind="recommended",
                title=source.title or "示例候选",
                content=first_text[:2000],
                main_type="knowledge",
                info_nature="fact",
                evidence=[EvidenceRefDraft(attachment_id=first_id, quote=first_text[:200])],
                reason="离线示例候选",
                risk_flags=["离线示例"],
            )
        ],
        discarded_count=0,
        discarded_reason_summary=None,
    )


async def ocr_attachment(model: Model, attachment: Attachment) -> str:
    """把图片附件 OCR 为文本；离线模式返回确定性占位文本。"""
    if isinstance(model, TestModel):
        return f"[图片 OCR：{attachment.file_name or attachment.id}]"
    path = AttachmentStorage.from_settings().resolve(attachment.file_path)
    if not path.exists():
        raise RuntimeError(f"附件文件不存在：{attachment.file_name}")
    data = path.read_bytes()
    image = BinaryImage(data=data, media_type=attachment.mime_type or "image/png")
    agent = Agent(model, output_type=_OCRText, system_prompt="请按顺序抽取图片中的文字。")
    result = await agent.run([image, "请输出图片中的全部文字。"])
    return result.output.text if result.output else ""


async def build_sections(
    db,
    source: Source,
    attachments: list[Attachment],
) -> list[tuple[int, str]]:
    """组装带附件 ID 的文本片段；图片先 OCR。"""
    sections: list[tuple[int, str]] = []
    for attachment in attachments:
        if attachment.kind == "text":
            sections.append((attachment.id, attachment.text_content or ""))
        elif attachment.kind == "image":
            vision_model = await get_vision_model(db, source.workspace_id)
            text = await ocr_attachment(vision_model, attachment)
            attachment.ocr_text = text
            sections.append((attachment.id, text))
    return sections


async def run_organizing_agent(
    db,
    source: Source,
    attachments: list[Attachment],
    project: Project | None,
) -> ExtractionDraft:
    """运行 Organizing Agent 生成结构化候选草稿。"""
    sections = await build_sections(db, source, attachments)
    text_model = await get_text_model(db, source.workspace_id)
    if isinstance(text_model, TestModel):
        return _offline_draft(source, sections)

    context = _format_context(source, sections, project)
    agent = Agent(text_model, output_type=ExtractionDraft, system_prompt=SYSTEM_PROMPT, retries=1)
    result = await agent.run(context)
    if result.output is None:
        raise RuntimeError("Organizing Agent 未返回结构化结果")
    return result.output
