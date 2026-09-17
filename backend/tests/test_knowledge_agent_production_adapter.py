"""正式 dialogue-loop 适配器的确定性边界测试。"""

import json
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeMessage,
)
from app.schemas.knowledge_agent import KnowledgeConversationCreate, KnowledgeRunSubmitRequest
from app.services.knowledge_agent.conversations import create_conversation
from app.services.knowledge_agent.observability import MODEL_NOT_DISPATCHED
from app.services.knowledge_agent.production_adapter import (
    _answer_status,
    _continuation_from_snapshot,
    _continuation_snapshot,
    _DialogueStagePublisher,
    _restore_state,
    _run_status,
    _state_snapshot,
    execute_dialogue_loop_run,
)
from app.services.knowledge_agent.runs import run_out, submit_message
from evals.dialogue_loop import loop as loop_module
from evals.dialogue_loop.core import BudgetLedger, ContinuationState
from evals.dialogue_loop.instrumentation import InputEstimate, Instrumentation
from evals.dialogue_loop.loop import LoopState
from tests._knowledge_agent_fixtures import create_user, create_workspace


def _state() -> LoopState:
    ledger = BudgetLedger()
    state = LoopState(
        workspace_id=11,
        user_id=22,
        conversation_id=33,
        ledger=ledger,
        instrumentation=Instrumentation(ledger),
        scope_type="project",
        project_id=44,
        project_name="项目甲",
    )
    state.begin_turn(55, "列出项目记录")
    return state


def test_production_state_round_trip_preserves_scope_results_and_continuation() -> None:
    state = _state()
    fingerprint = "7" * 64
    state.discovered_entry_ids.add(7)
    state.discovered_entry_fingerprints[7] = fingerprint
    handle = state.store_result(
        "list",
        {"items": [{"entry_id": 7, "title": "记录"}]},
        "completed",
        "limited",
        semantics={"project_name": "项目甲"},
    )
    state.evidence["ev-1"] = {"entry_id": 7, "source_id": 8}
    state.continuation = ContinuationState(
        task_type="finalize_answer",
        tool_name="finalize_answer",
        scope={"workspace_id": 11, "user_id": 22, "authorized_entry_ids": [7]},
        pending_steps=[{"step": "finalize_answer"}],
        recoverable_material={
            "mode": "grove_material",
            "records": {
                handle: {
                    "kind": "list",
                    "payload": {"items": [{"entry_id": 7, "title": "记录"}]},
                    "status": "completed",
                    "completeness": "limited",
                    "turn_index": 1,
                    "semantics": {"project_name": "项目甲"},
                    "displayable": True,
                }
            },
            "evidence": state.evidence,
            "events": [],
        },
        validation_refs={"entry_ids": [7], "source_ids": [8]},
    )
    snapshot = _state_snapshot(
        state,
        {
            "status": "partial_completed",
            "answer": "已读取记录，等待收尾。",
            "blocks": [{"kind": "entry", "entry_id": 7}],
            "completion": {
                "status": "partial_completed",
                "can_continue": True,
                "continuation": _continuation_snapshot(state.continuation),
            },
            "model_calls": [],
        },
        loop_status="partial_completed",
    )
    restored = _state()
    _restore_state(restored, json.loads(json.dumps(snapshot, ensure_ascii=False)))
    assert restored.project_id == 44
    assert restored.authorized_entry_ids == {7}
    assert restored.discovered_entry_ids == {7}
    assert restored.discovered_entry_fingerprints == {7: fingerprint}
    assert restored.result_sets[handle].payload["items"][0]["entry_id"] == 7
    assert restored.continuation is not None
    assert restored.continuation.pending_steps == [{"step": "finalize_answer"}]
    assert restored.continuation.validation_refs["source_ids"] == [8]

    switched_scope = _state()
    switched_scope.project_id = 45
    _restore_state(
        switched_scope,
        json.loads(json.dumps(snapshot, ensure_ascii=False)),
    )
    assert switched_scope.authorized_entry_ids == {7}
    assert switched_scope.discovered_entry_ids == set()
    assert switched_scope.discovered_entry_fingerprints == {}


def test_production_restore_does_not_authorize_candidate_list() -> None:
    state = _state()
    state.discovered_entry_ids.add(99)
    state.discovered_entry_fingerprints[99] = "9" * 64
    handle = state.store_result(
        "list",
        {"items": [{"entry_id": 99, "title": "间接候选"}]},
        "completed",
        "limited",
        semantics={"result_role": "candidate"},
        displayable=True,
    )
    snapshot = _state_snapshot(
        state,
        {"status": "completed", "answer": "", "blocks": [], "model_calls": []},
        loop_status="completed",
    )
    restored = _state()
    _restore_state(restored, json.loads(json.dumps(snapshot, ensure_ascii=False)))

    assert handle in restored.result_sets
    assert restored.result_sets[handle].semantics["result_role"] == "candidate"
    assert restored.authorized_entry_ids == set()
    assert restored.discovered_entry_ids == set()
    assert restored.discovered_entry_fingerprints == {}


@pytest.mark.asyncio
async def test_run_786_to_787_restores_authorized_discovery_without_requery(
    monkeypatch,
) -> None:
    """Run 787 应首次直接读取 Run 786 已授权且已发现的三条 Entry。"""
    entry_ids = [35, 18, 84]
    fingerprints = {
        entry_id: f"{entry_id:064x}"
        for entry_id in entry_ids
    }
    run_786 = _state()
    run_786.discovered_entry_ids.update(entry_ids)
    run_786.discovered_entry_fingerprints.update(fingerprints)
    selected_handle = run_786.store_result(
        "list",
        {
            "items": [
                {
                    "entry_id": entry_id,
                    "title": f"Entry {entry_id}",
                }
                for entry_id in entry_ids
            ]
        },
        "completed",
        "limited",
        semantics={"result_role": "authorized", "relevance_scope": "direct"},
    )
    run_786.store_result(
        "entries",
        {
            "items": [
                {
                    "entry_id": entry_id,
                    "title": f"Entry {entry_id}",
                    "content": f"内容 {entry_id}",
                    "project_name": "项目甲",
                    "node_path": "",
                    "sources": [],
                }
                for entry_id in entry_ids
            ],
            "denied_entry_ids": [],
            "unavailable_entry_ids": [],
        },
        "completed",
        "limited",
    )
    snapshot = _state_snapshot(
        run_786,
        {
            "status": "completed",
            "answer": "已读取三条记录。",
            "blocks": [{"kind": "list", "result_handle": selected_handle}],
            "completion": {"status": "completed", "can_continue": False},
            "model_calls": [],
        },
        loop_status="completed",
    )

    run_787 = _state()
    _restore_state(run_787, json.loads(json.dumps(snapshot, ensure_ascii=False)))
    run_787.begin_turn(787, "把这几条的内容输出出来")
    run_787.current_handles.update(run_787.result_sets)
    dispatched: list[str] = []

    async def fake_dispatch(ctx, tool_name, params, kind, **_kwargs):
        dispatched.append(tool_name)
        assert tool_name == "read_entries"
        assert params == {"entry_ids": entry_ids}
        assert ctx.deps.state.discovered_entry_ids.issuperset(entry_ids)
        payload = {
            "items": [
                {
                    "entry_id": entry_id,
                    "title": f"Entry {entry_id}",
                    "content": f"内容 {entry_id}",
                    "project_name": "项目甲",
                    "node_path": "",
                    "sources": [],
                }
                for entry_id in entry_ids
            ],
            "denied_entry_ids": [],
            "unavailable_entry_ids": [],
        }
        handle = ctx.deps.state.store_result(
            kind, payload, "completed", "limited"
        )
        event = {
            "tool": tool_name,
            "shared_tool": tool_name,
            "result_handle": handle,
            "status": "completed",
            "completeness": "limited",
            "params": params,
            "result_summary": {"returned_count": len(entry_ids)},
            "error": None,
            "turn_index": run_787.turn_index,
        }
        run_787.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop_module, "_dispatch", fake_dispatch)
    model_calls = 0

    def respond(_messages, info):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelResponse(
                parts=[ToolCallPart("read_entries", {"entry_ids": entry_ids})]
            )
        read_handle = next(
            handle
            for handle in run_787.current_handles
            if run_787.result_sets[handle].kind == "entries"
            and run_787.result_sets[handle].turn_index == run_787.turn_index
        )
        refs = "\n".join(
            f"[[entry:{read_handle}:{position}]]"
            for position in range(1, len(entry_ids) + 1)
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": refs}]},
                )
            ]
        )

    turn, _ = await loop_module.run_turn(
        loop_module.build_agent(FunctionModel(respond)),
        run_787,
        "把这几条的内容输出出来",
        [],
    )

    assert turn["status"] == "completed", turn
    assert dispatched == ["read_entries"]
    assert not any(
        event.get("tool") in {
            "search_knowledge",
            "query_entries",
            "select_relevant_entries",
        }
        for event in turn["tool_calls"]
    )


def test_terminal_and_answer_status_mapping_is_programmatic() -> None:
    assert _run_status("completed") == "completed"
    assert _run_status("partial_completed") == "partial"
    assert _run_status("unsupported") == "failed"
    assert _answer_status("completed", [{"kind": "list"}]) == "completed"
    assert _answer_status("completed", [{"kind": "insufficient", "text": "缺口"}]) == "insufficient"
    assert _answer_status("partial_completed", []) == "partial"


@pytest.mark.asyncio
async def test_stage_publisher_preserves_worker_step_and_terminal_hides_stage() -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "阶段发布")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-stage-publisher-1",
                message="查询并整理",
            ),
        )
        run.status = "processing"
        run.current_step = "dialogue_loop"
        run.dialogue_loop_state_json = json.dumps(
            {"version": 1, "loop_status": "processing"}
        )
        await db.commit()
        run_id = run.id

    publisher = _DialogueStagePublisher(run_id)
    publisher.publish("querying")
    publisher.publish("querying")
    publisher.publish("reading_entries")
    await publisher.close()

    async with async_session_factory() as db:
        saved = await db.get(KnowledgeAgentRun, run_id)
        assert saved is not None
        assert saved.current_step == "dialogue_loop"
        assert json.loads(saved.dialogue_loop_state_json)["stage"] == "reading_entries"
        assert run_out(saved).dialogue_stage == "reading_entries"
        saved.status = "completed"
        saved.current_step = None
        await db.commit()
        await db.refresh(saved)
        assert run_out(saved).dialogue_stage is None


def test_continuation_snapshot_is_separate_from_public_material_summary() -> None:
    continuation = ContinuationState(
        task_type="finalize_answer",
        tool_name="finalize_answer",
        recoverable_material={"records": {"rs-1": {"payload": {"items": []}}}},
    )
    snapshot = _continuation_snapshot(continuation)
    assert snapshot is not None
    assert "recoverable_material" in snapshot
    assert "recoverable_material" not in continuation.snapshot()
    assert _continuation_from_snapshot(snapshot).task_type == "finalize_answer"


@pytest.mark.asyncio
async def test_execute_persists_structured_blocks_and_candidate_only_result(monkeypatch) -> None:
    """适配器写正式 Run/Message；循环结果不会触碰 Entry 写入服务。"""
    async with async_session_factory() as db:
        user = await create_user(db, "生产适配")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-adapter-1",
                message="整理成候选稿",
                basis_mode="auto",
            ),
        )
        run.status = "processing"
        run.current_step = "claim"
        await db.commit()

        async def fake_turn(agent, state, message, history):
            state.begin_turn(run.id, message)
            return (
                {
                    "status": "completed",
                    "answer": "这是候选内容。",
                    "blocks": [{"kind": "candidate", "text": "这是候选内容。"}],
                    "completion": {
                        "status": "completed",
                        "can_continue": False,
                        "continuation": None,
                    },
                    "model_calls": [],
                    "tool_calls": [],
                    "error": None,
                },
                [],
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.production_adapter.run_turn", fake_turn
        )
        await execute_dialogue_loop_run(db, run)
        await db.commit()

    async with async_session_factory() as db:
        saved = await db.get(KnowledgeAgentRun, run.id)
        assert saved is not None
        assert saved.status == "completed"
        state = json.loads(saved.dialogue_loop_state_json)
        assert state["blocks"][0]["kind"] == "candidate"
        fallback = json.loads(saved.fallback_summary)
        assert fallback["has_fallback"] is True
        assert fallback["stages"][0]["outcome"] == "deterministic_fallback"
        assistant = await db.get(KnowledgeMessage, saved.assistant_message_id)
        assert assistant is not None
        assert assistant.content == "这是候选内容。"


@pytest.mark.asyncio
async def test_real_model_not_dispatched_is_not_reported_as_fallback(monkeypatch) -> None:
    """真实模型成功后，预算停止点只记录未派发，不污染 fallback 摘要。"""
    async with async_session_factory() as db:
        user = await create_user(db, "真实模型审计")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-observability-1",
                message="列出项目",
            ),
        )
        run.status = "processing"
        run.current_step = "claim"
        await db.commit()

        def _respond(_messages, _info):
            raise AssertionError("fake FunctionModel 不应被 run_turn 调用")

        async def _get_text_model(_db, _workspace_id):
            return FunctionModel(_respond, model_name="deepseek-v4-flash")

        monkeypatch.setattr("app.services.ai_models.get_text_model", _get_text_model)

        async def fake_turn(agent, state, message, history):
            return (
                {
                    "status": "completed",
                    "answer": "已完成真实模型阶段。",
                    "blocks": [{"kind": "text", "text": "已完成真实模型阶段。"}],
                    "completion": {"status": "completed", "can_continue": False},
                    "model_calls": [
                        {
                            "kind": "text_not_dispatched",
                            "provider": "deepseek",
                            "model": "deepseek-v4-flash",
                            "error": "达到求解停止点，当前求解请求未派发",
                            "duration_ms": 0,
                        }
                    ],
                    "tool_calls": [],
                    "error": None,
                },
                [],
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.production_adapter.run_turn", fake_turn
        )
        await execute_dialogue_loop_run(db, run)
        await db.commit()
        await db.refresh(run)

        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is False
        assert summary["stages"][0]["outcome"] == MODEL_NOT_DISPATCHED
        assert summary["stages"][0]["is_fallback"] is False
        invocation = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalar_one()
        assert invocation.outcome == MODEL_NOT_DISPATCHED
        assert invocation.is_fallback is False


@pytest.mark.asyncio
async def test_finalize_transition_is_not_dispatched_in_production_audit(monkeypatch) -> None:
    async with async_session_factory() as db:
        user = await create_user(db, "收尾转换审计")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-finalize-transition-1",
                message="整理回答",
            ),
        )
        run.status = "processing"
        run.current_step = "claim"
        await db.commit()

        def _respond(_messages, _info):
            raise AssertionError("模型不应由测试适配器直接调用")

        async def _get_text_model(_db, _workspace_id):
            return FunctionModel(_respond, model_name="deepseek-v4-flash")

        monkeypatch.setattr("app.services.ai_models.get_text_model", _get_text_model)

        async def fake_turn(agent, state, message, history):
            return (
                {
                    "status": "completed",
                    "answer": "已整理。",
                    "blocks": [{"kind": "text", "text": "已整理。"}],
                    "completion": {"status": "completed", "can_continue": False},
                    "model_calls": [
                        {
                            "kind": "finalize_transition",
                            "provider": "deepseek",
                            "model": "deepseek-v4-flash",
                            "error": "达到求解停止点，当前求解请求未派发",
                            "duration_ms": 0,
                            "projected_input_tokens": 9290,
                            "finalize_reason": "input_soft_limit",
                        }
                    ],
                    "tool_calls": [],
                    "error": None,
                },
                [],
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.production_adapter.run_turn", fake_turn
        )
        await execute_dialogue_loop_run(db, run)
        await db.commit()

        invocation = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalar_one()
        assert invocation.outcome == MODEL_NOT_DISPATCHED
        assert invocation.is_fallback is False


@pytest.mark.asyncio
async def test_production_adapter_uses_same_invalid_json_fixture_and_resume_only_finalizes(
    monkeypatch,
) -> None:
    """正式适配器与实验循环共用损坏 JSON 夹具，继续时不重复成功工具。"""

    raw = (
        Path(__file__).parent / "fixtures" / "dialogue-invalid-json-six-point.txt"
    ).read_text(encoding="utf-8").rstrip("\n")
    provider_calls = []

    def respond(messages, info):
        provider_calls.append((messages, info))
        if len(provider_calls) == 1:
            return ModelResponse(parts=[ToolCallPart("list_projects", {})])
        if len(provider_calls) == 2:
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, {"INVALID_JSON": raw})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"blocks": [{"kind": "text", "text": "已仅重试最终回答。"}]},
                )
            ]
        )

    async def get_text_model(_db, _workspace_id):
        return FunctionModel(respond, model_name="deepseek-v4-flash")

    def estimate_input(_messages, parameters=None):
        has_data_tools = bool(parameters and parameters.function_tools)
        tokens = 8_000 if not has_data_tools else 8_295 if not provider_calls else 9_290
        return InputEstimate(tokens=tokens, components={"version": "production-parity"})

    monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)
    monkeypatch.setattr(
        "evals.dialogue_loop.instrumentation.estimate_input", estimate_input
    )

    async with async_session_factory() as db:
        user = await create_user(db, "生产损坏 JSON")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, first_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-invalid-json-1",
                message="列出项目并整理回答",
            ),
        )
        first_run.status = "processing"
        first_run.current_step = "claim"
        existing_tool_call_ids = set(
            (await db.execute(select(KnowledgeAgentToolCall.id))).scalars()
        )
        await db.commit()
        await execute_dialogue_loop_run(db, first_run)
        await db.commit()
        await db.refresh(first_run)

        first_snapshot = json.loads(first_run.dialogue_loop_state_json)
        assert first_run.status == "partial"
        assert first_snapshot["completion"]["reason_code"] == "finalize_output_invalid"
        assert first_snapshot["continuation"]["task_type"] == "finalize_answer"

        _, second_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="production-invalid-json-2",
                message="继续",
            ),
        )
        second_run.status = "processing"
        second_run.current_step = "claim"
        await db.commit()
        await execute_dialogue_loop_run(db, second_run)
        await db.commit()
        await db.refresh(second_run)

        assert second_run.status == "completed"
        assert "已仅重试最终回答" in json.loads(second_run.answer_json)["answer"]
        tool_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.id.not_in(existing_tool_call_ids or {-1})
                )
            )
        ).scalars().all()
        assert [call.tool_name for call in tool_calls] == ["list_projects"]
        assert len(provider_calls) == 3
