"""Extraction 与 Candidate 持久化服务。"""

import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.organizing import ExtractionDraft
from app.models import Candidate, Extraction, Source
from app.models.extraction import (
    CANDIDATE_PENDING,
    EXTRACTION_ACTIVE,
    EXTRACTION_FAILED,
    EXTRACTION_SUPERSEDED,
)
from app.schemas.candidate import CandidateOut, EvidenceRefOut


def _dump_evidence(candidate_draft) -> str:
    """把候选证据引用序列化为 JSON。"""
    return json.dumps(
        [item.model_dump() for item in candidate_draft.evidence],
        ensure_ascii=False,
    )


def _dump_risk_flags(candidate_draft) -> str:
    """把风险信号序列化为 JSON。"""
    return json.dumps(list(candidate_draft.risk_flags), ensure_ascii=False)


def _parse_evidence(raw: str | None) -> list[EvidenceRefOut]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    result: list[EvidenceRefOut] = []
    for item in data:
        if isinstance(item, dict) and "attachment_id" in item:
            result.append(
                EvidenceRefOut(
                    attachment_id=int(item["attachment_id"]),
                    quote=str(item.get("quote", "")),
                )
            )
    return result


def _parse_risk_flags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _candidate_out(candidate: Candidate) -> CandidateOut:
    return CandidateOut(
        id=candidate.id,
        source_id=candidate.source_id,
        candidate_kind=candidate.candidate_kind,
        title=candidate.title,
        content=candidate.content,
        main_type=candidate.main_type,
        info_nature=candidate.info_nature,
        applicable_condition=candidate.applicable_condition,
        note=candidate.note,
        evidence=_parse_evidence(candidate.evidence_refs),
        reason=candidate.reason,
        risk_flags=_parse_risk_flags(candidate.risk_flags),
        status=candidate.status,
    )


async def save_success_extraction(
    db: AsyncSession,
    source: Source,
    draft: ExtractionDraft,
    provider: str,
    model: str,
) -> Extraction:
    """保存成功 Extraction，并把旧成功 Extraction 置为 superseded。"""
    await db.execute(
        update(Extraction)
        .where(
            Extraction.source_id == source.id,
            Extraction.status == EXTRACTION_ACTIVE,
        )
        .values(status=EXTRACTION_SUPERSEDED)
    )
    extraction = Extraction(
        source_id=source.id,
        provider=provider,
        model=model,
        prompt_version="v1",
        status=EXTRACTION_ACTIVE,
        discarded_count=draft.discarded_count,
        discarded_reason_summary=draft.discarded_reason_summary,
    )
    db.add(extraction)
    await db.flush()

    for candidate_draft in draft.candidates:
        db.add(
            Candidate(
                extraction_id=extraction.id,
                source_id=source.id,
                candidate_kind=candidate_draft.candidate_kind,
                title=candidate_draft.title,
                content=candidate_draft.content,
                main_type=candidate_draft.main_type,
                info_nature=candidate_draft.info_nature,
                applicable_condition=candidate_draft.applicable_condition,
                note=candidate_draft.note,
                evidence_refs=_dump_evidence(candidate_draft),
                reason=candidate_draft.reason,
                risk_flags=_dump_risk_flags(candidate_draft),
                status=CANDIDATE_PENDING,
            )
        )
    return extraction


async def save_failed_extraction(
    db: AsyncSession,
    source: Source,
    provider: str,
    model: str,
    error: str,
) -> Extraction:
    """保存失败 Extraction，保留上一份 active。"""
    extraction = Extraction(
        source_id=source.id,
        provider=provider,
        model=model,
        prompt_version="v1",
        status=EXTRACTION_FAILED,
        error=error,
    )
    db.add(extraction)
    await db.flush()
    return extraction


async def get_active_candidates(db: AsyncSession, source_id: int) -> list[Candidate]:
    """返回当前 active Extraction 下的候选。"""
    extraction = (
        await db.execute(
            select(Extraction).where(
                Extraction.source_id == source_id,
                Extraction.status == EXTRACTION_ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if extraction is None:
        return []
    candidates = (
        await db.execute(
            select(Candidate)
            .where(Candidate.extraction_id == extraction.id)
            .order_by(Candidate.id)
        )
    ).scalars().all()
    return list(candidates)


async def list_candidate_out(db: AsyncSession, source_id: int) -> list[CandidateOut]:
    """返回当前候选响应。"""
    return [_candidate_out(candidate) for candidate in await get_active_candidates(db, source_id)]
