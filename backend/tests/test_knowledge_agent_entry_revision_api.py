"""知识 Agent 单 Entry 修订 API 测试：提交、幂等、消息页、编辑、取消与隔离。"""

import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun, KnowledgeEntryRevisionDraft
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
    username = f"revision_api_{uuid.uuid4().hex[:10]}"
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


async def _completed_answer_run(
    client: httpx.AsyncClient,
    *,
    project_id: int,
    message: str = "闭水试验通常持续多久？",
    client_message_id: str | None = None,
) -> tuple[int, str]:
    """提交普通问答并运行 Worker，返回 (run_id, evidence_handle)。"""
    response = await client.post("/api/knowledge-agent/conversations", json={})
    conversation = response.json()
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


async def _revision_submit(
    client: httpx.AsyncClient,
    conversation_id: int,
    source_run_id: int,
    target_entry_id: int,
    *,
    instruction: str = "补充适用条件与验收步骤",
    client_message_id: str | None = None,
) -> httpx.Response:
    return await client.post(
        f"/api/knowledge-agent/conversations/{conversation_id}/entry-revision-drafts",
        json={
            "client_message_id": client_message_id or f"rev-{uuid.uuid4().hex[:8]}",
            "source_run_id": source_run_id,
            "target_entry_id": target_entry_id,
            "instruction": instruction,
        },
    )


@pytest.mark.asyncio
async def test_revision_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    """未登录访问修订端点返回 401。"""
    for method, path in [
        ("POST", "/api/knowledge-agent/conversations/1/entry-revision-drafts"),
        ("GET", "/api/knowledge-agent/entry-revision-drafts/1"),
        ("PATCH", "/api/knowledge-agent/entry-revision-drafts/1"),
        ("POST", "/api/knowledge-agent/entry-revision-drafts/1/cancel"),
    ]:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, (method, path)


@pytest.mark.asyncio
async def test_revision_submit_and_message_page(client: httpx.AsyncClient) -> None:
    """提交修订动作：201 创建消息/operation Run/草稿，消息页返回去重草稿。"""
    await _register(client)
    project = await _project(client, "修订项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]

    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    assert submitted.status_code == 201, submitted.text
    body = submitted.json()
    assert body["run"]["run_kind"] == "entry_revision"
    assert body["run"]["source_run_id"] == source_run_id
    assert body["run"]["target_entry_id"] == entry["id"]
    assert body["draft"]["status"] == "generating"
    assert body["draft"]["target_project_id"] == project["id"]
    assert body["draft"]["target_entry_id"] == entry["id"]
    assert "修订《" in body["user_message"]["content"]
    assert body["draft"]["changed_fields"] == []

    page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    drafts = [
        item
        for item in page["entry_revision_drafts"]
        if item["id"] == body["draft"]["id"]
    ]
    assert len(drafts) == 1
    # 既有 answer/candidate 响应兼容：普通回答不产生修订草稿集合
    assert "candidate_drafts" in page


@pytest.mark.asyncio
async def test_revision_submit_idempotent_201_then_200(client: httpx.AsyncClient) -> None:
    """相同 client_message_id 提交两次：第一次 201，第二次 200 且返回同一草稿。"""
    await _register(client)
    project = await _project(client, "修订幂等")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    payload = {
        "client_message_id": "dup-revision-1",
        "source_run_id": source_run_id,
        "target_entry_id": entry["id"],
        "instruction": "补充验收步骤",
    }
    first = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/entry-revision-drafts",
        json=payload,
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/entry-revision-drafts",
        json=payload,
    )
    assert second.status_code == 200
    assert second.json()["draft"]["id"] == first.json()["draft"]["id"]


@pytest.mark.asyncio
async def test_revision_edit_and_cancel_via_api(client: httpx.AsyncClient) -> None:
    """生成 → 编辑（含服务端 diff）→ 取消；取消后不可再编辑。"""
    await _register(client)
    project = await _project(client, "修订编辑")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    draft_id = submitted.json()["draft"]["id"]
    async with async_session_factory() as db:
        draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
        assert draft is not None
        draft.status = "draft"
        draft.title = "候选标题"
        draft.content = "候选内容"
        draft.main_type = "method"
        await db.commit()

    edited = await client.patch(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}",
        json={
            "title": "闭水试验验收要点（编辑后）",
            "content": "闭水试验应持续观察水位与楼下顶面。",
            "applicable_condition": "仅南方潮湿地区",
            "change_summary": "按用户要求改写",
        },
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["title"] == "闭水试验验收要点（编辑后）"
    fields = {item["field"]: item for item in body["changed_fields"]}
    assert fields["title"]["after"] == "闭水试验验收要点（编辑后）"
    assert fields["applicable_condition"]["after"] == "仅南方潮湿地区"
    assert "target_entry_id" not in body or body["target_entry_id"] == entry["id"]

    cancelled = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/cancel"
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    after_cancel = await client.patch(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}",
        json={"title": "不应生效"},
    )
    assert after_cancel.status_code == 409


@pytest.mark.asyncio
async def test_revision_cross_user_404(client: httpx.AsyncClient) -> None:
    """其他用户无法读取/编辑修订草稿（404，不暴露存在性）。"""
    await _register(client)
    project = await _project(client, "修订隔离")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    draft_id = submitted.json()["draft"]["id"]

    await _register(client)  # 第二个用户
    response = await client.get(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}"
    )
    assert response.status_code == 404
    patch = await client.patch(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}",
        json={"title": "越权修改"},
    )
    assert patch.status_code == 404


@pytest.mark.asyncio
async def test_revision_rejects_empty_instruction_via_api(client: httpx.AsyncClient) -> None:
    """空指令由 API 校验拒绝（422），不创建草稿。"""
    await _register(client)
    project = await _project(client, "修订空指令")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    response = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
        instruction="   ",
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_revision_confirm_via_api(client: httpx.AsyncClient) -> None:
    """确认接口原子更新正式 Entry，返回 applied 回执；重复确认返回同一 Execution。"""
    await _register(client)
    project = await _project(client, "修订确认")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    draft_id = submitted.json()["draft"]["id"]
    async with async_session_factory() as db:
        draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
        assert draft is not None
        draft.status = "draft"
        draft.title = "闭水试验验收要点（确认后）"
        draft.content = "闭水试验应持续观察水位与楼下顶面，并按材料说明确认时长。"
        draft.main_type = "method"
        draft.info_nature = "advice"
        draft.change_summary = "补充观察要求与材料口径"
        import json as _json

        # 采用允许集合内的真实句柄
        allowed = _json.loads(draft.allowed_evidence_handles_json or "[]")
        assert allowed
        draft.selected_evidence_handles_json = _json.dumps([allowed[0]])
        await db.commit()

    op_key = f"confirm-{uuid.uuid4().hex[:8]}"
    confirmed = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/confirm",
        json={"client_operation_id": op_key},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["draft"]["status"] == "applied"
    assert body["execution"]["status"] == "applied"
    assert body["execution"]["after_version_number"] >= 2
    assert body["entry"]["id"] == entry["id"]
    assert body["entry"]["title"] == "闭水试验验收要点（确认后）"
    assert body["draft"]["changed_fields"]

    replay = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/confirm",
        json={"client_operation_id": op_key},
    )
    assert replay.status_code == 200
    assert replay.json()["execution"]["id"] == body["execution"]["id"]


@pytest.mark.asyncio
async def test_revision_undo_via_api_and_cross_user_404(client: httpx.AsyncClient) -> None:
    """撤销接口恢复 before 快照；其他用户撤销同一草稿返回 404。"""
    await _register(client)
    project = await _project(client, "修订撤销")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    draft_id = submitted.json()["draft"]["id"]
    async with async_session_factory() as db:
        draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
        assert draft is not None
        draft.status = "draft"
        draft.title = "确认后的标题"
        draft.content = "确认后的内容。"
        draft.main_type = "method"
        draft.change_summary = "修改标题与内容"
        import json as _json

        allowed = _json.loads(draft.allowed_evidence_handles_json or "[]")
        draft.selected_evidence_handles_json = _json.dumps([allowed[0]])
        await db.commit()

    op_key = f"confirm-{uuid.uuid4().hex[:8]}"
    confirmed = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/confirm",
        json={"client_operation_id": op_key},
    )
    assert confirmed.status_code == 200
    applied_title = confirmed.json()["entry"]["title"]
    assert applied_title == "确认后的标题"

    undo_key = f"undo-{uuid.uuid4().hex[:8]}"
    undone = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/undo",
        json={"client_operation_id": undo_key},
    )
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert body["draft"]["status"] == "undone"
    assert body["execution"]["status"] == "undone"
    assert body["entry"]["title"] == "闭水试验通常持续 24 小时"

    replay = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/undo",
        json={"client_operation_id": undo_key},
    )
    assert replay.status_code == 200
    assert replay.json()["execution"]["id"] == body["execution"]["id"]

    await _register(client)  # 第二个用户
    cross = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/undo",
        json={"client_operation_id": f"undo-{uuid.uuid4().hex[:8]}"},
    )
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_revision_undo_rejected_after_later_edit_via_api(
    client: httpx.AsyncClient,
) -> None:
    """Entry 被后续编辑后撤销返回 409，回执保持 applied。"""
    await _register(client)
    project = await _project(client, "撤销冲突")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_run_id, _handle = await _completed_answer_run(client, project_id=project["id"])
    conversation = (await client.get("/api/knowledge-agent/conversations")).json()[0]
    submitted = await _revision_submit(
        client,
        conversation["id"],
        source_run_id,
        entry["id"],
    )
    draft_id = submitted.json()["draft"]["id"]
    async with async_session_factory() as db:
        draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
        assert draft is not None
        draft.status = "draft"
        draft.title = "确认后的标题"
        draft.content = "确认后的内容。"
        draft.main_type = "method"
        draft.change_summary = "修改标题与内容"
        import json as _json

        allowed = _json.loads(draft.allowed_evidence_handles_json or "[]")
        draft.selected_evidence_handles_json = _json.dumps([allowed[0]])
        await db.commit()

    confirmed = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/confirm",
        json={"client_operation_id": f"confirm-{uuid.uuid4().hex[:8]}"},
    )
    assert confirmed.status_code == 200
    # 后续人工编辑 Entry
    edit = await client.patch(f"/api/entries/{entry['id']}", json={"title": "后续编辑标题"})
    assert edit.status_code == 200, edit.text

    undone = await client.post(
        f"/api/knowledge-agent/entry-revision-drafts/{draft_id}/undo",
        json={"client_operation_id": f"undo-{uuid.uuid4().hex[:8]}"},
    )
    assert undone.status_code == 409
    assert "知识后来发生了变化" in undone.text
    draft = (await client.get(f"/api/knowledge-agent/entry-revision-drafts/{draft_id}")).json()
    assert draft["status"] == "applied"
