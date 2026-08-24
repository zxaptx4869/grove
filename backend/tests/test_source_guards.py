"""来源改归属与删除保护测试。"""

import uuid

import httpx
import pytest
from sqlalchemy import update

from app.db.session import async_session_factory
from app.main import create_app
from app.models import ProcessingTask, Source
from app.models.processing import PROCESSING
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
    response = await client.post("/api/projects", json={"name": "来源保护项目"})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _create_source(client: httpx.AsyncClient, project_id: int) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": "闭水试验至少持续 24 小时", "project_id": str(project_id)},
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


async def _archive_first(
    client: httpx.AsyncClient,
    node_id: int,
    source_id: int,
) -> dict:
    candidate = (await _candidates(client, source_id))[0]
    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_update_source_blocked_after_archive(client: httpx.AsyncClient) -> None:
    """已归档来源（有 Entry 证据）禁止改归属。"""
    await _register(client)
    project = await _create_project(client)
    other = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    await _archive_first(client, node["id"], source["id"])

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": other["id"]},
    )

    assert response.status_code == 409
    assert "正式知识引用" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_source_allowed_when_done_unconfirmed(
    client: httpx.AsyncClient,
) -> None:
    """提取完成但候选未确认的来源可以改归属。"""
    await _register(client)
    project = await _create_project(client)
    other = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": other["id"]},
    )

    assert response.status_code == 200
    assert (await client.get(f"/api/sources/{source['id']}")).json()["project_id"] == other["id"]


@pytest.mark.asyncio
async def test_update_source_blocked_when_processing(client: httpx.AsyncClient) -> None:
    """处理中的来源禁止改归属。"""
    await _register(client)
    project = await _create_project(client)
    other = await _create_project(client)
    source = await _create_source(client, project["id"])
    await client.post(f"/api/sources/{source['id']}/process")
    async with async_session_factory() as db:
        await db.execute(
            update(ProcessingTask)
            .where(ProcessingTask.source_id == source["id"])
            .values(status=PROCESSING)
        )
        await db.execute(
            update(Source).where(Source.id == source["id"]).values(status=PROCESSING)
        )
        await db.commit()

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": other["id"]},
    )

    assert response.status_code == 409
    assert "处理中" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_source_blocked_unique_evidence(
    client: httpx.AsyncClient,
) -> None:
    """作为唯一来源证据的 Source 禁止删除，并返回锁定标记。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    await _archive_first(client, node["id"], source["id"])

    query = (await client.get("/api/sources/query", params={"project_id": project["id"]})).json()
    item = next(entry for entry in query["items"] if entry["id"] == source["id"])
    assert item["project_locked"] is True
    assert item["evidence_entry_count"] == 1
    assert item["pending_candidate_count"] == 0

    response = await client.delete(f"/api/sources/{source['id']}")

    assert response.status_code == 409
    assert "正式知识引用" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_source_allowed_when_done_unconfirmed(
    client: httpx.AsyncClient,
) -> None:
    """提取完成但候选未确认的来源可以删除（连带候选）。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])

    response = await client.delete(f"/api/sources/{source['id']}")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_done_source_blocked_even_with_other_evidence(
    client: httpx.AsyncClient,
) -> None:
    """已产生正式知识的来源即使有其他证据也禁止删除。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source_a = await _create_source(client, project["id"])
    source_b = await _create_source(client, project["id"])
    await _process(client, source_a["id"])
    entry = await _archive_first(client, node["id"], source_a["id"])
    await _process(client, source_b["id"])
    candidate_b = (await _candidates(client, source_b["id"]))[0]
    added = await client.post(
        f"/api/candidates/{candidate_b['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )
    assert added.status_code == 200

    response = await client.delete(f"/api/sources/{source_a['id']}")

    assert response.status_code == 409
    assert "正式知识引用" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_source_blocked_when_processing(client: httpx.AsyncClient) -> None:
    """处理中的来源禁止删除。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await client.post(f"/api/sources/{source['id']}/process")
    async with async_session_factory() as db:
        await db.execute(
            update(ProcessingTask)
            .where(ProcessingTask.source_id == source["id"])
            .values(status=PROCESSING)
        )
        await db.execute(
            update(Source).where(Source.id == source["id"]).values(status=PROCESSING)
        )
        await db.commit()

    response = await client.delete(f"/api/sources/{source['id']}")

    assert response.status_code == 409
    assert "处理中" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_unprocessed_source_allowed(client: httpx.AsyncClient) -> None:
    """未处理的来源可直接删除。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])

    response = await client.delete(f"/api/sources/{source['id']}")

    assert response.status_code == 200
