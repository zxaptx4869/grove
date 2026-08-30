"""知识 Agent 候选草稿 API 测试：动作提交、编辑、取消、确认、幂等与隔离。"""

import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import SCOPE_PROJECT
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
    username = f"draft_api_{uuid.uuid4().hex[:10]}"
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


async def _conversation(
    client: httpx.AsyncClient,
    *,
    project_id: int | None = None,
) -> dict:
    payload = {"scope_type": "project", "project_id": project_id} if project_id else {}
    response = await client.post("/api/knowledge-agent/conversations", json=payload)
    assert response.status_code == 201
    return response.json()


async def _completed_answer_run(
    client: httpx.AsyncClient,
    *,
    project_id: int,
    message: str = "闭水试验通常持续多久？",
    client_message_id: str | None = None,
) -> tuple[int, str]:
    """提交普通问答并运行 Worker，返回 (run_id, evidence_handle)。"""
    conversation = await _conversation(client, project_id=project_id)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": client_message_id or f"q-{uuid.uuid4().hex[:8]}",
            "message": message,
        },
    )
    run_id = submitted.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
        run = await db.get(KnowledgeAgentRun, run_id)
        ctx = RunToolContext(
            run_id=run_id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=SCOPE_PROJECT,
            project_id=project_id,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        assert verified
        handle = verified[0].evidence_handle
        await db.commit()

    import app.services.knowledge_agent.runner as runner_module

    runner_module.run_knowledge_answer_agent = _fake_answer_agent(
        KnowledgeAnswerDraft(
            answer="闭水试验通常持续 24 小时，验收前不得放水。",
            citations=[KnowledgeCitationDraft(evidence_handle=handle)],
        )
    )
    assert await process_one_run() is True
    return run_id, handle


@pytest.mark.asyncio
async def test_draft_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    """未登录访问草稿端点返回 401。"""
    for method, path in [
        ("POST", "/api/knowledge-agent/conversations/1/drafts"),
        ("GET", "/api/knowledge-agent/drafts/1"),
        ("PATCH", "/api/knowledge-agent/drafts/1"),
        ("POST", "/api/knowledge-agent/drafts/1/cancel"),
        ("POST", "/api/knowledge-agent/drafts/1/confirm"),
    ]:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, (method, path)


@pytest.mark.asyncio
async def test_draft_action_submit_and_message_page(client: httpx.AsyncClient) -> None:
    """提交整理动作：201 创建消息/operation Run/草稿，消息页返回去重草稿。"""
    await _register(client)
    project = await _project(client, "草稿项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])

    # 项目范围对话 id 从消息页查询
    conversation = (
        await client.get("/api/knowledge-agent/conversations")
    ).json()[0]
    assert conversation["scope_type"] == "project"
    assert conversation["project_id"] == project["id"]

    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json={
            "client_message_id": f"action-{uuid.uuid4().hex[:8]}",
            "source_run_id": source_run_id,
        },
    )
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    assert body["run"]["run_kind"] == "draft_candidate"
    assert body["run"]["source_run_id"] == source_run_id
    assert body["draft"]["status"] == "generating"
    assert body["draft"]["target_project_id"] == project["id"]
    assert body["draft"]["target_project_name"] == "草稿项目"
    assert "整理成知识" in body["user_message"]["content"]

    page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    drafts = [item for item in page["candidate_drafts"] if item["id"] == body["draft"]["id"]]
    assert len(drafts) == 1


@pytest.mark.asyncio
async def test_draft_action_idempotent_201_then_200(client: httpx.AsyncClient) -> None:
    """相同 client_message_id 提交两次：第一次 201，第二次 200 且返回同一草稿。"""
    await _register(client)
    project = await _project(client, "幂等项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    payload = {
        "client_message_id": "dup-action-1",
        "source_run_id": source_run_id,
    }
    first = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json=payload,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json=payload,
    )
    assert second.status_code == 200
    assert second.json()["draft"]["id"] == first.json()["draft"]["id"]


@pytest.mark.asyncio
async def test_draft_edit_cancel_confirm_via_api(client: httpx.AsyncClient) -> None:
    """生成 → 编辑 → 确认 → 回执；相同幂等键重放返回同一 Candidate。"""
    await _register(client)
    project = await _project(client, "确认项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json={
            "client_message_id": f"action-{uuid.uuid4().hex[:8]}",
            "source_run_id": source_run_id,
        },
    )
    draft_id = submitted.json()["draft"]["id"]
    run_id = submitted.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
    # TestModel 无密钥：确定性 seed 降级生成草稿
    assert await process_one_run() is True

    draft = (await client.get(f"/api/knowledge-agent/drafts/{draft_id}")).json()
    assert draft["status"] == "draft"
    assert draft["generation_degraded"] is True
    assert draft["evidence_handles"]

    edited = await client.patch(
        f"/api/knowledge-agent/drafts/{draft_id}",
        json={"title": "闭水试验要点（编辑后）", "content": "闭水试验通常持续 24 小时。"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "闭水试验要点（编辑后）"

    op_key = f"op-{uuid.uuid4().hex[:8]}"
    confirmed = await client.post(
        f"/api/knowledge-agent/drafts/{draft_id}/confirm",
        json={"client_operation_id": op_key},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["draft"]["status"] == "confirmed"
    assert body["candidate"]["status"] == "pending"
    assert body["candidate"]["id"] == body["draft"]["confirmed_candidate_id"]
    candidate_id = body["candidate"]["id"]

    replay = await client.post(
        f"/api/knowledge-agent/drafts/{draft_id}/confirm",
        json={"client_operation_id": op_key},
    )
    assert replay.status_code == 200
    assert replay.json()["candidate"]["id"] == candidate_id

    # 确认后编辑/取消被拒绝
    conflict = await client.patch(
        f"/api/knowledge-agent/drafts/{draft_id}",
        json={"title": "不可编辑"},
    )
    assert conflict.status_code == 409
    cancelled = await client.post(f"/api/knowledge-agent/drafts/{draft_id}/cancel", json={})
    assert cancelled.status_code == 409

    # 未新增或修改正式 Entry
    entries = (
        await client.get(f"/api/projects/{project['id']}/entries", params={"node_id": node["id"]})
    ).json()
    assert [row["id"] for row in entries] == [entry["id"]]


@pytest.mark.asyncio
async def test_draft_action_cross_workspace_404(client: httpx.AsyncClient) -> None:
    """其他 Workspace 用户访问草稿一律 404。"""
    await _register(client)
    project = await _project(client, "隔离项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json={
            "client_message_id": f"action-{uuid.uuid4().hex[:8]}",
            "source_run_id": source_run_id,
        },
    )
    draft_id = submitted.json()["draft"]["id"]

    # 第二个用户（新 Workspace）
    await client.post(
        "/api/auth/register",
        json={"username": f"other_{uuid.uuid4().hex[:10]}", "password": "password123"},
    )
    # 登出当前用户并切换到新用户
    await client.post("/api/auth/logout")
    await _register(client)
    response = await client.get(f"/api/knowledge-agent/drafts/{draft_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_draft_action_active_run_409(client: httpx.AsyncClient) -> None:
    """对话存在活动 Run 时提交整理动作返回 409，不创建草稿。"""
    await _register(client)
    project = await _project(client, "冲突项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    # 制造一个活动 Run
    await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": f"q-{uuid.uuid4().hex[:8]}",
            "message": "再来一个问题",
        },
    )
    response = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
        json={
            "client_message_id": f"action-{uuid.uuid4().hex[:8]}",
            "source_run_id": source_run_id,
        },
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_old_answer_run_default_fields(client: httpx.AsyncClient) -> None:
    """旧 answer Run 响应保持 run_kind=answer 与 source_run_id=None，不缺省字段。"""
    await _register(client)
    project = await _project(client, "兼容项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    run = (await client.get(f"/api/knowledge-agent/runs/{source_run_id}")).json()
    assert run["run_kind"] == "answer"
    assert run["source_run_id"] is None
    assert run["status"] == "completed"


@pytest.mark.asyncio
async def test_message_page_draft_loading_query_count_bounded(
    client: httpx.AsyncClient,
) -> None:
    """消息页加载多个草稿时查询数量有界（批量加载，不产生逐草稿 N+1）。"""
    import sqlalchemy as sa

    from app.db.session import engine

    await _register(client)
    project = await _project(client, "查询项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    for index in range(3):
        response = await client.post(
            f"/api/knowledge-agent/conversations/{conversation['id']}/drafts",
            json={
                "client_message_id": f"multi-{index}",
                "source_run_id": source_run_id,
            },
        )
        assert response.status_code in {201, 200}
        draft_run_id = response.json()["run"]["id"]
        async with async_session_factory() as db:
            await _cancel_other_waiting_runs(db, keep_run_id=draft_run_id)
        assert await process_one_run() is True
    await client.post(f"/api/knowledge-agent/conversations/{conversation['id']}/messages")

    counts: list[int] = []

    def _count_query(conn, cursor, statement, parameters, context, executemany):
        text = str(statement)
        if "knowledge_candidate_drafts" in text or "knowledge_agent_evidences" in text:
            counts.append(1)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _count_query)
    try:
        page = (
            await client.get(
                f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
            )
        ).json()
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _count_query)
    drafts = [item for item in page["candidate_drafts"]]
    assert len(drafts) == 3
    # 批量加载：草稿集合一条查询 + Evidence 句柄一条查询，不随草稿数量线性增长
    assert len(counts) <= 4
