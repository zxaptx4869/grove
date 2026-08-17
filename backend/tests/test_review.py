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


async def _set_candidate(candidate_id: int, **fields) -> None:
    """直接修改候选字段，用于构造精审/无节点等测试数据。"""
    async with async_session_factory() as session:
        candidate = await session.get(Candidate, candidate_id)
        assert candidate is not None
        for key, value in fields.items():
            setattr(candidate, key, value)
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


@pytest.mark.asyncio
async def test_list_review_candidates_splits_quick_and_detailed(
    client: httpx.AsyncClient,
) -> None:
    """批量候选列表应标记快审与精审，并带来源信息。"""
    await _register(client)
    project = await _create_project(client)
    await client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "求职", "parent_id": None},
    )
    first = await _create_source(client, project["id"])
    second = await _create_source(client, project["id"])
    await _process(client, first["id"])
    await _process(client, second["id"])
    first_candidate = (await _candidates(client, first["id"]))[0]
    second_candidate = (await _candidates(client, second["id"]))[0]
    await _set_candidate(second_candidate["id"], risk_flags='["高风险"]')

    response = await client.get(f"/api/projects/{project['id']}/review/candidates")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    by_id = {item["id"]: item for item in items}
    assert by_id[first_candidate["id"]]["review_band"] == "quick"
    assert by_id[first_candidate["id"]]["source_title"]
    assert by_id[second_candidate["id"]]["review_band"] == "detailed"


@pytest.mark.asyncio
async def test_list_review_candidates_workspace_isolation(
    client: httpx.AsyncClient,
) -> None:
    """跨用户不能读取项目的批量候选列表。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])

    other_transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=other_transport, base_url="http://test"
    ) as other:
        await _register(other)
        response = await other.get(f"/api/projects/{project['id']}/review/candidates")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_batch_confirm_creates_entries_with_recommended_nodes(
    client: httpx.AsyncClient,
) -> None:
    """批量确认应按候选推荐节点创建 Entry。"""
    await _register(client)
    project = await _create_project(client)
    node = (
        await client.post(
            f"/api/projects/{project['id']}/nodes",
            json={"name": "求职", "parent_id": None},
        )
    ).json()
    first = await _create_source(client, project["id"])
    second = await _create_source(client, project["id"])
    await _process(client, first["id"])
    await _process(client, second["id"])
    ids = [
        (await _candidates(client, first["id"]))[0]["id"],
        (await _candidates(client, second["id"]))[0]["id"],
    ]

    response = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={"candidate_ids": ids, "action": "confirm"},
    )

    assert response.status_code == 200
    assert {item["status"] for item in response.json()} == {"confirmed"}
    entries = (
        await client.get(f"/api/projects/{project['id']}/nodes/{node['id']}/entries")
    ).json()
    assert len(entries) == 2
    assert (await client.get(f"/api/projects/{project['id']}/review/candidates")).json() == []


@pytest.mark.asyncio
async def test_batch_confirm_with_override_node(client: httpx.AsyncClient) -> None:
    """批量确认支持统一目录节点覆盖推荐。"""
    await _register(client)
    project = await _create_project(client)
    await client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "推荐节点", "parent_id": None},
    )
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate_id = (await _candidates(client, source["id"]))[0]["id"]
    override = (
        await client.post(
            f"/api/projects/{project['id']}/nodes",
            json={"name": "统一节点", "parent_id": None},
        )
    ).json()

    response = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={
            "candidate_ids": [candidate_id],
            "action": "confirm",
            "node_id": override["id"],
        },
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "confirmed"
    entries = (
        await client.get(f"/api/projects/{project['id']}/nodes/{override['id']}/entries")
    ).json()
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_batch_confirm_partial_failure_keeps_failed(
    client: httpx.AsyncClient,
) -> None:
    """批量确认部分失败时，失败候选保持待采纳。"""
    await _register(client)
    project = await _create_project(client)
    await client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "求职", "parent_id": None},
    )
    first = await _create_source(client, project["id"])
    second = await _create_source(client, project["id"])
    await _process(client, first["id"])
    await _process(client, second["id"])
    first_candidate = (await _candidates(client, first["id"]))[0]
    second_candidate = (await _candidates(client, second["id"]))[0]
    await _set_candidate(
        second_candidate["id"],
        routing_status="no_suitable",
        recommended_node_id=None,
    )

    response = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={
            "candidate_ids": [first_candidate["id"], second_candidate["id"]],
            "action": "confirm",
        },
    )

    assert response.status_code == 200
    results = {item["candidate_id"]: item for item in response.json()}
    assert results[first_candidate["id"]]["status"] == "confirmed"
    assert results[second_candidate["id"]]["status"] == "failed"
    remaining = (
        await client.get(f"/api/projects/{project['id']}/review/candidates")
    ).json()
    assert [item["id"] for item in remaining] == [second_candidate["id"]]


@pytest.mark.asyncio
async def test_batch_reject_marks_candidates_rejected(client: httpx.AsyncClient) -> None:
    """批量拒绝应把候选改为已拒绝并从待审列表移除。"""
    await _register(client)
    project = await _create_project(client)
    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    response = await client.post(
        f"/api/projects/{project['id']}/review/candidates/batch-decision",
        json={"candidate_ids": [candidate["id"]], "action": "reject"},
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "rejected"
    assert (await client.get(f"/api/projects/{project['id']}/review/candidates")).json() == []


@pytest.mark.asyncio
async def test_batch_decision_rejects_candidates_from_other_project(
    client: httpx.AsyncClient,
) -> None:
    """批量决策不能包含其他项目的候选。"""
    await _register(client)
    first = await _create_project(client)
    second = await _create_project(client)
    first_source = await _create_source(client, first["id"])
    second_source = await _create_source(client, second["id"])
    await _process(client, first_source["id"])
    await _process(client, second_source["id"])
    other_candidate = (await _candidates(client, second_source["id"]))[0]

    response = await client.post(
        f"/api/projects/{first['id']}/review/candidates/batch-decision",
        json={"candidate_ids": [other_candidate["id"]], "action": "reject"},
    )

    assert response.status_code == 400
