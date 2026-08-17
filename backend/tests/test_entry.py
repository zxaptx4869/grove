"""Entry 与来源证据测试。"""

import uuid

import httpx
import pytest

from app.main import create_app
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
    response = await client.post("/api/projects", json={"name": "Entry 项目"})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _create_child_node(
    client: httpx.AsyncClient,
    project_id: int,
    parent_id: int,
    name: str,
) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": parent_id},
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
    await client.post(f"/api/sources/{source_id}/process")
    assert await worker.process_one_task() is True


async def _candidates(client: httpx.AsyncClient, source_id: int) -> list[dict]:
    response = await client.get(f"/api/sources/{source_id}/candidates")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_archive_creates_entry_and_evidence(client: httpx.AsyncClient) -> None:
    """归档候选应创建 Entry 与来源证据。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node["id"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == node["id"]
    assert data["project_id"] == project["id"]
    assert data["node_name"] == "施工"
    assert data["evidences"][0]["source_id"] == source["id"]
    assert data["evidences"][0]["source_title"]

    entries = (
        await client.get(f"/api/projects/{project['id']}/nodes/{node['id']}/entries")
    ).json()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_archive_rejects_wrong_project_node(client: httpx.AsyncClient) -> None:
    """归档时不能选择其他项目的节点。"""
    await _register(client)
    project = await _create_project(client)
    other = await _create_project(client)
    other_node = await _create_node(client, other["id"], "其他")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": other_node["id"]},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_archived_candidate_locked(client: httpx.AsyncClient) -> None:
    """归档后候选不能重新打开。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    await client.post(f"/api/candidates/{candidate['id']}/archive", json={"node_id": node["id"]})

    response = await client.post(
        f"/api/candidates/{candidate['id']}/decision",
        json={"status": "pending"},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_edit_entry(client: httpx.AsyncClient) -> None:
    """Entry 可编辑字段与移动目录。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    node2 = await _create_node(client, project["id"], "验收")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    entry = (
        await client.post(
            f"/api/candidates/{candidate['id']}/archive",
            json={"node_id": node["id"]},
        )
    ).json()

    response = await client.patch(
        f"/api/entries/{entry['id']}",
        json={"title": "新标题", "node_id": node2["id"]},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "新标题"
    assert response.json()["node_id"] == node2["id"]
    assert response.json()["node_name"] == "验收"


@pytest.mark.asyncio
async def test_list_entries_by_scope(client: httpx.AsyncClient) -> None:
    """按目录浏览应区分仅本节点与仅后代。"""
    await _register(client)
    project = await _create_project(client)
    parent = await _create_node(client, project["id"], "施工")
    child = await _create_child_node(client, project["id"], parent["id"], "水电")

    for node_id in (parent["id"], child["id"]):
        source = await _create_source(client, project["id"])
        await _process(client, source["id"])
        candidate = (await _candidates(client, source["id"]))[0]
        await client.post(
            f"/api/candidates/{candidate['id']}/archive",
            json={"node_id": node_id},
        )

    direct = (
        await client.get(
            f"/api/projects/{project['id']}/nodes/{parent['id']}/entries"
        )
    ).json()
    descendants = (
        await client.get(
            f"/api/projects/{project['id']}/nodes/{parent['id']}/entries",
            params={"scope": "descendants"},
        )
    ).json()
    child_descendants = (
        await client.get(
            f"/api/projects/{project['id']}/nodes/{child['id']}/entries",
            params={"scope": "descendants"},
        )
    ).json()

    assert [entry["node_id"] for entry in direct] == [parent["id"]]
    assert [entry["node_id"] for entry in descendants] == [child["id"]]
    assert child_descendants == []


@pytest.mark.asyncio
async def test_archive_marks_source_reviewed(client: httpx.AsyncClient) -> None:
    """采纳（归档）全部候选后，Source 应从待处理来源中消失。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node["id"]},
    )

    assert response.status_code == 200
    review_sources = (
        await client.get(f"/api/projects/{project['id']}/review/sources")
    ).json()
    assert review_sources == []
