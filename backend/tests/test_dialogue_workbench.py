"""知识 Agent 实验工作台的无模型边界测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from evals.dialogue_loop.core import BATCH_TEXT_REQUESTS
from evals.dialogue_workbench.runtime import OfflineFixtureEngine, WorkbenchRuntime
from evals.dialogue_workbench.server import create_app
from evals.dialogue_workbench.store import WorkbenchStore


def make_runtime(tmp_path: Path, engine=None) -> WorkbenchRuntime:
    return WorkbenchRuntime(
        engine=engine or OfflineFixtureEngine(),
        store=WorkbenchStore(tmp_path / "records"),
        snapshot_at="2026-09-07T12:00:00+00:00",
        snapshot_fingerprint="abc123",
        isolation_unchanged=lambda: True,
    )


async def wait_for_turn(runtime: WorkbenchRuntime, conversation_id: str, turn_id: str) -> dict:
    for _ in range(100):
        turn = runtime._turn(runtime._conversation(conversation_id), turn_id)
        if turn["status"] not in {"queued", "running"}:
            return turn
        await asyncio.sleep(0.01)
    raise AssertionError("轮次没有在测试时限内结束")


@pytest.mark.asyncio
async def test_real_engine_factory_reserves_last_request_for_finalization(monkeypatch):
    from unittest.mock import AsyncMock

    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from app.db import session
    from app.services import ai_models
    from evals.dialogue_loop.instrumentation import BudgetedModel
    from evals.dialogue_loop.loop import LoopState
    from evals.dialogue_workbench import engine as engine_module

    installed = []
    calls = []

    def respond(messages, info):
        calls.append(info)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "insufficient", "text": "现有材料不足以回答。"}]},
                )
            ]
        )

    async def get_model(db, workspace_id):
        return BudgetedModel(FunctionModel(respond), installed[0])

    monkeypatch.setattr(engine_module, "install_instrumentation", installed.append)
    monkeypatch.setattr(session, "async_session_factory", lambda: AsyncMock())
    monkeypatch.setattr(ai_models, "get_text_model", get_model)
    monkeypatch.setattr(engine_module, "_submit_turn", AsyncMock(return_value=4))
    monkeypatch.setattr(engine_module, "_finish_new_run", AsyncMock())
    engine = await engine_module.UnifiedLoopEngine.create({"workspace_id": 1, "user_id": 2})
    context = engine_module.UnifiedConversationContext(
        state=LoopState(1, 2, 3, engine.ledger, engine.instrumentation), history=[]
    )
    engine.ledger.batch_text_requests = BATCH_TEXT_REQUESTS - 1

    turn = await engine.run_turn(context, "查询目录", 1, lambda stage: None)

    assert turn["status"] == "completed"
    assert turn["finalization"]["reason"] == "text_request_budget"
    assert turn["finalization"]["status"] == "completed"
    assert turn["finalization"]["attempted"] is True
    assert len(calls) == 1
    assert calls[0].function_tools == []
    assert engine.ledger.batch_text_requests == BATCH_TEXT_REQUESTS


@pytest.mark.asyncio
async def test_continuous_turns_preserve_order_diagnostics_and_shared_budget(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    conversation = await runtime.create_conversation()

    first = await runtime.submit_turn(conversation["id"], "列出装修记录", "request-0001")
    duplicate = await runtime.submit_turn(conversation["id"], "不会再次执行", "request-0001")
    assert duplicate["id"] == first["id"]
    first_done = await wait_for_turn(runtime, conversation["id"], first["id"])

    second = await runtime.submit_turn(conversation["id"], "展开列表第二项", "request-0002")
    second_done = await wait_for_turn(runtime, conversation["id"], second["id"])

    assert [item["title"] for item in first_done["blocks"][2]["items"]] == [
        "施工材料环保等级",
        "甲醛控制方法",
    ]
    assert first_done["tool_calls"][1]["params"]["entry_id"] == 101
    assert second_done["context"]["history_turns"] == 1
    assert runtime.public_state()["budget"]["used"]["text_requests"] == 2


@pytest.mark.asyncio
async def test_refresh_persistence_feedback_export_and_restart_read_only(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    conversation = await runtime.create_conversation()
    created = await runtime.submit_turn(conversation["id"], "统计正式记录", "request-1001")
    await wait_for_turn(runtime, conversation["id"], created["id"])
    await runtime.save_feedback(conversation["id"], created["id"], "omitted", "漏了项目条件")

    persisted = json.loads(runtime.store.path.read_text(encoding="utf-8"))
    saved_turn = persisted["sessions"][-1]["conversations"][0]["turns"][0]
    assert saved_turn["feedback"]["experiment_version"]
    assert saved_turn["feedback"]["diagnostic"]["budget"]
    assert runtime.store.root.stat().st_mode & 0o777 == 0o700
    assert runtime.store.path.stat().st_mode & 0o777 == 0o600
    assert runtime.export_payload() == persisted

    restarted = make_runtime(tmp_path)
    old_conversation = restarted._conversation(conversation["id"])
    assert old_conversation["read_only"] is True
    assert "不可恢复" in old_conversation["recovery_notice"]
    with pytest.raises(PermissionError, match="只能查看和导出"):
        await restarted.save_feedback(conversation["id"], created["id"], "wrong", "修改")


class SlowFixtureEngine(OfflineFixtureEngine):
    async def run_turn(self, context, message, turn_number, stage):
        self.ledger.start_turn()
        stage("querying")
        await asyncio.sleep(10)
        raise AssertionError("取消后不应继续")


@pytest.mark.asyncio
async def test_cancel_has_no_additional_model_request_and_keeps_safe_result(tmp_path: Path):
    engine = SlowFixtureEngine()
    runtime = make_runtime(tmp_path, engine)
    conversation = await runtime.create_conversation()
    created = await runtime.submit_turn(conversation["id"], "慢查询", "request-2001")
    await asyncio.sleep(0.02)

    cancelled = await runtime.cancel_turn(conversation["id"], created["id"])

    assert cancelled["status"] == "cancelled"
    assert cancelled["finalization"]["attempted"] is False
    assert cancelled["model_calls"] == []
    assert engine.ledger.batch_text_requests == 0


@pytest.mark.asyncio
async def test_failure_and_exhausted_budget_are_explicit_without_reset(tmp_path: Path):
    runtime = make_runtime(tmp_path)
    conversation = await runtime.create_conversation()
    failed = await runtime.submit_turn(conversation["id"], "请模拟失败", "request-3001")
    failed_done = await wait_for_turn(runtime, conversation["id"], failed["id"])
    assert failed_done["status"] == "failed"
    assert failed_done["error_details"]["category"] == "provider"

    runtime.engine.ledger.batch_text_requests = BATCH_TEXT_REQUESTS
    exhausted = await runtime.submit_turn(conversation["id"], "再查询", "request-3002")
    exhausted_done = await wait_for_turn(runtime, conversation["id"], exhausted["id"])
    assert exhausted_done["status"] == "failed"
    assert "整批文本模型请求预算已耗尽" in exhausted_done["error"]
    assert runtime.public_state()["budget"]["remaining"]["text_requests"] == 0


@pytest.mark.asyncio
async def test_api_requires_cookie_rejects_identity_fields_and_checks_origin(tmp_path: Path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "workbench.html").write_text("<div>workbench</div>", encoding="utf-8")
    runtime = make_runtime(tmp_path)
    app = create_app(runtime, static)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50123))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        assert (await client.get("/api/workbench/state")).status_code == 401
        bootstrap = await client.post("/api/workbench/bootstrap")
        assert bootstrap.status_code == 200
        assert "HttpOnly" in bootstrap.headers["set-cookie"]
        conversation = await client.post("/api/workbench/conversations")
        assert conversation.status_code == 201
        conversation_id = conversation.json()["id"]
        injected = await client.post(
            f"/api/workbench/conversations/{conversation_id}/turns",
            json={
                "message": "查询",
                "request_id": "request-4001",
                "workspace_id": 999,
            },
        )
        assert injected.status_code == 422
        exported = await client.get("/api/workbench/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        assert "grove_experiment_session" not in exported.text
        foreign_origin = await client.post(
            "/api/workbench/conversations",
            headers={"Origin": "http://127.0.0.1:9999"},
        )
        assert foreign_origin.status_code == 403


@pytest.mark.asyncio
async def test_isolation_change_stops_further_conversations(tmp_path: Path):
    unchanged = True
    runtime = WorkbenchRuntime(
        engine=OfflineFixtureEngine(),
        store=WorkbenchStore(tmp_path / "records"),
        snapshot_at="2026-09-07T12:00:00+00:00",
        snapshot_fingerprint="abc123",
        isolation_unchanged=lambda: unchanged,
    )
    conversation = await runtime.create_conversation()
    unchanged = False
    turn = await runtime.submit_turn(conversation["id"], "查询", "request-5001")
    await wait_for_turn(runtime, conversation["id"], turn["id"])
    assert runtime.public_state()["metadata"]["status"] == "unsafe"
    with pytest.raises(RuntimeError, match="隔离指纹"):
        await runtime.create_conversation()
