"""知识 Agent API 测试：认证、隔离、409、幂等、轮询恢复、取消与 Evidence 引用。"""

import json
import uuid

import httpx
import pytest

from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import (
    CONTEXT_DECISION_CLARIFY,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.tools import RunToolContext
from app.services.knowledge_agent.working_set import (
    get_active_context_version,
)
from tests.test_knowledge_agent_runner import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
    _evidence_for_run,
    _fake_answer_agent,
    _fixed_decision,
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
async def test_scope_change_same_scope_api_noop(client: httpx.AsyncClient) -> None:
    """API 层同范围 PATCH 返回 200 且不产生 scope_change 消息。"""
    await _register(client)
    project = await _project(client, "API 同范围项目")
    conversation = await _conversation(client)
    messages_before = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()["items"]
    assert not any(
        item["message_type"] == "scope_change" for item in messages_before
    )

    same = await client.patch(
        f"/api/knowledge-agent/conversations/{conversation['id']}/scope",
        json={"scope_type": "workspace"},
    )
    assert same.status_code == 200
    assert same.json()["scope_type"] == "workspace"
    messages_after = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()["items"]
    assert not any(
        item["message_type"] == "scope_change" for item in messages_after
    )

    project_conv = await client.post(
        "/api/knowledge-agent/conversations",
        json={"scope_type": "project", "project_id": project["id"]},
    )
    assert project_conv.status_code == 201
    project_id = project_conv.json()["id"]
    same_project = await client.patch(
        f"/api/knowledge-agent/conversations/{project_id}/scope",
        json={"scope_type": "project", "project_id": project["id"]},
    )
    assert same_project.status_code == 200
    assert same_project.json()["scope_type"] == "project"
    project_messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{project_id}/messages"
        )
    ).json()["items"]
    assert not any(
        item["message_type"] == "scope_change"
        for item in project_messages
    )


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
async def test_message_page_normalizes_runs(client: httpx.AsyncClient) -> None:
    """消息页 runs 集合去重携带关联 Run，用户/助手消息通过 run_id 复用。"""
    await _register(client)
    project = await _project(client, "规范化项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "norm-1", "message": "闭水试验通常持续多久？"},
    )
    assert submitted.status_code == 201
    run_id = submitted.json()["run"]["id"]

    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
    assert await process_one_run() is True

    page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assert len(page["runs"]) == 1
    run = page["runs"][0]
    assert run["id"] == run_id
    assert run["status"] in {"completed", "partial"}
    assert run["answer"] is not None
    assert run["answer"]["answer"]
    items = page["items"]
    user_message = next(item for item in items if item["role"] == "user")
    assistant_message = next(item for item in items if item["role"] == "assistant")
    assert user_message["run_id"] == run_id
    assert assistant_message["run_id"] == run_id


@pytest.mark.asyncio
async def test_submit_basis_mode_compat_and_idempotent_reuse(
    client: httpx.AsyncClient,
) -> None:
    """新客户端显式 basis_mode；旧客户端缺省按 knowledge_only；同标识重试不改模式。"""
    await _register(client)
    conversation = await _conversation(client)

    auto = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "basis-auto-1",
            "message": "什么是闭水试验？",
            "basis_mode": "auto",
        },
    )
    assert auto.status_code == 201
    auto_payload = auto.json()
    assert auto_payload["run"]["request_basis_mode"] == "auto"
    assert auto_payload["run"]["answer_basis"] is None
    assert auto_payload["user_message"]["request_basis_mode"] == "auto"
    auto_run_id = auto_payload["run"]["id"]

    # 同一 client_message_id 以不同 basis_mode 重试：返回首次 Run 与固化模式
    retry = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "basis-auto-1",
            "message": "什么是闭水试验？",
            "basis_mode": "knowledge_only",
        },
    )
    assert retry.status_code == 200
    retry_payload = retry.json()
    assert retry_payload["run"]["id"] == auto_run_id
    assert retry_payload["run"]["request_basis_mode"] == "auto"

    # 取消活动 Run 后旧客户端缺省提交：兼容为 knowledge_only
    cancelled = await client.post(f"/api/knowledge-agent/runs/{auto_run_id}/cancel")
    assert cancelled.status_code == 200
    legacy = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "basis-legacy-1",
            "message": "闭水试验通常持续多久？",
        },
    )
    assert legacy.status_code == 201
    assert legacy.json()["run"]["request_basis_mode"] == "knowledge_only"
    assert legacy.json()["run"]["request_result_mode"] == "auto"

    # Run 详情与消息页继续返回可选 basis 字段（旧 Run 无实际依据时为空）
    run = (await client.get(f"/api/knowledge-agent/runs/{auto_run_id}")).json()
    assert run["request_basis_mode"] == "auto"
    assert run["answer_basis"] is None
    page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assert "request_basis_mode" in page["items"][0]
    assert "answer_basis" in page["runs"][0]


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
                core_question_answered=True,
                coverage_complete=True,
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


@pytest.mark.asyncio
async def test_api_context_mode_default_explicit_and_idempotent(
    client: httpx.AsyncClient,
) -> None:
    """context_mode 默认 auto；显式模式被保存；幂等重试返回首次模式。"""
    await _register(client)
    conversation = await _conversation(client)

    default = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "mode-default", "message": "默认模式问题"},
    )
    assert default.status_code == 201
    assert default.json()["run"]["request_context_mode"] == "auto"
    default_run_id = default.json()["run"]["id"]
    assert (
        await client.post(f"/api/knowledge-agent/runs/{default_run_id}/cancel")
    ).status_code == 200

    explicit = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "mode-explicit",
            "message": "继续追问",
            "context_mode": "continue",
        },
    )
    assert explicit.status_code == 201
    assert explicit.json()["run"]["request_context_mode"] == "continue"
    explicit_run_id = explicit.json()["run"]["id"]

    # 幂等重试携带不同模式：返回首次创建的消息与 Run，不改写模式
    retry = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "mode-explicit",
            "message": "继续追问",
            "context_mode": "new_topic",
        },
    )
    assert retry.status_code == 200
    assert retry.json()["run"]["id"] == explicit_run_id
    assert retry.json()["run"]["request_context_mode"] == "continue"
    assert retry.json()["user_message"]["request_context_mode"] == "continue"


@pytest.mark.asyncio
async def test_api_conversation_run_and_message_context_fields(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """对话返回活动主题摘要；Run/消息返回决策、查询与工作集版本。"""
    await _register(client)
    project = await _project(client, "上下文项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    conversation = await _conversation(client)

    first = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "ctx-1",
            "message": "闭水试验通常持续多久？",
        },
    )
    first_run_id = first.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=first_run_id)
    assert await process_one_run() is True

    conv = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}"
        )
    ).json()
    assert conv["active_topic_label"] is not None
    assert conv["active_context_version_id"] is not None
    first_run = (await client.get(f"/api/knowledge-agent/runs/{first_run_id}")).json()
    assert first_run["context_decision"] in {"continue", "new_topic", "clarify"}
    assert first_run["standalone_query"]
    assert first_run["output_context_version_id"] == conv["active_context_version_id"]

    # 第二轮 continue：输入版本固化，输出新版本
    second = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "ctx-2",
            "message": "为什么不能提前放水？",
            "context_mode": "continue",
        },
    )
    second_run_id = second.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=second_run_id)
        run = await db.get(KnowledgeAgentRun, second_run_id)
        assert run.input_context_version_id == conv["active_context_version_id"]
        ctx = RunToolContext(
            run_id=second_run_id,
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

    run2 = (await client.get(f"/api/knowledge-agent/runs/{second_run_id}")).json()
    assert run2["request_context_mode"] == "continue"
    assert run2["context_decision"] == "continue"
    assert run2["standalone_query"]
    assert run2["topic_label"]
    assert run2["input_context_version_id"] == conv["active_context_version_id"]
    assert run2["output_context_version_id"] is not None
    assert run2["output_context_version_id"] != run2["input_context_version_id"]
    assert run2["answer"]["citations"][0]["entry_id"] == entry["id"]

    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    second_user_message = next(
        item
        for item in messages["items"]
        if item["client_message_id"] == "ctx-2"
    )
    assert second_user_message["request_context_mode"] == "continue"
    assert second_user_message["context_decision"] == "continue"
    assert second_user_message["input_context_version_id"] == run2[
        "input_context_version_id"
    ]
    assert second_user_message["output_context_version_id"] == run2[
        "output_context_version_id"
    ]


@pytest.mark.asyncio
async def test_api_scope_change_closes_working_set(client: httpx.AsyncClient) -> None:
    """范围切换事务关闭活动工作集；历史版本保留范围快照。"""
    await _register(client)
    project = await _project(client, "范围项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "scope-1",
            "message": "闭水试验通常持续多久？",
        },
    )
    run_id = submitted.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)
    assert await process_one_run() is True

    before = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}"
        )
    ).json()
    assert before["active_context_version_id"] is not None

    changed = await client.patch(
        f"/api/knowledge-agent/conversations/{conversation['id']}/scope",
        json={"scope_type": "project", "project_id": project["id"]},
    )
    assert changed.status_code == 200
    after = changed.json()
    assert after["active_topic_label"] is None
    assert after["active_context_version_id"] is None

    async with async_session_factory() as db:
        version = await get_active_context_version(db, conversation["id"])
        assert version is None


@pytest.mark.asyncio
async def test_api_clarification_run(client: httpx.AsyncClient, monkeypatch) -> None:
    """API 澄清分支：返回 clarification 回答且不产生输出版本。"""
    await _register(client)
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "clarify-api",
            "message": "它的验收标准是什么？",
        },
    )
    run_id = submitted.json()["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.decide_context",
        _fixed_decision(
            CONTEXT_DECISION_CLARIFY,
            "它的验收标准是什么？",
            clarify_question="你指的是哪个方案的验收标准？",
        ),
    )
    assert await process_one_run() is True
    run = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    assert run["status"] == "completed"
    assert run["context_decision"] == "clarify"
    assert run["answer"]["status"] == "clarification"
    assert run["answer"]["answer"] == "你指的是哪个方案的验收标准？"
    assert run["input_context_version_id"] is None
    assert run["output_context_version_id"] is None
    messages = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    assistant = next(
        item for item in messages["items"] if item["role"] == "assistant"
    )
    assert assistant["content"] == "你指的是哪个方案的验收标准？"


@pytest.mark.asyncio
async def test_api_projects_bounded_composite_summary_to_run_and_messages(
    client: httpx.AsyncClient,
) -> None:
    """Run 与历史消息使用同一脱敏复合快照，不返回查询或内部句柄。"""
    await _register(client)
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "composite-projection",
            "message": "解释甲醛并结合我的知识说明来源",
        },
    )
    assert submitted.status_code == 201
    run_id = submitted.json()["run"]["id"]
    plan = {
        "schema_version": "v1",
        "prompt_version": "v1",
        "requirements": [
            {
                "id": "r1",
                "order": 0,
                "summary": "解释甲醛是什么",
                "kind": "explain",
                "basis_policy": "model_allowed",
            }
        ],
        "statement_message_ids": [],
        "retrieval_requests": [
            {"id": "q1", "query": "私密检索词", "requirement_ids": ["r1"]}
        ],
        "structured_requests": [],
    }
    coverage = {
        "schema_version": "v1",
        "requirements": [
            {
                "requirement_id": "r1",
                "status": "answered",
                "evidence_handles": ["ev_" + "1" * 32],
                "result_handles": [],
                "user_message_ids": [],
                "model_knowledge_used": True,
                "note": None,
            }
        ],
    }
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run is not None
        run.composite_answer_plan_json = json.dumps(plan, ensure_ascii=False)
        run.composite_answer_coverage_json = json.dumps(coverage, ensure_ascii=False)
        await db.commit()

    run_payload = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    public_plan = run_payload["composite_answer_plan"]
    public_coverage = run_payload["composite_answer_coverage"]
    assert public_plan["input_kinds"] == ["retrieval"]
    assert "retrieval_requests" not in public_plan
    assert "prompt_version" not in public_plan
    assert public_coverage["requirements"][0]["basis_kinds"] == [
        "grove_evidence",
        "model_knowledge",
    ]
    assert "evidence_handles" not in public_coverage["requirements"][0]
    assert "私密检索词" not in json.dumps(run_payload, ensure_ascii=False)

    page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    user_message = next(item for item in page["items"] if item["role"] == "user")
    assert user_message["composite_answer_plan"] == public_plan
    assert user_message["composite_answer_coverage"] == public_coverage


@pytest.mark.asyncio
async def test_shared_graph_internal_snapshots_never_enter_public_protocol(
    client: httpx.AsyncClient,
) -> None:
    """Run 与消息页不得暴露共享图、内部查询、句柄、全文或授权参数。"""
    await _register(client)
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "shared-graph-redaction",
            "message": "公开问题",
        },
    )
    assert submitted.status_code == 201
    run_id = submitted.json()["run"]["id"]
    internal_secrets = {
        "graph": "内部图查询-不可公开",
        "entry": "Entry 全文-不可公开",
        "source": "Source 全文-不可公开",
        "authorization": "Bearer secret-token",
        "reasoning": "隐藏推理-不可公开",
        "handle": "res_internal_handle",
    }
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run is not None
        run.shared_execution_graph_json = json.dumps(internal_secrets, ensure_ascii=False)
        run.shared_execution_state_json = json.dumps(internal_secrets, ensure_ascii=False)
        run.composite_answer_execution_json = json.dumps(
            internal_secrets, ensure_ascii=False
        )
        await db.commit()

    run_payload = (await client.get(f"/api/knowledge-agent/runs/{run_id}")).json()
    message_page = (
        await client.get(
            f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
        )
    ).json()
    serialized = json.dumps(
        {"run": run_payload, "message_page": message_page}, ensure_ascii=False
    )
    assert all(secret not in serialized for secret in internal_secrets.values())
    for forbidden_key in (
        "shared_execution_graph",
        "shared_execution_state",
        "composite_answer_execution",
        "node_fingerprint",
    ):
        assert forbidden_key not in serialized


@pytest.mark.asyncio
async def test_legacy_run_without_shared_graph_fields_remains_readable(
    client: httpx.AsyncClient,
) -> None:
    """迁移前语义的 Run 没有图字段时，Run 与历史消息仍按原协议返回。"""
    await _register(client)
    conversation = await _conversation(client)
    submitted = await client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={"client_message_id": "legacy-no-graph", "message": "旧问题"},
    )
    assert submitted.status_code == 201
    run_id = submitted.json()["run"]["id"]
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        assert run is not None
        assert run.shared_execution_graph_json is None
        assert run.shared_execution_state_json is None

    run_response = await client.get(f"/api/knowledge-agent/runs/{run_id}")
    page_response = await client.get(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages"
    )
    assert run_response.status_code == 200
    assert page_response.status_code == 200
    assert run_response.json()["id"] == run_id
    assert {item["id"] for item in page_response.json()["runs"]} == {run_id}
