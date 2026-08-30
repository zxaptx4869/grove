"""Run Evidence：真实原文核验、内容指纹与句柄解析。"""

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Attachment, EntrySourceEvidence, KnowledgeAgentEvidence, Node
from app.models.knowledge_agent import EVIDENCE_PURPOSE_ANSWER
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeAnswerPointOut,
    KnowledgeConflictOut,
    KnowledgeRunCitationOut,
)
from app.services.evidence_normalize import normalize_evidence_quote

logger = logging.getLogger(__name__)

_EVIDENCE_HANDLE_IN_TEXT = re.compile(
    r"[（(]\s*ev_[0-9a-f]{32}\s*[）)]|ev_[0-9a-f]{32}"
)


def _compose_answer_text(lead: str | None, points: list) -> str:
    """从 lead + 结构化要点确定性拼接回答纯文本。

    格式刻意模仿模型既有输出（`**分组**` + `- 列表`），让 Web 与历史
    展示语义保持一致；同一分组内要点不空行，分组变化与 lead 后空行分段。
    """
    lines: list[str] = []
    current_section: str | None = None
    started = False
    if lead and lead.strip():
        lines.append(lead.strip())
    for point in points:
        text = (getattr(point, "text", "") or "").strip()
        if not text:
            continue
        section = (getattr(point, "section", None) or "").strip() or None
        if section != current_section:
            if lines:
                lines.append("")
            current_section = section
            if section:
                lines.append(f"**{section}**")
        elif not started and lines:
            lines.append("")
        lines.append(f"- {text}")
        started = True
    return "\n".join(lines).strip()


def sanitize_answer_text(text: str) -> str:
    """移除模型误写入正文的 Evidence 句柄（`ev_` + 32 位十六进制）。

    句柄只应出现在结构化的 citations/conflicts 字段；模型偶尔会把句柄
    当成内联引用写进正文，展示层与后续草稿都不应看到这些标识。
    """
    return _EVIDENCE_HANDLE_IN_TEXT.sub("", text)


@dataclass
class ReferenceValidationStats:
    """最终引用校验统计：请求/有效/丢弃句柄数。"""

    requested_count: int = 0
    valid_count: int = 0
    discarded_count: int = 0


def _clean_summary(value: object) -> str:
    """规范化终态摘要文本，供可信集合匹配与去重。"""
    return " ".join(str(value).split())[:160]


def _summary_items(
    values: list[object],
    evidence_handles: set[str],
    *,
    verifiable_missing: set[str] | None = None,
) -> list[str]:
    """保留可回溯 Evidence 或匹配服务端缺失维度集合的终态摘要。"""
    result: list[str] = []
    allowed_missing = verifiable_missing or set()
    for value in values:
        summary = getattr(value, "summary", "")
        handles = set(getattr(value, "evidence_handles", []))
        text = _clean_summary(summary)
        if not handles.intersection(evidence_handles) and text not in allowed_missing:
            continue
        if text and text not in result:
            result.append(text)
        if len(result) >= 5:
            break
    return result


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
    nodes = (await db.execute(select(Node).where(Node.project_id == project_id))).scalars().all()
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
        (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == run_id,
                    KnowledgeAgentEvidence.handle.in_(unique),
                    KnowledgeAgentEvidence.is_citable.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
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
    *,
    verifiable_gaps: list[str] | None = None,
) -> tuple[KnowledgeAnswerOut, ReferenceValidationStats]:
    """把回答草稿转换为最终回答：只保留本 Run 可引用句柄，丢弃模型自由内容。

    返回 (最终回答, 引用校验统计)。事实性回答没有有效引用时降级为
    `insufficient`；部分句柄失效时保留有效引用并标记 `partial`。

    v3：模型输出 `lead` + `points` 时，逐条校验要点句柄、派生扁平 citations，
    并由服务端从 `lead` + `points` 拼接 `answer` 文本；无 `points`（旧模型/
    降级输出）沿用既有 `answer` 文本与扁平 citations 行为。
    """
    points = list(getattr(draft, "points", []) or [])
    if points:
        handles = [
            handle for point in points for handle in point.evidence_handles
        ]
    else:
        handles = [item.evidence_handle for item in draft.citations]
    handles.extend(item.evidence_handle_a for item in draft.conflicts)
    handles.extend(item.evidence_handle_b for item in draft.conflicts)
    unique_handles = list(dict.fromkeys(handles))
    resolved = await resolve_evidence_handles(db, run_id, handles)

    if points:
        valid_points: list = []
        citations: list[KnowledgeRunCitationOut] = []
        seen_citations: set[int] = set()
        for point in points:
            if not (point.text or "").strip():
                # 空正文要点与拼接语义一致：整条丢弃，不产生空展示行
                continue
            point_handles = list(
                dict.fromkeys(
                    handle for handle in point.evidence_handles if handle in resolved
                )
            )
            if not point_handles:
                # 无有效句柄的要点整条丢弃，并计入失效统计
                continue
            valid_points.append(point)
            for handle in point_handles:
                citation = _citation_out(resolved[handle])
                if citation.evidence_id not in seen_citations:
                    seen_citations.add(citation.evidence_id)
                    citations.append(citation)
    else:
        citation_handles = list(
            dict.fromkeys(item.evidence_handle for item in draft.citations)
        )
        citations = [
            _citation_out(resolved[handle])
            for handle in citation_handles
            if handle in resolved
        ]
        valid_points = []

    conflicts: list[KnowledgeConflictOut] = []
    for conflict in draft.conflicts:
        left = resolved.get(conflict.evidence_handle_a)
        right = resolved.get(conflict.evidence_handle_b)
        if left is None or right is None or left.id == right.id:
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
    output_evidence_handles = {citation.evidence_handle for citation in citations}
    output_evidence_handles.update(
        conflict.citation_a.evidence_handle
        for conflict in conflicts
        if conflict.citation_a is not None
    )
    output_evidence_handles.update(
        conflict.citation_b.evidence_handle
        for conflict in conflicts
        if conflict.citation_b is not None
    )
    coverage = _summary_items(getattr(draft, "coverage", []), output_evidence_handles)
    trusted_gaps = {
        text
        for value in (verifiable_gaps or [])
        if (text := _clean_summary(value))
    }
    gaps = _summary_items(
        getattr(draft, "gaps", []),
        output_evidence_handles,
        verifiable_missing=trusted_gaps,
    )
    core_question_answered = getattr(draft, "core_question_answered", None)
    coverage_complete = getattr(draft, "coverage_complete", None)
    assessment_missing = core_question_answered is None or coverage_complete is None
    if points and not citations:
        # 全部要点被丢弃（正文为空或句柄失效）：没有可核验内容，不得保持 completed
        status = "insufficient"
        citations = []
        conflicts = []
    elif stats.valid_count == 0:
        # 事实性回答但没有一个可引用句柄：不得保持 completed
        status = "insufficient"
        citations = []
        conflicts = []
    elif draft.insufficient or core_question_answered is False:
        # 边缘 Evidence 不能因存在零散引用伪装为有用的部分结果。
        status = "insufficient"
    elif stats.discarded_count > 0 or assessment_missing or coverage_complete is False or gaps:
        # 部分句柄失效：保留有效引用并标记 partial
        status = "partial"
    else:
        status = "completed"
    if citations and not coverage:
        entry_count = len({citation.entry_id for citation in citations})
        coverage = [f"当前回答采用 {len(citations)} 条核验证据，涉及 {entry_count} 条正式知识"]
    if coverage_complete is not True and not gaps and trusted_gaps:
        gaps = list(sorted(trusted_gaps))[:5]
    if status == "partial" and not gaps:
        gaps = ["当前 Run 的有效证据尚未完整覆盖核心问题"]
    if status == "insufficient" and not gaps:
        gaps = [draft.insufficient_note or "当前 Run 证据不足以回答核心问题"]
    if points:
        answer_text = _compose_answer_text(draft.lead, valid_points)
    else:
        answer_text = draft.answer or (draft.lead or "")
    return KnowledgeAnswerOut(
        answer=sanitize_answer_text(answer_text),
        status=status,
        insufficient_note=draft.insufficient_note
        if draft.insufficient
        else ("全部引用被丢弃，无法提供带证据的确定结论" if not citations else None),
        points=[
            KnowledgeAnswerPointOut(
                section=sanitize_answer_text(point.section) if point.section else None,
                text=sanitize_answer_text(point.text.strip()),
                citations=[
                    _citation_out(resolved[handle])
                    for handle in dict.fromkeys(point.evidence_handles)
                    if handle in resolved
                ],
            )
            for point in valid_points
        ],
        citations=citations,
        conflicts=conflicts,
        coverage=coverage,
        gaps=gaps,
    ), stats
