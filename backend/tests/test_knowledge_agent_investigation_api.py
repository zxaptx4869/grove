"""退役执行器后历史 Investigation 详情仍可读取且保持隔离。"""

import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.main import create_app
from app.models import KnowledgeAgentRun, KnowledgeInvestigation


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def register(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "username": f"history_{uuid.uuid4().hex[:10]}",
            "password": "password123",
        },
    )
    assert response.status_code == 201


async def create_run(client: httpx.AsyncClient) -> tuple[dict, dict]:
    conversation = (
        await client.post(
            "/api/knowledge-agent/conversations",
            json={"scope_type": "workspace"},
        )
    ).json()
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": f"history-{uuid.uuid4().hex[:8]}",
            "message": "历史调查问题",
        },
    )
    assert submitted.status_code == 201
    return conversation, submitted.json()["run"]


@pytest.mark.asyncio
async def test_historical_investigation_detail_remains_readable_and_isolated(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    conversation, run = await create_run(client)
    async with async_session_factory() as db:
        stored_run = await db.get(KnowledgeAgentRun, run["id"])
        assert stored_run is not None
        db.add(
            KnowledgeInvestigation(
                run_id=run["id"],
                conversation_id=conversation["id"],
                workspace_id=stored_run.workspace_id,
                owner_user_id=stored_run.owner_user_id,
                scope_type="workspace",
                objective="历史调查问题",
                requested_answer_mode="investigate",
                actual_answer_mode="investigate",
                status="completed",
                current_round=2,
                total_queries_executed=3,
                distinct_entries_found=4,
                citable_evidence_count=2,
                stop_reason="controller_complete",
                coverage_summary='["已覆盖"]',
                gaps_summary="[]",
                conflicts_summary="[]",
            )
        )
        await db.commit()

    detail = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/investigation"
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert payload["objective"] == "历史调查问题"
    assert payload["total_queries_executed"] == 3
    assert payload["coverage"] == ["已覆盖"]
    assert payload["rounds"] == []
    assert payload["queries"] == []

    await client.post("/api/auth/logout")
    await register(client)
    denied = await client.get(
        f"/api/knowledge-agent/runs/{run['id']}/investigation"
    )
    assert denied.status_code == 404
