"""证据引用规范化测试。"""

import json

import pytest
from sqlalchemy import select

from app.agents.organizing import CandidateDraft, EvidenceRefDraft, ExtractionDraft
from app.db.session import async_session_factory
from app.models import Attachment, Candidate, Source, Workspace
from app.services.evidence_normalize import (
    normalize_evidence_quote,
    split_evidence_quote_segments,
)
from app.services.extraction import save_success_extraction


def test_normalize_quote_with_symbol_differences() -> None:
    text = "☞每层层板后缩2cm，不妨碍放鞋子，但是鞋柜内空气可以流通起来"
    quote = "每层层板后缩2cm,不妨碍放鞋子但是鞋柜内空气可以流通起来"

    result = normalize_evidence_quote(text, quote)

    assert result is not None
    assert result in text
    assert "层板后缩2cm" in result


def test_normalize_quote_with_slight_rewrite() -> None:
    text = "厨房是食材处理、烹饪操作的功能区，洗菜、切配都需要清晰充足的光线"
    quote = "厨房是食材处理烹饪操作的功能区洗菜切配都需要清晰光线"

    result = normalize_evidence_quote(text, quote)

    assert result is not None
    assert result in text


def test_normalize_quote_unrelated_returns_none() -> None:
    result = normalize_evidence_quote("完全不相关的原文内容", "39800 王牌臻选套餐")
    assert result is None


def test_split_evidence_quote_segments() -> None:
    segments = split_evidence_quote_segments(
        "第一段内容…第二段内容...第三段内容",
    )
    assert segments == ["第一段内容", "第二段内容", "第三段内容"]


@pytest.mark.asyncio
async def test_save_success_extraction_normalizes_evidence() -> None:
    async with async_session_factory() as db:
        workspace = Workspace(name="规范化测试空间")
        db.add(workspace)
        await db.flush()
        source = Source(
            workspace_id=workspace.id,
            title="测试来源",
            status="done",
        )
        db.add(source)
        await db.flush()
        attachment = Attachment(
            source_id=source.id,
            kind="text",
            position=0,
            text_content="☞每层层板后缩2cm，不妨碍放鞋子；☞鞋柜底部层板打两个孔，让空气循环",
        )
        db.add(attachment)
        await db.flush()

        draft = ExtractionDraft(
            candidates=[
                CandidateDraft(
                    candidate_kind="recommended",
                    title="防臭细节",
                    content="层板后缩与底部打孔",
                    main_type="knowledge",
                    evidence=[
                        EvidenceRefDraft(
                            attachment_id=attachment.id,
                            quote="每层层板后缩2cm,不妨碍放鞋子；鞋柜底部层板打两个孔",
                        ),
                    ],
                ),
            ],
        )
        await save_success_extraction(
            db,
            source,
            draft,
            provider="demo",
            model="test",
        )
        await db.flush()

        candidate = (
            await db.execute(select(Candidate).where(Candidate.source_id == source.id))
        ).scalar_one()
        evidence = json.loads(candidate.evidence_refs or "[]")
        assert evidence
        assert "层板后缩2cm" in evidence[0]["quote"]
