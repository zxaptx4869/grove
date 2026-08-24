"""Organizing Agent、Extraction 与 Candidate 测试。"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.agents.organizing import (
    SYSTEM_PROMPT,
    ExtractionDraft,
    _adopt_project_recommendation,
)
from app.db.session import async_session_factory
from app.main import create_app
from app.models import Extraction, Source
from app.models.extraction import EXTRACTION_ACTIVE, EXTRACTION_SUPERSEDED
from app.processing import worker
from app.processing.organizing import OrganizingProcessingProvider


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


def test_organizing_prompt_requires_project_recommendation() -> None:
    """未归属来源的项目推荐必须是必答项。"""
    assert "必须从「可选项目」" in SYSTEM_PROMPT
    assert "确实没有合适项目" in SYSTEM_PROMPT


def test_adopt_project_recommendation_keeps_candidates() -> None:
    """重试补充项目推荐时应保留首次候选，并忽略无效项目 id。"""
    draft = ExtractionDraft(source_title="标题", candidates=[])
    retry_valid = ExtractionDraft(
        source_title="重试标题",
        recommended_project_id=26,
        project_recommendation_reason="属于装修",
        candidates=[],
    )

    assert _adopt_project_recommendation(draft, retry_valid, {26}) is True
    assert draft.recommended_project_id == 26
    assert draft.project_recommendation_reason == "属于装修"
    assert draft.source_title == "标题"

    retry_invalid = ExtractionDraft(
        source_title="重试标题",
        recommended_project_id=999,
        project_recommendation_reason="无效",
        candidates=[],
    )
    assert _adopt_project_recommendation(draft, retry_invalid, {26}) is False
    assert draft.recommended_project_id == 26


async def _register(client: httpx.AsyncClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


async def _create_source(client: httpx.AsyncClient, text: str) -> dict:
    response = await client.post("/api/sources", data={"text": text})
    assert response.status_code == 201
    return response.json()


async def _process(client: httpx.AsyncClient, source_id: int) -> None:
    response = await client.post(f"/api/sources/{source_id}/process")
    assert response.status_code == 200
    assert await worker.process_one_task() is True


@pytest.mark.asyncio
async def test_process_creates_candidates(client: httpx.AsyncClient) -> None:
    """离线模式下处理应生成一条候选并可通过 API 查询。"""
    await _register(client)
    source = await _create_source(client, "闭水试验至少持续 24 小时")
    await _process(client, source["id"])

    response = await client.get(f"/api/sources/{source['id']}/candidates")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["candidate_kind"] == "recommended"
    assert data[0]["status"] == "pending"
    assert data[0]["evidence"][0]["attachment_id"] == source["attachments"][0]["id"]


@pytest.mark.asyncio
async def test_processing_updates_source_title(client: httpx.AsyncClient) -> None:
    """处理成功后 Source 标题应更新为 Agent 生成的标题。"""
    await _register(client)
    long_text = "这是很长的第一行" + "内容" * 20
    source = await _create_source(client, long_text)
    await _process(client, source["id"])

    updated = (await client.get(f"/api/sources/{source['id']}")).json()
    assert updated["title"] != source["title"]
    assert len(updated["title"]) <= 40


@pytest.mark.asyncio
async def test_retry_supersedes_old_extraction(client: httpx.AsyncClient) -> None:
    """重试成功后旧 Extraction 应变为 superseded，且不复制候选。"""
    await _register(client)
    source = await _create_source(client, "第一条知识")
    await _process(client, source["id"])

    first_response = await client.get(f"/api/sources/{source['id']}/candidates")
    first_count = len(first_response.json())
    assert first_count == 1

    async with async_session_factory() as db:
        loaded = await db.get(Source, source["id"])
        await OrganizingProcessingProvider().process(db, loaded)
        await db.commit()

    second_response = await client.get(f"/api/sources/{source['id']}/candidates")
    assert len(second_response.json()) == first_count

    async with async_session_factory() as db:
        extractions = (
            await db.execute(
                select(Extraction).where(Extraction.source_id == source["id"])
            )
        ).scalars().all()
        assert len(extractions) == 2
        assert sum(1 for item in extractions if item.status == EXTRACTION_ACTIVE) == 1
        assert sum(1 for item in extractions if item.status == EXTRACTION_SUPERSEDED) == 1


@pytest.mark.asyncio
async def test_failure_keeps_previous_candidates(client: httpx.AsyncClient, monkeypatch) -> None:
    """失败重试应保留上一份 active Extraction 及其候选。"""
    await _register(client)
    source = await _create_source(client, "原始知识")
    await _process(client, source["id"])
    before = (await client.get(f"/api/sources/{source['id']}/candidates")).json()
    assert len(before) == 1

    async def _fail(db, source, attachments, project, workspace_projects):
        raise RuntimeError("整理失败")

    monkeypatch.setattr("app.processing.organizing.run_organizing_agent", _fail)
    async with async_session_factory() as db:
        loaded = await db.get(Source, source["id"])
        with pytest.raises(RuntimeError):
            await OrganizingProcessingProvider().process(db, loaded)
        await db.commit()

    after = (await client.get(f"/api/sources/{source['id']}/candidates")).json()
    assert len(after) == 1
    assert after[0]["id"] == before[0]["id"]


@pytest.mark.asyncio
async def test_candidates_workspace_isolation(client: httpx.AsyncClient) -> None:
    """跨用户不可访问候选。"""
    await _register(client)
    source = await _create_source(client, "隔离测试")
    await _process(client, source["id"])

    other_transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=other_transport, base_url="http://test"
    ) as other:
        await _register(other)
        response = await other.get(f"/api/sources/{source['id']}/candidates")
        assert response.status_code == 404
