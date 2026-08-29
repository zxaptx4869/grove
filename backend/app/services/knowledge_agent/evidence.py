"""Run Evidence：真实原文核验、内容指纹与句柄解析。"""

import hashlib
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, EntrySourceEvidence, KnowledgeAgentEvidence, Node
from app.models.knowledge_agent import EVIDENCE_PURPOSE_ANSWER
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeConflictOut,
    KnowledgeRunCitationOut,
)
from app.services.evidence_normalize import normalize_evidence_quote

logger = logging.getLogger(__name__)


@dataclass
class ReferenceValidationStats:
    """最终引用校验统计：请求/有效/丢弃句柄数。"""

    requested_count: int = 0
    valid_count: int = 0
    discarded_count: int = 0


def attachment_fingerprint(text: str) -> str:
    """计算来源文本内容的 sha256 指纹，用于识别来源是否变化。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def available_attachment_text(attachment: Attachment | None) -> str | None:
    """优先使用 Attachment 文本，其次 OCR 文本；两者都为空返回 None。"""
    if attachment is None:
        return None
    return attachment.text_content or attachment.ocr_text


@dataclass
class VerifiedQuote:
    """核验后的原文精确子串与定位信息。"""

    text: str
    start: int
    end: int


def locate_verified_quote(text: str, quote: str) -> VerifiedQuote | None:
    """在 Attachment 原文中定位候选片段，返回原文精确子串；无法核验返回 None。"""
    verified = normalize_evidence_quote(text, quote)
    if not verified:
        return None
    start = text.find(verified)
    if start < 0:
        return None
    return VerifiedQuote(text=verified, start=start, end=start + len(verified))


async def build_node_path_map(db: AsyncSession, project_id: int) -> dict[int, str]:
    """构建项目内 node_id → 目录路径（如「施工/水电」）的映射。"""
    nodes = (
        await db.execute(select(Node).where(Node.project_id == project_id))
    ).scalars().all()
    by_id = {node.id: node for node in nodes}

    def _path(node: Node) -> str:
        parts: list[str] = []
        current: Node | None = node
        seen: set[int] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            parts.append(current.name)
            current = by_id.get(current.parent_id)
        return "/".join(reversed(parts))

    return {node.id: _path(node) for node in nodes}


async def create_answer_evidence(
    db: AsyncSession,
    *,
    run_id: int,
    entry: "object",
    project_name: str | None,
    node_path: str | None,
    evidence: EntrySourceEvidence,
    attachment: Attachment | None,
    verified: VerifiedQuote,
    round_number: int | None = None,
    query_sequence: int | None = None,
) -> KnowledgeAgentEvidence:
    """创建或复用本 Run 的可引用 Evidence；同来源重复读取不重复建行。"""
    text = available_attachment_text(attachment) or ""
    fingerprint = attachment_fingerprint(text)
    existing = (
        await db.execute(
            select(KnowledgeAgentEvidence).where(
                KnowledgeAgentEvidence.run_id == run_id,
                KnowledgeAgentEvidence.entry_id == entry.id,
                KnowledgeAgentEvidence.source_id == evidence.source_id,
                KnowledgeAgentEvidence.attachment_id
                == (attachment.id if attachment is not None else None),
                KnowledgeAgentEvidence.purpose == EVIDENCE_PURPOSE_ANSWER,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = KnowledgeAgentEvidence(
        run_id=run_id,
        handle=f"ev_{uuid.uuid4().hex}",
        entry_id=entry.id,
        project_id=entry.project_id,
        source_id=evidence.source_id,
        attachment_id=attachment.id if attachment is not None else None,
        entry_title=entry.title,
        project_name=project_name,
        source_title=evidence.source.title if evidence.source else "已删除来源",
        node_path=node_path,
        quote=verified.text,
        quote_start=verified.start,
        quote_end=verified.end,
        content_fingerprint=fingerprint,
        purpose=EVIDENCE_PURPOSE_ANSWER,
        is_citable=True,
        round_number=round_number,
        query_sequence=query_sequence,
    )
    db.add(row)
    await db.flush()
    return row


async def resolve_evidence_handles(
    db: AsyncSession,
    run_id: int,
    handles: list[str],
) -> dict[str, KnowledgeAgentEvidence]:
    """解析回答模型返回的句柄：只接受本 Run 且可引用的 Evidence。"""
    unique = list(dict.fromkeys(handles))
    if not unique:
        return {}
    rows = (
        await db.execute(
            select(KnowledgeAgentEvidence).where(
                KnowledgeAgentEvidence.run_id == run_id,
                KnowledgeAgentEvidence.handle.in_(unique),
                KnowledgeAgentEvidence.is_citable.is_(True),
            )
        )
    ).scalars().all()
    return {row.handle: row for row in rows}


def _citation_out(row: KnowledgeAgentEvidence) -> KnowledgeRunCitationOut:
    """把 Evidence 行组装为最终引用（quote 来自服务端核验原文）。"""
    return KnowledgeRunCitationOut(
        evidence_id=row.id,
        evidence_handle=row.handle,
        entry_id=row.entry_id or 0,
        entry_title=row.entry_title or "已删除 Entry",
        source_id=row.source_id or 0,
        source_title=row.source_title or "已删除来源",
        attachment_id=row.attachment_id,
        quote=row.quote,
        project_id=row.project_id,
        project_name=row.project_name,
        node_path=row.node_path,
    )


async def build_validated_answer(
    db: AsyncSession,
    run_id: int,
    draft,
) -> tuple[KnowledgeAnswerOut, ReferenceValidationStats]:
    """把回答草稿转换为最终回答：只保留本 Run 可引用句柄，丢弃模型自由内容。

    返回 (最终回答, 引用校验统计)。事实性回答没有有效引用时降级为
    `insufficient`；部分句柄失效时保留有效引用并标记 `partial`。
    """
    handles = [item.evidence_handle for item in draft.citations]
    handles.extend(
        item.evidence_handle_a for item in draft.conflicts
    )
    handles.extend(
        item.evidence_handle_b for item in draft.conflicts
    )
    unique_handles = list(dict.fromkeys(handles))
    resolved = await resolve_evidence_handles(db, run_id, handles)
    citations = [
        _citation_out(resolved[item.evidence_handle])
        for item in draft.citations
        if item.evidence_handle in resolved
    ]

    conflicts: list[KnowledgeConflictOut] = []
    for conflict in draft.conflicts:
        left = resolved.get(conflict.evidence_handle_a)
        right = resolved.get(conflict.evidence_handle_b)
        if left is None or right is None:
            continue
        conflicts.append(
            KnowledgeConflictOut(
                summary=conflict.summary,
                evidence_id_a=left.id,
                entry_id_a=left.entry_id or 0,
                entry_title_a=left.entry_title or "已删除 Entry",
                evidence_id_b=right.id,
                entry_id_b=right.entry_id or 0,
                entry_title_b=right.entry_title or "已删除 Entry",
                citation_a=_citation_out(left),
                citation_b=_citation_out(right),
            )
        )

    stats = ReferenceValidationStats(
        requested_count=len(unique_handles),
        valid_count=len(resolved),
        discarded_count=len(unique_handles) - len(resolved),
    )
    if draft.insufficient:
        # 模型显式标记知识不足：允许无引用，不伪装成事实性回答
        status = "insufficient"
    elif stats.valid_count == 0:
        # 事实性回答但没有一个可引用句柄：不得保持 completed
        status = "insufficient"
        citations = []
        conflicts = []
    elif stats.discarded_count > 0:
        # 部分句柄失效：保留有效引用并标记 partial
        status = "partial"
    else:
        status = "completed"
    return KnowledgeAnswerOut(
        answer=draft.answer,
        status=status,
        insufficient_note=draft.insufficient_note
        if draft.insufficient
        else (
            "全部引用被丢弃，无法提供带证据的确定结论"
            if stats.valid_count == 0
            else None
        ),
        citations=citations,
        conflicts=conflicts,
    ), stats
