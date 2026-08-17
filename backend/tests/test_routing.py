"""项目与目录推荐（路由）测试。"""

import uuid

import httpx
import pytest

from app.agents.organizing import ExtractionDraft, NodeRecommendationDraft, RoutingDraft
from app.db.session import async_session_factory
from app.main import create_app
from app.models import Source
from app.processing import worker
from app.processing.organizing import OrganizingProcessingProvider


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


async def _source(
    client: httpx.AsyncClient,
    text: str,
    project_id: int | None = None,
) -> dict:
    data = {"text": text}
    if project_id is not None:
        data["project_id"] = str(project_id)
    response = await client.post("/api/sources", data=data)
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
async def test_project_internal_source_routes_after_processing(
    client: httpx.AsyncClient,
) -> None:
    """项目内来源处理成功后应立即得到目录推荐。"""
    await _register(client)
    project = await _project(client, "装修")
    node = await _node(client, project["id"], "施工")
    source = await _source(client, "闭水试验至少持续 24 小时", project["id"])

    await _process(client, source["id"])
    candidates = await _candidates(client, source["id"])

    assert len(candidates) == 1
    assert candidates[0]["recommended_node_id"] == node["id"]
    assert candidates[0]["routing_status"] == "recommended"


@pytest.mark.asyncio
async def test_global_source_routes_after_project_assignment(
    client: httpx.AsyncClient,
) -> None:
    """全局来源确认项目后应触发目录推荐。"""
    await _register(client)
    project = await _project(client, "装修")
    node = await _node(client, project["id"], "施工")
    source = await _source(client, "闭水试验至少持续 24 小时")
    await _process(client, source["id"])

    before = await _candidates(client, source["id"])
    assert before[0]["routing_status"] == "pending"
    assert before[0]["recommended_node_id"] is None

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": project["id"]},
    )
    assert response.status_code == 200

    after = await _candidates(client, source["id"])
    assert after[0]["recommended_node_id"] == node["id"]
    assert after[0]["routing_status"] == "recommended"


@pytest.mark.asyncio
async def test_reroute_on_project_change(client: httpx.AsyncClient) -> None:
    """修改来源项目后应重新计算目录推荐。"""
    await _register(client)
    first = await _project(client, "项目甲")
    first_node = await _node(client, first["id"], "节点甲")
    second = await _project(client, "项目乙")
    second_node = await _node(client, second["id"], "节点乙")
    source = await _source(client, "闭水试验至少持续 24 小时", first["id"])
    await _process(client, source["id"])

    assert (await _candidates(client, source["id"]))[0]["recommended_node_id"] == first_node["id"]

    response = await client.patch(
        f"/api/sources/{source['id']}",
        json={"project_id": second["id"]},
    )
    assert response.status_code == 200

    assert (await _candidates(client, source["id"]))[0]["recommended_node_id"] == second_node["id"]


@pytest.mark.asyncio
async def test_auto_assign_recommended_project(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """AI 推荐明确的项目应自动归属，不再要求用户确认。"""
    await _register(client)
    project = await _project(client, "装修")
    source = await _source(client, "闭水试验至少持续 24 小时")

    async def _fake_agent(db, source, attachments, project, workspace_projects):
        return ExtractionDraft(
            source_title="闭水试验",
            recommended_project_id=workspace_projects[0].id,
            project_recommendation_reason="内容与装修相关",
            candidates=[],
        )

    monkeypatch.setattr("app.processing.organizing.run_organizing_agent", _fake_agent)

    async with async_session_factory() as db:
        loaded = await db.get(Source, source["id"])
        await OrganizingProcessingProvider().process(db, loaded)
        await db.commit()

    refreshed = await client.get(f"/api/sources/{source['id']}")
    assert refreshed.status_code == 200
    assert refreshed.json()["project_id"] == project["id"]


@pytest.mark.asyncio
async def test_no_suitable_stores_new_node_suggestion(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """no_suitable 候选应保存路由 Agent 给出的新节点建议。"""
    await _register(client)
    project = await _project(client, "求职")
    await _node(client, project["id"], "装修")
    source = await _source(client, "如何识别不靠谱公司", project["id"])

    async def _fake_route(db, workspace_id, candidates, nodes):
        return RoutingDraft(
            recommendations=[
                NodeRecommendationDraft(
                    candidate_id=candidates[0].id,
                    routing_status="no_suitable",
                    new_node_name="求职经验",
                    new_node_parent_id=None,
                    new_node_reason="没有匹配目录",
                )
            ]
        )

    monkeypatch.setattr("app.services.routing.run_routing_agent", _fake_route)

    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    assert candidate["routing_status"] == "no_suitable"
    assert candidate["new_node_suggestion"]["name"] == "求职经验"
    assert candidate["new_node_suggestion"]["parent_id"] is None
    assert candidate["new_node_suggestion"]["reason"] == "没有匹配目录"


@pytest.mark.asyncio
async def test_no_suitable_rejects_invalid_new_node_parent(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """非法新节点父节点应被降级为根节点。"""
    await _register(client)
    project = await _project(client, "求职")
    await _node(client, project["id"], "装修")
    source = await _source(client, "如何识别不靠谱公司", project["id"])

    async def _fake_route(db, workspace_id, candidates, nodes):
        return RoutingDraft(
            recommendations=[
                NodeRecommendationDraft(
                    candidate_id=candidates[0].id,
                    routing_status="no_suitable",
                    new_node_name="求职经验",
                    new_node_parent_id=9999,
                    new_node_reason="没有匹配目录",
                )
            ]
        )

    monkeypatch.setattr("app.services.routing.run_routing_agent", _fake_route)

    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    assert candidate["new_node_suggestion"]["name"] == "求职经验"
    assert candidate["new_node_suggestion"]["parent_id"] is None


@pytest.mark.asyncio
async def test_empty_project_stores_new_node_suggestion(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """项目没有节点时也应调用路由 Agent 并保存新节点建议。"""
    await _register(client)
    project = await _project(client, "求职")
    source = await _source(client, "如何寻找靠谱工作", project["id"])

    async def _fake_route(db, workspace_id, candidates, nodes):
        return RoutingDraft(
            recommendations=[
                NodeRecommendationDraft(
                    candidate_id=candidates[0].id,
                    routing_status="no_suitable",
                    new_node_name="求职经验",
                    new_node_parent_id=None,
                    new_node_reason="项目还没有目录",
                )
            ]
        )

    monkeypatch.setattr("app.services.routing.run_routing_agent", _fake_route)

    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]

    assert candidate["routing_status"] == "no_suitable"
    assert candidate["new_node_suggestion"]["name"] == "求职经验"
