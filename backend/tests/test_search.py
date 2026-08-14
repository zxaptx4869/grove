"""关键词搜索测试。"""

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


async def _project(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _entry(client: httpx.AsyncClient, project_id: int, node_id: int, text: str) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": text, "project_id": str(project_id)},
    )
    assert response.status_code == 201
    source = response.json()
    await client.post(f"/api/sources/{source['id']}/process")
    assert await worker.process_one_task() is True
    candidates = (await client.get(f"/api/sources/{source['id']}/candidates")).json()
    assert candidates
    response = await client.post(
        f"/api/candidates/{candidates[0]['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_search_matches_title_content_directory_and_source(client: httpx.AsyncClient) -> None:
    """搜索应命中内容/标题/来源，以及目录节点名。"""
    await _register(client)
    project = await _project(client, "搜索项目")
    node = await _node(client, project["id"], "水电验收")
    await _entry(client, project["id"], node["id"], "闭水试验至少持续 24 小时")

    response = await client.get("/api/search", params={"q": "闭水试验"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["node_name"] == "水电验收"
    assert data[0]["project_name"] == "搜索项目"
    assert data[0]["evidences"][0]["source_title"]

    response = await client.get("/api/search", params={"q": "水电验收"})
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = await client.get("/api/search", params={"q": "不存在的关键词XYZ"})
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_escapes_like_wildcards(client: httpx.AsyncClient) -> None:
    """通配符应按字面匹配，不当作 SQL 通配符。"""
    await _register(client)
    project = await _project(client, "搜索项目")
    node = await _node(client, project["id"], "节点")
    await _entry(client, project["id"], node["id"], "合格率达到100%")
    await _entry(client, project["id"], node["id"], "另一条普通知识")

    response = await client.get("/api/search", params={"q": "%"})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert "100%" in response.json()[0]["content"]


@pytest.mark.asyncio
async def test_search_project_scope_and_global(client: httpx.AsyncClient) -> None:
    """项目内搜索应限定项目，全局搜索跨项目返回。"""
    await _register(client)
    first = await _project(client, "项目甲")
    first_node = await _node(client, first["id"], "节点甲")
    await _entry(client, first["id"], first_node["id"], "甲内容独有")

    second = await _project(client, "项目乙")
    second_node = await _node(client, second["id"], "节点乙")
    await _entry(client, second["id"], second_node["id"], "乙内容独有")

    scoped = (
        await client.get("/api/search", params={"q": "独有", "project_id": first["id"]})
    ).json()
    global_result = (await client.get("/api/search", params={"q": "独有"})).json()

    assert len(scoped) == 1
    assert scoped[0]["project_id"] == first["id"]
    assert len(global_result) == 2


@pytest.mark.asyncio
async def test_search_respects_workspace_isolation(client: httpx.AsyncClient) -> None:
    """全局搜索不能跨 Workspace 暴露数据。"""
    await _register(client)
    project = await _project(client, "甲的空间项目")
    node = await _node(client, project["id"], "节点")
    await _entry(client, project["id"], node["id"], "甲独有内容")

    await _register(client)
    response = await client.get("/api/search", params={"q": "甲独有内容"})
    assert response.json() == []
