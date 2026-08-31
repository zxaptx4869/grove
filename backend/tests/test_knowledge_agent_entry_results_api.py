"""结构化 Entry 结果分页 API 测试：游标、越权、历史恢复与快照稳定。"""

import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun
from app.services.knowledge_agent.entry_search import _encode_result_cursor


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def _register(client: httpx.AsyncClient) -> str:
    username = f"results_{uuid.uuid4().hex[:10]}"
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


async def _entry(
    client: httpx.AsyncClient,
    project_id: int,
    node_id: int,
    text: str,
) -> dict:
    """通过采集/确认链路创建已确认 Entry。"""
    response = await client.post(
        "/api/sources",
        data={"text": text, "project_id": str(project_id)},
    )
    assert response.status_code == 201
    source = response.json()
    await client.post(f"/api/sources/{source['id']}/process")
    from app.processing import worker

    assert await worker.process_one_task() is True
    candidates = (await client.get(f"/api/sources/{source['id']}/candidates")).json()
    assert candidates
    response = await client.post(
        f"/api/candidates/{candidates[0]['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


async def _conversation(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/knowledge-agent/conversations",
        json={"scope_type": "workspace"},
    )
    assert response.status_code == 201
    return response.json()


async def _submit_entries_run(
    client: httpx.AsyncClient,
    conversation_id: int,
    message: str = "找出和闭水试验有关的知识",
) -> dict:
    response = await client.post(
        f"/api/knowledge-agent/conversations/{conversation_id}/messages",
        json={
            "client_message_id": f"results-{uuid.uuid4().hex[:10]}",
            "message": message,
            "result_mode": "entries",
        },
    )
    assert response.status_code == 201
    run = response.json()["run"]
    assert await process_one_run() is True
    polled = (await client.get(f"/api/knowledge-agent/runs/{run['id']}")).json()
    assert polled["status"] in {"completed", "partial"}
    return polled


async def _seed_entries(client: httpx.AsyncClient, count: int = 3) -> dict:
    project = await _project(client, "分页项目")
    node = await _node(client, project["id"], "施工")
    for index in range(count):
        await _entry(
            client,
            project["id"],
            node["id"],
            f"闭水试验记录{index}：基层处理、涂刷范围与闭水验收要点。",
        )
    return project


@pytest.mark.asyncio
async def test_pagination_first_and_next_pages(client: httpx.AsyncClient) -> None:
    """首屏与后续页：稳定顺序、无重复/跳过、has_more 独立于完整性。"""
    await _register(client)
    await _seed_entries(client, count=5)
    conversation = await _conversation(client)
    run = await _submit_entries_run(client, conversation["id"])

    first = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results?limit=2"
    )
    assert first.status_code == 200
    page_one = first.json()
    assert page_one["returned_count"] == 2
    assert page_one["has_more"] is True
    assert page_one["next_cursor"] is not None
    first_ids = [item["entry_id"] for item in page_one["items"]]

    second = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results"
        f"?limit=2&cursor={page_one['next_cursor']}"
    )
    assert second.status_code == 200
    page_two = second.json()
    assert page_two["returned_count"] == 2
    second_ids = [item["entry_id"] for item in page_two["items"]]
    assert set(first_ids).isdisjoint(second_ids)

    third = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results"
        f"?limit=2&cursor={page_two['next_cursor']}"
    )
    assert third.status_code == 200
    page_three = third.json()
    assert page_three["returned_count"] == 1
    assert page_three["has_more"] is False
    assert page_three["next_cursor"] is None
    all_ids = first_ids + second_ids + [page_three["items"][0]["entry_id"]]
    assert len(all_ids) == len(set(all_ids))


@pytest.mark.asyncio
async def test_pagination_does_not_rerun_search(monkeypatch, client: httpx.AsyncClient) -> None:
    """分页只读同一快照：即使搜索被禁用，历史页仍可读取。"""
    await _register(client)
    await _seed_entries(client, count=4)
    conversation = await _conversation(client)
    run = await _submit_entries_run(client, conversation["id"])
    first = (
        await client.get(
            f"/api/knowledge-agent/runs/{run['id']}/entry-results?limit=3"
        )
    ).json()
    assert first["has_more"] is True

    async def _explode_search(db, run, decision, ctx):
        raise AssertionError("分页不得重新执行搜索")

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.execute_structured_entry_search",
        _explode_search,
    )
    second = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results"
        f"?limit=3&cursor={first['next_cursor']}"
    )
    assert second.status_code == 200
    assert second.json()["returned_count"] == 1


@pytest.mark.asyncio
async def test_cursor_tampering_and_cross_run_rejected(client: httpx.AsyncClient) -> None:
    """篡改/跨 Run/越界游标返回稳定 400。"""
    await _register(client)
    await _seed_entries(client, count=3)
    conversation_a = await _conversation(client)
    conversation_b = await _conversation(client)
    run_a = await _submit_entries_run(client, conversation_a["id"], "找出和闭水试验有关的知识")
    run_b = await _submit_entries_run(client, conversation_b["id"], "找出和闭水试验有关的知识")
    async with async_session_factory() as db:
        run_row = await db.get(KnowledgeAgentRun, run_a["id"])
        workspace_id = run_row.workspace_id
        owner_user_id = run_row.owner_user_id
    page = (
        await client.get(
            f"/api/knowledge-agent/runs/{run_a['id']}/entry-results?limit=2"
        )
    ).json()
    cursor = page["next_cursor"]
    assert cursor is not None

    # 垃圾游标
    garbage = await client.get(
        f"/api/knowledge-agent/runs/{run_a['id']}/entry-results?cursor=not-a-cursor"
    )
    assert garbage.status_code == 400

    # 其他 Run 的游标
    cross_run = await client.get(
        f"/api/knowledge-agent/runs/{run_b['id']}/entry-results?cursor={cursor}"
    )
    assert cross_run.status_code == 400

    # 越界偏移（合法签名但 offset 超过快照）
    beyond = _encode_result_cursor(
        run_id=run_a["id"],
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        schema_version="v1",
        offset=999,
    )
    out_of_range = await client.get(
        f"/api/knowledge-agent/runs/{run_a['id']}/entry-results?cursor={beyond}"
    )
    assert out_of_range.status_code == 400

    # 错误 schema 版本
    wrong_schema = _encode_result_cursor(
        run_id=run_a["id"],
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        schema_version="v2",
        offset=1,
    )
    schema_mismatch = await client.get(
        f"/api/knowledge-agent/runs/{run_a['id']}/entry-results?cursor={wrong_schema}"
    )
    assert schema_mismatch.status_code == 400


@pytest.mark.asyncio
async def test_non_entries_run_and_unauth_status(client: httpx.AsyncClient) -> None:
    """非 entries Run 返回 404；未登录返回 401；端点不是 404。"""
    unauth = await client.get("/api/knowledge-agent/runs/1/entry-results")
    assert unauth.status_code == 401

    await _register(client)
    await _seed_entries(client, count=2)
    conversation = await _conversation(client)
    response = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": f"answer-{uuid.uuid4().hex[:10]}",
            "message": "闭水试验说明了什么",
            "result_mode": "answer",
        },
    )
    assert response.status_code == 201
    run = response.json()["run"]
    assert await process_one_run() is True
    polled = (await client.get(f"/api/knowledge-agent/runs/{run['id']}")).json()
    assert polled["status"] in {"completed", "partial", "failed"}
    results = await client.get(f"/api/knowledge-agent/runs/{run['id']}/entry-results")
    assert results.status_code == 404


@pytest.mark.asyncio
async def test_history_recovery_and_snapshot_immutability(
    client: httpx.AsyncClient,
) -> None:
    """消息历史恢复首屏结果；Entry 后续更新不改变历史快照。"""
    await _register(client)
    entry_rows = await _seed_entries(client, count=2)
    conversation = await _conversation(client)
    run = await _submit_entries_run(client, conversation["id"])
    snapshot_ids = [item["entry_id"] for item in run["entry_result"]["items"]]
    assert len(snapshot_ids) == 2

    # 历史消息页：Run 集合携带首屏结构化结果与实际形态
    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assert messages["runs"][0]["actual_result_mode"] == "entries"
    assert messages["runs"][0]["entry_result"] is not None
    assert messages["runs"][0]["entry_result"]["items"][0]["entry_id"] == snapshot_ids[0]

    # Entry 后续更新：历史快照保留旧 updated_at，当前详情反映新内容
    project = entry_rows
    entries = (
        await client.get(f"/api/projects/{project['id']}/entries")
    ).json()
    target = next(item for item in entries if item["id"] == snapshot_ids[0])
    updated = await client.patch(
        f"/api/entries/{target['id']}",
        json={"title": target["title"] + "（已更新）"},
    )
    assert updated.status_code == 200
    current = updated.json()
    page = (
        await client.get(
            f"/api/knowledge-agent/runs/{run['id']}/entry-results?limit=6"
        )
    ).json()
    snapshot_item = next(item for item in page["items"] if item["entry_id"] == target["id"])
    # 快照保留生成时 updated_at；当前 Entry updated_at 已前进 → 客户端可显示「已更新」
    assert snapshot_item["title"] != current["title"]
    # 同秒更新时 updated_at 可能相同，指纹可证明内容已变化
    assert snapshot_item["fingerprint"] is not None
    assert snapshot_item["fingerprint"] != current["fingerprint"]
    assert snapshot_item["updated_at"] <= current["updated_at"]


@pytest.mark.asyncio
async def test_workspace_isolation_404(client: httpx.AsyncClient) -> None:
    """其他用户/Workspace 读取结果 Run 返回 404。"""
    await _register(client)
    await _seed_entries(client, count=2)
    conversation = await _conversation(client)
    run = await _submit_entries_run(client, conversation["id"])

    # 第二个用户在自己的 Workspace 读取同一 Run
    other_name = f"other_{uuid.uuid4().hex[:10]}"
    await client.post(
        "/api/auth/register",
        json={"username": other_name, "password": "password123"},
    )
    response = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_limit_clamped_to_server_max(client: httpx.AsyncClient) -> None:
    """客户端不能放大分页上限：limit=100 按服务端最大值截断。"""
    await _register(client)
    await _seed_entries(client, count=4)
    conversation = await _conversation(client)
    run = await _submit_entries_run(client, conversation["id"])
    page = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/entry-results?limit=100"
    )
    assert page.status_code == 200
    assert page.json()["returned_count"] == 4
