"""语义检索（语义搜索与相似推荐）测试。"""

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
async def test_semantic_search_ranks_results_and_falls_back(client: httpx.AsyncClient) -> None:
    """未配置密钥时语义搜索降级，并按召回分数降序返回结果。"""
    await _register(client)
    project = await _project(client, "语义项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验规范")
    await _entry(client, project["id"], node["id"], "闭水试验")

    response = await client.get("/api/semantic-search", params={"q": "闭水试验"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(item["is_fallback"] is True for item in data)
    assert all(item["reason"] == "" for item in data)
    # 完全匹配的「闭水试验」应排在「闭水试验规范」之前
    assert data[0]["title"] == "闭水试验"
    assert data[0]["project_name"] == "语义项目"

    empty = await client.get("/api/semantic-search", params={"q": "不存在的词XYZ"})
    assert empty.status_code == 200
    assert empty.json() == []


@pytest.mark.asyncio
async def test_semantic_search_project_scope_and_global(client: httpx.AsyncClient) -> None:
    """项目内语义搜索限定项目，全局语义搜索跨项目返回。"""
    await _register(client)
    first = await _project(client, "项目甲")
    first_node = await _node(client, first["id"], "节点甲")
    await _entry(client, first["id"], first_node["id"], "甲独有知识内容")

    second = await _project(client, "项目乙")
    second_node = await _node(client, second["id"], "节点乙")
    await _entry(client, second["id"], second_node["id"], "乙独有知识内容")

    scoped = (
        await client.get(
            "/api/semantic-search",
            params={"q": "独有知识", "project_id": first["id"]},
        )
    ).json()
    global_result = (
        await client.get("/api/semantic-search", params={"q": "独有知识"})
    ).json()

    assert len(scoped) == 1
    assert scoped[0]["project_id"] == first["id"]
    assert len(global_result) == 2


@pytest.mark.asyncio
async def test_semantic_search_project_not_found(client: httpx.AsyncClient) -> None:
    """语义搜索越权项目返回 404。"""
    await _register(client)
    response = await client.get(
        "/api/semantic-search",
        params={"q": "闭水试验", "project_id": 99999},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_semantic_search_respects_workspace_isolation(client: httpx.AsyncClient) -> None:
    """语义搜索不能跨 Workspace 暴露数据。"""
    await _register(client)
    project = await _project(client, "甲的空间")
    node = await _node(client, project["id"], "节点")
    await _entry(client, project["id"], node["id"], "甲独有内容")

    await _register(client)
    response = await client.get("/api/semantic-search", params={"q": "甲独有内容"})
    assert response.json() == []


@pytest.mark.asyncio
async def test_similar_entries_excludes_self_and_stays_in_project(
    client: httpx.AsyncClient,
) -> None:
    """相似推荐应排除自身，且不跨项目。"""
    await _register(client)
    project = await _project(client, "推荐项目")
    node = await _node(client, project["id"], "施工")
    first = await _entry(client, project["id"], node["id"], "闭水试验")
    second = await _entry(client, project["id"], node["id"], "闭水试验规范")

    other_project = await _project(client, "其他项目")
    other_node = await _node(client, other_project["id"], "节点")
    await _entry(client, other_project["id"], other_node["id"], "闭水试验跨项目")

    response = await client.get(f"/api/entries/{first['id']}/similar")
    assert response.status_code == 200
    data = response.json()
    assert all(item["id"] != first["id"] for item in data)
    assert all(item["project_id"] == project["id"] for item in data)
    assert any(item["id"] == second["id"] for item in data)
    assert all(item["is_fallback"] is True for item in data)


@pytest.mark.asyncio
async def test_similar_entries_entry_not_found(client: httpx.AsyncClient) -> None:
    """相似推荐对不存在的 Entry 返回 404。"""
    await _register(client)
    response = await client.get("/api/entries/99999/similar")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_similar_entries_respects_workspace_isolation(client: httpx.AsyncClient) -> None:
    """相似推荐不能跨 Workspace 访问 Entry。"""
    await _register(client)
    project = await _project(client, "甲的空间")
    node = await _node(client, project["id"], "节点")
    entry = await _entry(client, project["id"], node["id"], "甲独有内容")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other_client:
        await _register(other_client)
        response = await other_client.get(f"/api/entries/{entry['id']}/similar")
        assert response.status_code == 404
