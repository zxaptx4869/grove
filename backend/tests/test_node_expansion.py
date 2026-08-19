"""节点 AI 拓展测试：生成、差异、受保护移除、应用与删除保护。"""

import uuid

import httpx
import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.main import create_app
from app.models import Entry, Node
from app.models.directory_draft import DirectoryDraft
from app.services.directory_draft import process_next_draft_step


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


@pytest.fixture(autouse=True)
async def _clean_rows():
    """每个测试前清空草稿与 Entry 表，避免残留干扰。"""
    async with async_session_factory() as db:
        await db.execute(delete(Entry))
        await db.execute(delete(DirectoryDraft))
        await db.commit()
    yield


async def _register(client: httpx.AsyncClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


async def _create_project(client: httpx.AsyncClient) -> dict:
    response = await client.post("/api/projects", json={"name": "装修项目"})
    assert response.status_code == 201
    return response.json()


async def _create_node(
    client: httpx.AsyncClient,
    project_id: int,
    name: str,
    parent_id: int | None = None,
) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": parent_id},
    )
    assert response.status_code == 201
    return response.json()


async def _create_entry(project_id: int, node_id: int, title: str) -> None:
    async with async_session_factory() as db:
        db.add(
            Entry(
                project_id=project_id,
                node_id=node_id,
                title=title,
                content="正式知识内容",
                main_type="fact",
            )
        )
        await db.commit()


async def _fetch_project_nodes(client: httpx.AsyncClient, project_id: int) -> list[dict]:
    response = await client.get(f"/api/projects/{project_id}/tree")
    assert response.status_code == 200
    return response.json()


def _flatten(nodes: list[dict]) -> list[dict]:
    result: list[dict] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node.get("children", [])))
    return result


@pytest.mark.asyncio
async def test_expand_skips_clarify_and_generates_subtree(client) -> None:
    """发起拓展跳过澄清，直接生成完整目标子树并返回差异。"""
    await _register(client)
    project = await _create_project(client)
    target = await _create_node(client, project["id"], "施工管理")

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": target["id"]},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["kind"] == "expand"
    assert data["target_node_id"] == target["id"]
    assert data["status"] == "drafting"
    assert await process_next_draft_step() is True

    data = (await client.get(f"/api/projects/{project['id']}/directory-draft")).json()
    assert data["status"] == "pending_confirm"
    assert data["next_action"] == "generate"
    assert data["provider"] == "offline"
    assert data["is_fallback"] is True
    assert len(data["nodes"]) == 9
    assert len(data["diff"]) == 3
    assert all(item["kind"] == "added" for item in data["diff"])


@pytest.mark.asyncio
async def test_expand_diff_kept_added_removed(client) -> None:
    """差异按名称识别保留/新增/建议移除，无 Entry 时可移除。"""
    await _register(client)
    project = await _create_project(client)
    target = await _create_node(client, project["id"], "施工管理")
    await _create_node(client, project["id"], "水电改造", target["id"])
    removable = await _create_node(client, project["id"], "材料采购", target["id"])
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": target["id"]},
    )
    assert await process_next_draft_step() is True

    # 把草稿树替换为“保留水电改造 + 新增墙面工程”
    response = await client.patch(
        f"/api/projects/{project['id']}/directory-draft/nodes",
        json={
            "nodes": [
                {"name": "水电改造", "description": "保留", "selected": True},
                {"name": "墙面工程", "description": "新增", "selected": True},
            ]
        },
    )
    assert response.status_code == 200
    data = (await client.get(f"/api/projects/{project['id']}/directory-draft")).json()
    kinds = {item["name"]: item["kind"] for item in data["diff"]}
    assert kinds["水电改造"] == "kept"
    assert kinds["墙面工程"] == "added"
    assert all(
        item["kind"] == "removed" and not item["blocked"]
        for item in data["diff"]
        if item["name"] != "水电改造" and item["name"] != "墙面工程"
    )
    removed = next(item for item in data["diff"] if item["kind"] == "removed")
    assert removed["real_node_id"] == removable["id"]
    assert removed["blocked"] is False


@pytest.mark.asyncio
async def test_expand_apply_creates_added_and_removes_selected(client) -> None:
    """确认应用：创建新增节点、删除勾选移除子树、保留既有节点。"""
    await _register(client)
    project = await _create_project(client)
    target = await _create_node(client, project["id"], "施工管理")
    await _create_node(client, project["id"], "水电改造", target["id"])
    removable = await _create_node(client, project["id"], "材料采购", target["id"])
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": target["id"]},
    )
    assert await process_next_draft_step() is True

    await client.patch(
        f"/api/projects/{project['id']}/directory-draft/nodes",
        json={
            "nodes": [
                {"name": "水电改造", "description": "保留", "selected": True},
                {"name": "墙面工程", "description": "新增", "selected": True},
            ]
        },
    )
    data = (await client.get(f"/api/projects/{project['id']}/directory-draft")).json()
    removed = next(item for item in data["diff"] if item["kind"] == "removed")
    assert removed["real_node_id"] == removable["id"]

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/apply",
        json={"removed_node_ids": [removed["real_node_id"]]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    tree = await _fetch_project_nodes(client, project["id"])
    flat = _flatten(tree)
    target_flat = next(item for item in flat if item["id"] == target["id"])
    child_names = [item["name"] for item in target_flat["children"]]
    assert "墙面工程" in child_names
    assert "水电改造" in child_names
    assert all(item["name"] != "材料采购" for item in flat)


@pytest.mark.asyncio
async def test_expand_blocked_removal_rolls_back(client) -> None:
    """含正式 Entry 的建议移除项提交后整批回滚。"""
    await _register(client)
    project = await _create_project(client)
    target = await _create_node(client, project["id"], "施工管理")
    protected = await _create_node(client, project["id"], "水电改造", target["id"])
    await _create_entry(project["id"], protected["id"], "闭水试验")
    await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": target["id"]},
    )
    assert await process_next_draft_step() is True

    await client.patch(
        f"/api/projects/{project['id']}/directory-draft/nodes",
        json={"nodes": [{"name": "墙面工程", "description": "新增", "selected": True}]},
    )
    data = (await client.get(f"/api/projects/{project['id']}/directory-draft")).json()
    removed = next(item for item in data["diff"] if item["kind"] == "removed")
    assert removed["blocked"] is True
    assert removed["blocker_count"] == 1

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/apply",
        json={"removed_node_ids": [removed["real_node_id"]]},
    )
    assert response.status_code == 409
    tree = await _fetch_project_nodes(client, project["id"])
    flat = _flatten(tree)
    assert any(item["id"] == protected["id"] for item in flat)
    assert all(item["name"] != "墙面工程" for item in flat)


@pytest.mark.asyncio
async def test_expand_overwrites_active_draft(client) -> None:
    """已有活跃草稿时发起新拓展复用同一草稿并重置。"""
    await _register(client)
    project = await _create_project(client)
    first = await _create_node(client, project["id"], "施工管理")
    second = await _create_node(client, project["id"], "材料采购")
    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": first["id"]},
    )
    first_draft = response.json()
    assert await process_next_draft_step() is True

    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": second["id"]},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == first_draft["id"]
    assert data["kind"] == "expand"
    assert data["target_node_id"] == second["id"]
    assert data["status"] == "drafting"
    assert data["nodes"] == []
    assert data["diff"] == []
    assert data["provider"] is None
    assert data["is_fallback"] is False


@pytest.mark.asyncio
async def test_manual_delete_protects_entries(client) -> None:
    """手动删除含正式 Entry 的节点被拒绝。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "水电改造")
    await _create_entry(project["id"], node["id"], "闭水试验")

    response = await client.delete(f"/api/projects/{project['id']}/nodes/{node['id']}")

    assert response.status_code == 409
    assert "正式知识" in response.json()["detail"]


@pytest.mark.asyncio
async def test_manual_delete_allows_empty_node(client) -> None:
    """无正式 Entry 的节点仍可正常删除。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "空节点")

    response = await client.delete(f"/api/projects/{project['id']}/nodes/{node['id']}")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_target_discards_expand_draft(client) -> None:
    """删除拓展目标节点后草稿置为已放弃。"""
    await _register(client)
    project = await _create_project(client)
    target = await _create_node(client, project["id"], "施工管理")
    response = await client.post(
        f"/api/projects/{project['id']}/directory-draft/expand",
        json={"node_id": target["id"]},
    )
    draft_id = response.json()["id"]

    response = await client.delete(f"/api/projects/{project['id']}/nodes/{target['id']}")

    assert response.status_code == 200
    async with async_session_factory() as db:
        draft = await db.get(DirectoryDraft, draft_id)
        assert draft is not None
        assert draft.status == "discarded"
        assert (
            await db.execute(
                select(Node).where(Node.id == target["id"])
            )
        ).scalar_one_or_none() is None
