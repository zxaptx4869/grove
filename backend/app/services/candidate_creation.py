"""共享候选创建服务：虚拟 Source / Attachment / Extraction / pending Candidate。

只接受调用方已完成校验的参数，不自行解析客户端引用；调用方负责
Workspace、项目与引用校验。旧 Web Reader 与知识 Agent Draft 确认接口
共用本服务，不通过内部 HTTP 互相代理。

约束：
- 不创建、修改或删除正式 Entry；
- Source 归属当前 Workspace 与目标项目，保留问题、回答与来源 Run 溯源；
- Candidate 一律为 pending，进入既有确认流程后才可能成为正式知识。
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, Candidate, Extraction, Source
from app.models.extraction import (
    CANDIDATE_KIND_RECOMMENDED,
    CANDIDATE_PENDING,
    EXTRACTION_ACTIVE,
)

logger = logging.getLogger(__name__)

SOURCE_KIND_READER = "reader"
SOURCE_KIND_KNOWLEDGE_AGENT = "knowledge_agent"

_SOURCE_TITLE_PREFIX = {
    SOURCE_KIND_READER: "AI 阅读问答",
    SOURCE_KIND_KNOWLEDGE_AGENT: "知识 Agent 对话",
}


def build_knowledge_agent_attachment_text(
    *,
    question: str,
    original_answer: str,
    edited_content: str,
    source_run_id: int,
) -> str:
    """组装知识 Agent 虚拟 Source 的文本附件：原问题、原回答、编辑草稿与来源 Run。"""
    return (
        f"来源：知识 Agent 对话整理（Run #{source_run_id}）\n"
        f"问题：{question}\n"
        f"原回答：{original_answer}\n"
        f"编辑后草稿：{edited_content}"
    )


async def create_candidate_from_answer(
    db: AsyncSession,
    *,
    workspace_id: int,
    project_id: int,
    question: str,
    title: str,
    content: str,
    main_type: str | None,
    info_nature: str | None,
    evidence_refs: list[dict],
    provider: str,
    model: str,
    prompt_version: str,
    source_kind: str = SOURCE_KIND_READER,
    source_run_id: int | None = None,
    attachment_text: str | None = None,
    reason: str = "来自 AI 阅读回答",
) -> Candidate:
    """在一个事务内创建虚拟 Source/Attachment/Extraction 与 pending Candidate。

    `evidence_refs` 必须由调用方按当前可核验对象构造
    （形如 [{"attachment_id": int, "quote": str}]），本服务不校验对象存在性。
    """
    title_prefix = _SOURCE_TITLE_PREFIX.get(source_kind, SOURCE_KIND_READER)
    source_title = f"{title_prefix}：{(question or '').strip()[:40]}" or title_prefix
    source = Source(
        workspace_id=workspace_id,
        project_id=project_id,
        title=source_title[:255],
        note=question.strip(),
    )
    db.add(source)
    await db.flush()
    attachment = Attachment(
        source_id=source.id,
        kind="text",
        position=0,
        text_content=attachment_text if attachment_text is not None else content,
    )
    db.add(attachment)
    await db.flush()

    extraction = Extraction(
        source_id=source.id,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        status=EXTRACTION_ACTIVE,
        discarded_count=0,
    )
    db.add(extraction)
    await db.flush()

    candidate = Candidate(
        extraction_id=extraction.id,
        source_id=source.id,
        candidate_kind=CANDIDATE_KIND_RECOMMENDED,
        title=title,
        content=content,
        main_type=main_type or "knowledge",
        info_nature=info_nature,
        applicable_condition=None,
        note=None,
        evidence_refs=json.dumps(evidence_refs, ensure_ascii=False),
        reason=reason,
        risk_flags="[]",
        status=CANDIDATE_PENDING,
    )
    db.add(candidate)
    await db.flush()
    return candidate
