"""知识 Agent 调查 API 测试：回答模式、幂等、逐轮详情、进度、可观测性与隔离。"""

import httpx
import pytest

from app.agents.investigation import InvestigationControllerDraft
from app.db.session import async_session_factory
from app.knowledge_agent_worker import process_one_run
from app.main import create_app
from app.models import KnowledgeAgentRun
from app.models.knowledge_agent import (
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_STATUS_CANCELLED,
    INVESTIGATION_STATUS_COMPLETED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_PARTIAL,
    STOP_REASON_CONTROLLER_COMPLETE,
    STOP_REASON_NO_PROGRESS,
)
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.tools import SearchResultItem, SearchToolOutput
from tests.test_knowledge_agent_api import (
    _conversation,
    _entry,
    _node,
    _project,
    _register,
)
from tests.test_knowledge_agent_runner import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
)
from tests.test_knowledge_agent_worker import _cancel_other_waiting_runs


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as api_client:
        yield api_client


def _controller_meta() -> StageMeta:
    return StageMeta(
        purpose="investigation_controller",
        provider="llm",
        model="fake-controller",
        is_fallback=False,
        error=None,
        duration_ms=1,
    )


def _synthesis_meta() -> StageMeta:
    return StageMeta(
        purpose="synthesis",
        provider="llm",
        model="fake-synthesis",
        is_fallback=False,
        error=None,
        duration_ms=1,
    )


def _controller_sequence(plans):
    calls: list[dict] = []

    async def _fake(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        calls.append({"executed": list(executed_queries)})
        draft = plans[min(len(calls) - 1, len(plans) - 1)]
        return draft, _controller_meta()

    return _fake, calls


def _synthesis_agent():
    async def _fake(
        db,
        workspace_id,
        query,
        scope_label,
        entries,
        *,
        purpose=None,
        synthesis_context=None,
    ):
        handles = []
        for item in entries:
            for evidence in item.get("evidences", []):
                handles.append(evidence["handle"])
        return (
            KnowledgeAnswerDraft(
                answer="调查 API 综合回答。",
                citations=[
                    KnowledgeCitationDraft(evidence_handle=handle)
                    for handle in handles
                ],
            ),
            _synthesis_meta(),
        )

    return _fake


def _search_result(entry_id: int, title: str) -> SearchResultItem:
    return SearchResultItem(
        entry_id=entry_id,
        title=title,
        project_name="项目",
        node_path="",
        summary="摘要",
        source_count=1,
    )


def _scripted_search(results_by_query: dict[str, list]):
    async def _fake(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        items = results_by_query.get(query, [])
        for item in items:
            ctx.discovered_entry_ids.add(item.entry_id)
        return SearchToolOutput(items=items)

    return _fake


async def _submit(client: httpx.AsyncClient, conversation_id: int, message: str, **extra):
    payload = {
        "client_message_id": f"api-inv-{message[:8]}",
        "message": message,
        **extra,
    }
    response = await client.post(
        f"/api/knowledge-agent/conversations/{conversation_id}/messages",
        json=payload,
    )
    assert response.status_code in (200, 201)
    return response.json()


@pytest.mark.asyncio
async def test_api_answer_mode_default_and_three_modes(client: httpx.AsyncClient) -> None:
    """旧客户端缺省 auto；quick/investigate 显式固化到 Run。"""
    await _register(client)
    auto_conv = await _conversation(client)
    auto_submit = await _submit(client, auto_conv["id"], "问题A", client_message_id="mode-auto")
    assert auto_submit["run"]["request_answer_mode"] == "auto"
    quick_conv = await _conversation(client)
    quick_submit = await _submit(
        client,
        quick_conv["id"],
        "问题B",
        client_message_id="mode-quick",
        answer_mode="quick",
    )
    assert quick_submit["run"]["request_answer_mode"] == "quick"
    investigate_conv = await _conversation(client)
    investigate_submit = await _submit(
        client,
        investigate_conv["id"],
        "问题C",
        client_message_id="mode-investigate",
        answer_mode="investigate",
    )
    assert investigate_submit["run"]["request_answer_mode"] == "investigate"


@pytest.mark.asyncio
async def test_api_answer_mode_idempotent_retry_keeps_first_mode(
    client: httpx.AsyncClient,
) -> None:
    """相同 client_message_id 重试：始终返回首次请求模式与 Run，不因新载荷改变。"""
    await _register(client)
    conversation = await _conversation(client)
    first = await _submit(
        client,
        conversation["id"],
        "调查问题",
        client_message_id="mode-retry",
        answer_mode="investigate",
    )
    retry = await _submit(
        client,
        conversation["id"],
        "调查问题（重试载荷改为 quick）",
        client_message_id="mode-retry",
        answer_mode="quick",
    )
    assert retry["run"]["id"] == first["run"]["id"]
    assert retry["run"]["request_answer_mode"] == "investigate"
    assert retry["user_message"]["content"] == "调查问题"


@pytest.mark.asyncio
async def test_api_investigation_run_completes_with_detail(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """真实提交+Worker：调查完成，Run 返回摘要，逐轮详情含轮次/查询/预算。"""
    await _register(client)
    project = await _project(client, "调查 API 项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时。")
    conversation = await _conversation(client)
    submitted = await _submit(
        client,
        conversation["id"],
        "闭水试验持续多久？",
        client_message_id="api-inv-complete",
        answer_mode="investigate",
    )
    run_id = submitted["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    controller, _calls = _controller_sequence(
        [
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_SEARCH,
                queries=["闭水试验持续多久"],
                coverage=["时长"],
            ),
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_ANSWER,
                coverage=["时长"],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _scripted_search({"闭水试验持续多久": [_search_result(entry["id"], "闭水试验")]}),
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
        _synthesis_agent(),
    )
    assert await process_one_run() is True

    run_response = await client.get(f"/api/knowledge-agent/runs/{run_id}")
    assert run_response.status_code == 200
    run_data = run_response.json()
    assert run_data["status"] == RUN_COMPLETED
    assert run_data["request_answer_mode"] == "investigate"
    assert run_data["actual_answer_mode"] == "investigate"
    assert run_data["current_round"] == 2
    summary = run_data["investigation_summary"]
    assert summary["stop_reason"] == STOP_REASON_CONTROLLER_COMPLETE
    assert summary["rounds_completed"] == 2
    assert summary["queries_executed"] == 1
    assert summary["coverage"] == ["当前回答采用 1 条核验证据，涉及 1 条正式知识"]

    detail_response = await client.get(
        f"/api/knowledge-agent/runs/{run_id}/investigation"
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == INVESTIGATION_STATUS_COMPLETED
    assert detail["max_rounds"] == 3
    assert detail["max_queries_per_round"] == 3
    assert detail["max_total_queries"] == 6
    assert detail["max_entries"] == 30
    assert detail["max_evidence"] == 12
    assert len(detail["rounds"]) == 2
    assert len(detail["queries"]) == 1
    assert detail["queries"][0]["status"] == "executed"
    assert detail["rounds"][0]["controller_action"] == "search"
    assert detail["rounds"][1]["controller_action"] == "answer"


@pytest.mark.asyncio
async def test_api_investigation_detail_isolation_404(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """越权读取调查详情：其他 Workspace/用户与无调查 Run 一律 404。"""
    # 未登录 → 401
    assert (
        await client.get("/api/knowledge-agent/runs/1/investigation")
    ).status_code == 401
    await _register(client)
    project = await _project(client, "隔离项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时。")
    conversation = await _conversation(client)
    submitted = await _submit(
        client,
        conversation["id"],
        "问题",
        client_message_id="iso-inv",
        answer_mode="investigate",
    )
    run_id = submitted["run"]["id"]

    # 无调查的 quick Run → 404（使用独立对话，避免活动 Run 409）
    quick_conv = await _conversation(client)
    quick = await _submit(
        client,
        quick_conv["id"],
        "快速问题",
        client_message_id="iso-quick",
        answer_mode="quick",
    )
    quick_response = await client.get(
        f"/api/knowledge-agent/runs/{quick['run']['id']}/investigation"
    )
    assert quick_response.status_code == 404

    # 其他用户 → 404
    await _register(client)
    other_response = await client.get(
        f"/api/knowledge-agent/runs/{run_id}/investigation"
    )
    assert other_response.status_code == 404


@pytest.mark.asyncio
async def test_api_observability_records_investigation_attribution(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """可观测性接口返回路由/控制器/综合阶段与 round/query 归属。"""
    await _register(client)
    project = await _project(client, "可观测项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时。")
    conversation = await _conversation(client)
    submitted = await _submit(
        client,
        conversation["id"],
        "闭水试验？",
        client_message_id="obs-inv",
        answer_mode="investigate",
    )
    run_id = submitted["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    controller, _calls = _controller_sequence(
        [
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_SEARCH,
                queries=["闭水试验"],
            ),
            InvestigationControllerDraft(action=INVESTIGATION_ACTION_ANSWER),
        ]
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _scripted_search({"闭水试验": [_search_result(entry["id"], "闭水试验")]}),
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
        _synthesis_agent(),
    )
    assert await process_one_run() is True

    response = await client.get(f"/api/knowledge-agent/runs/{run_id}/observability")
    assert response.status_code == 200
    data = response.json()
    controller_invocations = [
        item
        for item in data["model_invocations"]
        if item["purpose"] == "investigation_controller"
    ]
    assert len(controller_invocations) == 2
    assert {item["round_number"] for item in controller_invocations} == {1, 2}
    synthesis = [
        item
        for item in data["model_invocations"]
        if item["purpose"] == "synthesis"
    ]
    assert len(synthesis) == 1
    assert synthesis[0]["model"] == "fake-synthesis"
    assert synthesis[0]["is_fallback"] is False
    search_tools = [
        item
        for item in data["tool_calls"]
        if item["tool_name"] == "search_confirmed_knowledge"
    ]
    assert len(search_tools) == 1
    assert search_tools[0]["round_number"] == 1
    assert search_tools[0]["query_sequence"] == 1
    assert search_tools[0]["investigation_id"] is not None


@pytest.mark.asyncio
async def test_api_empty_search_insufficient_and_no_fallback_misreport(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """正常空搜索：不足/partial 回答，且不把 empty 误报为模型 fallback。"""
    await _register(client)
    project = await _project(client, "空项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时。")
    conversation = await _conversation(client)
    submitted = await _submit(
        client,
        conversation["id"],
        "不存在的主题",
        client_message_id="empty-inv",
        answer_mode="investigate",
    )
    run_id = submitted["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    controller, _calls = _controller_sequence(
        [
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_SEARCH,
                queries=["不存在的主题"],
            )
        ]
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        controller,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _scripted_search({"不存在的主题": []}),
    )
    assert await process_one_run() is True

    run_response = await client.get(f"/api/knowledge-agent/runs/{run_id}")
    assert run_response.status_code == 200
    run_data = run_response.json()
    assert run_data["status"] == RUN_PARTIAL
    assert run_data["answer"]["status"] == "insufficient"
    summary = run_data["investigation_summary"]
    assert summary["stop_reason"] == STOP_REASON_NO_PROGRESS
    # 正常空结果不算 fallback：工具阶段不进入降级摘要
    # （测试环境上下文决策可能因离线模型降级，但不来自正常空搜索）
    tool_stages = [
        stage
        for stage in run_data["fallback_summary"]["stages"]
        if stage["purpose"].startswith("tool:")
    ]
    assert tool_stages == []
    obs = (
        await client.get(f"/api/knowledge-agent/runs/{run_id}/observability")
    ).json()
    search_tool = [
        item
        for item in obs["tool_calls"]
        if item["tool_name"] == "search_confirmed_knowledge"
    ][0]
    assert search_tool["status"] == "empty"


@pytest.mark.asyncio
async def test_api_cancel_investigation_run_preserves_detail(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """取消调查 Run：Run 与调查进入取消态，逐轮详情仍可读。"""
    await _register(client)
    project = await _project(client, "取消 API 项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(
        client, project["id"], node["id"], "闭水试验通常持续 24 小时。"
    )
    conversation = await _conversation(client)
    submitted = await _submit(
        client,
        conversation["id"],
        "问题",
        client_message_id="cancel-inv",
        answer_mode="investigate",
    )
    run_id = submitted["run"]["id"]
    async with async_session_factory() as db:
        await _cancel_other_waiting_runs(db, keep_run_id=run_id)

    async def _search_sets_cancel(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        async with async_session_factory() as other:
            other_run = await other.get(KnowledgeAgentRun, run_id)
            other_run.cancel_requested = True
            await other.commit()
        ctx.discovered_entry_ids.add(entry["id"])
        return SearchToolOutput(items=[_search_result(entry["id"], "闭水试验")])

    async def _controller(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        return (
            InvestigationControllerDraft(
                action=INVESTIGATION_ACTION_SEARCH,
                queries=["闭水试验"],
            ),
            _controller_meta(),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
        _search_sets_cancel,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
        _controller,
    )

    assert await process_one_run() is True
    run_response = await client.get(f"/api/knowledge-agent/runs/{run_id}")
    assert run_response.json()["status"] == RUN_CANCELLED
    detail_response = await client.get(
        f"/api/knowledge-agent/runs/{run_id}/investigation"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == INVESTIGATION_STATUS_CANCELLED
