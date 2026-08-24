"""行为信号记录与只读查询的测试。"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
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


async def _create_project(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _create_source(
    client: httpx.AsyncClient,
    project_id: int | None,
    text: str,
) -> dict:
    data = {"text": text}
    if project_id is not None:
        data["project_id"] = str(project_id)
    response = await client.post("/api/sources", data=data)
    assert response.status_code == 201
    return response.json()


async def _process(client: httpx.AsyncClient, source_id: int) -> None:
    from app.processing import worker

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


async def _signals(client: httpx.AsyncClient, **params) -> list[dict]:
    response = await client.get("/api/behavior-signals", params=params)
    assert response.status_code == 200
    return response.json()


async def _set_recommended_node(candidate_id: int, node_id: int | None) -> None:
    """直接更新候选的推荐节点，构造确定的接受度场景。"""
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE candidates SET recommended_node_id = :node_id WHERE id = :candidate_id"),
            {"node_id": node_id, "candidate_id": candidate_id},
        )


@pytest.mark.asyncio
async def test_archive_candidate_records_node_decision(client) -> None:
    await _register(client)
    project = await _create_project(client, "信号项目")
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"], "闭水试验通常持续 24 小时")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node["id"]},
    )
    assert response.status_code == 200

    signals = await _signals(client, signal_type="node_decision")
    assert len(signals) == 1
    signal = signals[0]
    assert signal["candidate_id"] == candidate["id"]
    assert signal["source_id"] == source["id"]
    assert signal["project_id"] == project["id"]
    assert signal["final"] == {"node_id": node["id"], "created_new_node": False}
    assert signal["user_id"] is not None


@pytest.mark.asyncio
async def test_archive_follows_recommendation_sets_accepted_true(client) -> None:
    await _register(client)
    project = await _create_project(client, "推荐接受信号")
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"], "闭水试验通常持续 24 小时")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    await _set_recommended_node(candidate["id"], node["id"])

    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node["id"]},
    )
    assert response.status_code == 200

    signal = (await _signals(client, signal_type="node_decision"))[0]
    assert signal["accepted"] is True


@pytest.mark.asyncio
async def test_batch_confirm_and_reject_record_node_decision(client) -> None:
    await _register(client)
    project = await _create_project(client, "批量信号")
    node = await _create_node(client, project["id"], "施工")
    confirm_source = await _create_source(client, project["id"], "确认知识")
    reject_source = await _create_source(client, project["id"], "拒绝知识")
    await _process(client, confirm_source["id"])
    await _process(client, reject_source["id"])
    confirm_candidate = (await _candidates(client, confirm_source["id"]))[0]
    reject_candidate = (await _candidates(client, reject_source["id"]))[0]

    confirm = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={
            "candidate_ids": [confirm_candidate["id"]],
            "action": "confirm",
            "node_id": node["id"],
        },
    )
    assert confirm.status_code == 200
    reject = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={"candidate_ids": [reject_candidate["id"]], "action": "reject"},
    )
    assert reject.status_code == 200

    signals = await _signals(client, signal_type="node_decision")
    assert len(signals) == 2
    confirmed = next(item for item in signals if item["candidate_id"] == confirm_candidate["id"])
    rejected = next(item for item in signals if item["candidate_id"] == reject_candidate["id"])
    assert confirmed["final"]["node_id"] == node["id"]
    assert confirmed["user_id"] is not None
    assert rejected["final"] == {"node_id": None, "status": "rejected"}
    # 无推荐时接受度为空；有推荐且被拒绝时为 false
    assert rejected["accepted"] is None or rejected["accepted"] is False


@pytest.mark.asyncio
async def test_batch_update_directory_records_signal(client) -> None:
    await _register(client)
    project = await _create_project(client, "批量改目录信号")
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"], "改目录知识")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-update-directory",
        json={"candidate_ids": [candidate["id"]], "node_id": node["id"]},
    )
    assert response.status_code == 200

    signal = (await _signals(client, signal_type="node_decision"))[0]
    assert signal["candidate_id"] == candidate["id"]
    assert signal["final"] == {"node_id": node["id"], "user_overridden": True}
    assert signal["user_id"] is not None


@pytest.mark.asyncio
async def test_edit_candidate_records_content_edit(client) -> None:
    await _register(client)
    project = await _create_project(client, "编辑信号")
    source = await _create_source(client, project["id"], "闭水试验通常持续 24 小时")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"content": "闭水试验至少 48 小时"},
    )
    assert response.status_code == 200

    signals = await _signals(client, signal_type="content_edit")
    assert len(signals) == 1
    signal = signals[0]
    assert signal["candidate_id"] == candidate["id"]
    assert signal["accepted"] is None
    assert signal["recommended"]["content"] == "闭水试验通常持续 24 小时"
    assert signal["final"]["content"] == "闭水试验至少 48 小时"


@pytest.mark.asyncio
async def test_update_source_records_project_decision(client) -> None:
    await _register(client)
    project_a = await _create_project(client, "甲项目")
    await _create_project(client, "乙项目")
    source = await _create_source(client, None, "未归属内容")

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": project_a["id"]},
    )
    assert response.status_code == 200

    signals = await _signals(client, signal_type="project_decision")
    assert len(signals) == 1
    signal = signals[0]
    assert signal["source_id"] == source["id"]
    assert signal["final"]["project_id"] == project_a["id"]
    assert signal["recommended"] == {"project_id": None}
    assert signal["accepted"] is None


@pytest.mark.asyncio
async def test_add_evidence_records_relation_decision(client) -> None:
    await _register(client)
    project = await _create_project(client, "关系信号")
    node = await _create_node(client, project["id"], "施工")
    first_source = await _create_source(client, project["id"], "第一条知识")
    second_source = await _create_source(client, project["id"], "第二条知识")
    await _process(client, first_source["id"])
    await _process(client, second_source["id"])
    entry = await _archive_first(client, node["id"], first_source["id"])
    candidate = (await _candidates(client, second_source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )
    assert response.status_code == 200

    signals = await _signals(client, signal_type="relation_decision")
    assert len(signals) == 1
    signal = signals[0]
    assert signal["final"] == {"action": "supplement_evidence", "entry_id": entry["id"]}
    assert signal["recommended"]["relation_status"] in {"new", "duplicate", "supplement"}


@pytest.mark.asyncio
async def test_behavior_signals_isolated_by_workspace(client) -> None:
    await _register(client)
    project = await _create_project(client, "甲项目")
    node = await _create_node(client, project["id"], "施工")
    source = await _create_source(client, project["id"], "甲的知识")
    await _process(client, source["id"])
    await _archive_first(client, node["id"], source["id"])
    assert len(await _signals(client)) >= 1

    # 新用户注册后 Cookie 切换，只能看到自己的空信号
    await _register(client)
    assert await _signals(client) == []


@pytest.mark.asyncio
async def test_delete_source_keeps_signals(client) -> None:
    await _register(client)
    project = await _create_project(client, "删除信号")
    source = await _create_source(client, project["id"], "将被删除")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    await client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"content": "改后的内容"},
    )

    response = await client.delete(f"/api/sources/{source['id']}")
    assert response.status_code == 200

    signals = await _signals(client, signal_type="content_edit")
    assert len(signals) == 1
    assert signals[0]["source_id"] is None
    assert signals[0]["candidate_id"] is None


@pytest.mark.asyncio
async def test_behavior_signals_filter_and_readonly(client) -> None:
    await _register(client)
    project = await _create_project(client, "过滤信号")
    source = await _create_source(client, project["id"], "内容")
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    await client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"content": "修改后的内容"},
    )

    filtered = await _signals(client, signal_type="content_edit", limit=10)
    assert len(filtered) == 1
    assert all(item["signal_type"] == "content_edit" for item in filtered)
    assert await _signals(client, signal_type="node_decision") == []

    # 只读：同路径无写端点
    response = await client.post("/api/behavior-signals", json={})
    assert response.status_code == 405
