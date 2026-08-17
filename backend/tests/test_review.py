"""确认台候选决策测试。"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.main import create_app
from app.models import Candidate, Extraction
from app.models.extraction import CANDIDATE_CONFIRMED
from app.processing import worker


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def _register(client: httpx.AsyncClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


async def _create_project(client: httpx.AsyncClient) -> dict:
    response = await client.post("/api/projects", json={"name": "审阅项目"})
    assert response.status_code == 201
    return response.json()


async def _create_source(client: httpx.AsyncClient, project_id: int) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": "第一条候选知识", "project_id": str(project_id)},
    )
    assert response.status_code == 201
    return response.json()


async def _process(client: httpx.AsyncClient, source_id: int) -> None:
    response = await client.post(f"/api/sources/{source_id}/process")
    assert response.status_code == 200
    assert await worker.process_one_task() is True


async def _candidates(client: httpx.AsyncClient, source_id: int) -> list[dict]:
    response = await client.get(f"/api/sources/{source_id}/candidates")
    assert response.status_code == 200
    return response.json()


async def _add_confirmed_candidate(source_id: int) -> None:
    async with async_session_factory() as session:
        extraction = (
            await session.execute(
                select(Extraction).where(Extraction.source_id == source_id)
            )
        ).scalars().first()
        assert extraction is not None
        session.add(
            Candidate(
                extraction_id=extraction.id,
                source_id=source_id,
                candidate_kind="recommended",
                title="第二条候选",
                content="第二条候选内容",
                main_type="knowledge",
                info_nature="fact",
                status=CANDIDATE_CONFIRMED,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_confirm_candidate_marks_source_reviewed(client: httpx.AsyncClient) -> None:
    """采纳全部候选后 Source 应变为已处理。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidates = await _candidates(client, source["id"])
    assert len(candidates) == 1

    response = await client.post(
        f"/api/candidates/{candidates[0]['id']}/decision",
        json={"status": "confirmed"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    review_sources = (
        await client.get(f"/api/projects/{project['id']}/review/sources")
    ).json()
    assert review_sources == []


@pytest.mark.asyncio
async def test_reopen_candidate_returns_to_pending(client: httpx.AsyncClient) -> None:
    """已采纳候选可重新打开为待采纳。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    await client.post(f"/api/candidates/{candidate['id']}/decision", json={"status": "confirmed"})
    reopened = await client.post(
        f"/api/candidates/{candidate['id']}/decision",
        json={"status": "pending"},
    )

    assert reopened.status_code == 200
    assert reopened.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_edit_candidate(client: httpx.AsyncClient) -> None:
    """编辑候选字段后应持久化。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"title": "改过的标题", "main_type": "method"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "改过的标题"
    assert response.json()["main_type"] == "method"


@pytest.mark.asyncio
async def test_batch_decision(client: httpx.AsyncClient) -> None:
    """Source 内批量拒绝应更新所选候选。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidates = await _candidates(client, source["id"])

    response = await client.post(
        f"/api/sources/{source['id']}/candidates/batch-decision",
        json={"candidate_ids": [candidates[0]["id"]], "status": "rejected"},
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_review_sources_project_scoped(client: httpx.AsyncClient) -> None:
    """确认台只返回当前项目内的待审 Source。"""
    await _register(client)
    project = await _create_project(client)
    other = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])

    own_response = await client.get(f"/api/projects/{project['id']}/review/sources")
    assert own_response.status_code == 200
    assert own_response.json()[0]["id"] == source["id"]

    response = await client.get(f"/api/projects/{other['id']}/review/sources")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_review_workspace_isolation(client: httpx.AsyncClient) -> None:
    """跨用户不能访问候选决策。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    other_transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=other_transport, base_url="http://test"
    ) as other:
        await _register(other)
        response = await other.post(
            f"/api/candidates/{candidate['id']}/decision",
            json={"status": "confirmed"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_source_counts_only_pending(client: httpx.AsyncClient) -> None:
    """待处理来源的候选数应只统计待采纳，不包含已确认候选。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    await _add_confirmed_candidate(source["id"])

    review_sources = (
        await client.get(f"/api/projects/{project['id']}/review/sources")
    ).json()

    assert len(review_sources) == 1
    assert review_sources[0]["pending_candidate_count"] == 1
