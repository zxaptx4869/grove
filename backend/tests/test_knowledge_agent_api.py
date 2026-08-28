"""知识 Agent API 测试：认证、隔离、409、幂等、轮询恢复、取消与 Evidence 引用。"""

import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import SCOPE_WORKSPACE
from app.services.knowledge_agent.tools import RunToolContext
from tests.test_knowledge_agent_runner import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
    _evidence_for_run,
    _fake_answer_agent,
)
from tests.test_knowledge_agent_worker import _cancel_other_waiting_runs


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def _register(client: httpx.AsyncClient) -> str:
    username = f"api_{uuid.uuid4().hex[:10]}"
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
    """通过既有采集/确认链路创建已确认 Entry（来源附件为 text_content）。"""
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


@pytest.mark.asyncio
async def test_api_requires_auth(client: httpx.AsyncClient) -> None:
    """未登录访问知识 Agent API 返回 401。"""
    for method, path in [
        ("GET", "/api/knowledge-agent/conversations"),
        ("POST", "/api/knowledge-agent/conversations"),
        ("GET", "/api/knowledge-agent/conversations/1/messages"),
        ("GET", "/api/knowledge-agent/runs/1"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 401, (method, path)


@pytest.mark.asyncio
async def test_conversation_create_list_scope_change(client: httpx.AsyncClient) -> None:
    """创建/列出对话与范围切换；范围事件进入消息历史。"""
    await _register(client)
    project = await _project(client, "API 项目")
    workspace_conv = await _conversation(client)
    assert workspace_conv["scope_type"] == "workspace"
    project_conv_response = await client.post(
        "/api/knowledge-agent/conversations",
        json={"scope_type": "project", "project_id": project["id"]},
    )
    assert project_conv_response.status_code == 201
    project_conv = project_conv_response.json()
    assert project_conv["scope_type"] == "project"
    assert project_conv["project_name"] == "API 项目"

    listed = (await client.get("/api/knowledge-agent/conversations")).json()
    assert {item["id"] for item in listed} == {workspace_conv["id"], project_conv["id"]}

    changed = await client.patch(
        f"/api/knowledge-agent/conversations/{workspace_conv['id']}/scope",
        json={"scope_type": "project", "project_id": project["id"]},
    )
    assert changed.status_code == 200
    assert changed.json()["scope_type"] == "project"
    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{workspace_conv['id']}/messages"
        )
    ).json()
    assert any(item["message_type"] == "scope_change" for item in messages["items"])


@pytest.mark.asyncio
async def test_submit_idempotent_and_polling_recovery(client: httpx.AsyncClient) -> None:
    """提交返回 waiting Run；幂等重试返回同一 Run；轮询恢复终态回答。"""
    await _register(client)
    project = await _project(client, "轮询项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    conversation = await _conversation(client)

    first = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "poll-1", "message": "闭水试验通常持续多久？"},
    )
    assert first.status_code == 201
    payload = first.json()
    assert payload["run"]["status"] == "waiting"
    assert payload["user_message"]["content"] == "闭水试验通常持续多久？"
    run_id = payload["run"]["id"]

    retry = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "poll-1", "message": "闭水试验通常持续多久？"},
    )
    assert retry.status_code == 200
    assert retry.json()["run"]["id"] == run_id

    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
    assert await process_one_run() is True
    run = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    assert run["status"] in {"completed", "partial"}
    assert run["answer"] is not None
    assert run["answer"]["answer"]
    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assistant = next(
        item for item in messages["items"] if item["role"] == "assistant"
    )
    assert assistant["content"] == run["answer"]["answer"]


@pytest.mark.asyncio
async def test_submit_active_conflict_and_cancel(client: httpx.AsyncClient) -> None:
    """活动 Run 期间新问题 409；取消后不再产生回答。"""
    await _register(client)
    conversation = await _conversation(client)
    first = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "conflict-1", "message": "第一个问题"},
    )
    assert first.status_code == 201
    run_id = first.json()["run"]["id"]

    second = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "conflict-2", "message": "第二个问题"},
    )
    assert second.status_code == 409

    cancelled = await client.post(f"/api/knowledge-agent/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["answer"] is None

    run = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    assert run["status"] == "cancelled"
    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assistant = next(
        item for item in messages["items"] if item["role"] == "assistant"
    )
    assert assistant["content"] == ""


@pytest.mark.asyncio
async def test_cross_workspace_404_isolation(client: httpx.AsyncClient) -> None:
    """其他 Workspace 的对话与 Run 一律 404，不暴露存在性。"""
    await _register(client)
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "isolate-1", "message": "隔离问题"},
    )
    run_id = submitted.json()["run"]["id"]

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await _register(other)
        assert (
            await other.get(
                f"/api/knowledge-agent/conversations/{conversation['id']}"
            )
        ).status_code == 404
        assert (
            await other.get(f"/api/knowledge-agent/runs/{run_id}")
        ).status_code == 404
        assert (
            await other.post(
                f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
                json={"client_message_id": "x", "message": "越权"},
            )
        ).status_code == 404
        assert (
            await other.post(f"/api/knowledge-agent/runs/{run_id}/cancel")
        ).status_code == 404


@pytest.mark.asyncio
async def test_structured_answer_with_verified_evidence(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """API 返回结构化回答与真实原文引用，可观测记录完整。"""
    await _register(client)
    project = await _project(client, "证据项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "evidence-1", "message": "闭水试验通常持续多久？"},
    )
    run_id = submitted.json()["run"]["id"]

    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
        run = await db.get(KnowledgeAgentRun, run_id)
        ctx = RunToolContext(
            run_id=run_id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        assert verified
        handle = verified[0].evidence_handle
        await db.commit()

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
        _fake_answer_agent(
            KnowledgeAnswerDraft(
                answer="闭水试验通常持续 24 小时。",
                citations=[KnowledgeCitationDraft(evidence_handle=handle)],
            )
        ),
    )
    assert await process_one_run() is True
    run = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    assert run["status"] == "completed"
    citations = run["answer"]["citations"]
    assert len(citations) == 1
    assert citations[0]["evidence_handle"] == handle
    assert citations[0]["entry_id"] == entry["id"]
    assert citations[0]["quote"] == "闭水试验通常持续 24 小时"

    observability = (
        await client.get(f"/api/knowledge-agent/runs/{run_id}/observability")
    ).json()
    assert observability["run_id"] == run_id
    assert {item["tool_name"] for item in observability["tool_calls"]} >= {
        "search_confirmed_knowledge",
        "read_entries",
        "read_source_evidence",
    }
    assert {item["purpose"] for item in observability["model_invocations"]} >= {
        "embedding",
        "rerank",
        "answer",
    }
    assert observability["model_invocations"][-1]["model"] == "fake-answer"


@pytest.mark.asyncio
async def test_messages_pagination_via_api(client: httpx.AsyncClient) -> None:
    """API 消息分页：游标翻页不重复不跳过。"""
    await _register(client)
    conversation = await _conversation(client)
    for index in range(3):
        response = await client.post(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
            json={
                "client_message_id": f"page-{index}",
                "message": f"第 {index + 1} 个问题",
            },
        )
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]
        assert (
            await client.post(f"/api/knowledge-agent/runs/{run_id}/cancel")
        ).status_code == 200

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(5):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (
            await client.get(
                f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
                params=params,
            )
        ).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 6
    assert len(set(seen)) == 6
