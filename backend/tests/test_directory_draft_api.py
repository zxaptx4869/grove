"""Directory Draft 起草 API 测试。"""

import uuid

import httpx
import pytest

from app.main import create_app


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
    response = await client.post("/api/projects", json={"name": "新房装修"})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_create_draft_returns_clarify_questions(client) -> None:
    await _register(client)
    project = await _create_project(client)

    response = await client.post(f"/api/projects/{project['id']}/directory-draft", json={})

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "awaiting_input"
    assert data["next_action"] == "clarify"
    assert len(data["clarify"]) == 2
    assert data["clarify"][0]["options"] == ["按阶段", "按空间", "按主题"]
    assert data["clarify"][1]["multiple"] is True
    assert data["provider"] == "offline"
    assert data["is_fallback"] is True


@pytest.mark.asyncio
async def test_submit_clarify_generates_candidate_tree(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/clarify",
        json={
            "answers": {
                "dimension": "按阶段",
                "modules": ["施工管理", "材料采购"],
            }
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_confirm"
    assert data["next_action"] == "generate"
    assert len(data["nodes"]) > 0
    assert any(item["parent_id"] is None for item in data["nodes"])


@pytest.mark.asyncio
async def test_update_draft_nodes_persists_edits(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/clarify",
        json={"answers": {"dimension": "按阶段", "modules": []}},
    )

    response = await client.patch(
        f"/api/projects/{project['id']}/directory-draft/nodes",
        json={
            "nodes": [
                {
                    "name": "我的目录",
                    "description": "用户编辑后的根节点",
                    "children": [{"name": "子节点", "description": None}],
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    names = {item["name"] for item in data["nodes"]}
    assert names == {"我的目录", "子节点"}


@pytest.mark.asyncio
async def test_apply_draft_creates_nodes_and_marks_confirmed(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/clarify",
        json={"answers": {"dimension": "按阶段", "modules": []}},
    )

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/apply"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "confirmed"
    tree = (
        await client.get(f"/api/projects/{project['id']}/tree")
    ).json()
    assert len(tree) > 0
    assert (
        await client.get(f"/api/projects/{project['id']}/directory-draft")
    ).status_code == 404


@pytest.mark.asyncio
async def test_apply_draft_rejects_non_empty_project(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await _create_node(client, project["id"], "已有节点")
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/clarify",
        json={"answers": {"dimension": "按阶段", "modules": []}},
    )

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/apply"
    )

    assert response.status_code == 400
    assert "从零起草仅适用于空目录项目" in response.json()["detail"]


@pytest.mark.asyncio
async def test_discard_draft(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/discard"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "discarded"


@pytest.mark.asyncio
async def test_draft_workspace_isolation(client) -> None:
    await _register(client)
    project = await _create_project(client)
    await client.post(f"/api/projects/{project['id']}/directory-draft", json={})

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as other:
        await _register(other)
        response = await other.get(
            f"/api/projects/{project['id']}/directory-draft"
        )
        assert response.status_code == 404
