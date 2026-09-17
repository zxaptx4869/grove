"""正式 dialogue-loop 适配器的确定性边界测试。"""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
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
from evals.dialogue_loop.core import (
    TURN_PARTIAL_COMPLETED,
    BudgetLedger,
    ContinuationState,
    StopState,
)
from evals.dialogue_loop.instrumentation import InputEstimate, Instrumentation
from evals.dialogue_loop.loop import EditingContext, LoopState, _current_material_history
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


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
    entry = {
        "entry_id": 7,
        "title": "记录",
        "content": "原记录认为安装空间大约需要预留 20 厘米。",
        "sources": [{"source_id": 8, "title": "安装说明"}],
    }
    refs = {
        "workspace_id": 11,
        "user_id": 22,
        "entry_ids": [7],
        "source_ids": [8],
        "source_pairs": [[7, 8]],
        "fingerprints": {"entry:7": "a" * 64, "evidence:7:8": "b" * 64},
    }
    state.focused_entry = entry
    state.focused_entry_refs = refs
    state.editing_context = EditingContext(
        entry=entry,
        validation_refs=refs,
        discussion="通用分析认为应保留“大约”的不确定性，并说明这是安装空间。",
        draft={
            "blocks": [
                {
                    "kind": "text",
                    "text": "候选：安装时建议大约预留 20 厘米空间，尚未写入。",
                }
            ],
            "needs_clarification": False,
        },
        decisions=["按刚才分析改", "内容不变，表达更口语化"],
    )
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
    assert restored.current_handles == set()
    assert restored.continuation is not None
    assert restored.continuation.pending_steps == [{"step": "finalize_answer"}]
    assert restored.continuation.validation_refs["source_ids"] == [8]
    assert restored.focused_entry == entry
    assert restored.focused_entry_refs == refs
    assert restored.editing_context is not None
    assert restored.editing_context.discussion == state.editing_context.discussion
    assert restored.editing_context.draft == state.editing_context.draft
    assert restored.editing_context.decisions == state.editing_context.decisions

    restored.begin_turn(56, "按刚才分析改得更口语化")
    restored.editing_active = True
    restored.editing_purpose = "candidate"
    restored.candidate_draft = restored.editing_context.draft
    material_history = _current_material_history(restored, restored.current_message, [], [])
    serialized_history = str(material_history)
    assert entry["content"] in serialized_history
    assert "通用分析认为应保留" in serialized_history
    assert "候选：安装时建议" in serialized_history
    assert "内容不变，表达更口语化" in serialized_history

    switched_scope = _state()
    switched_scope.project_id = 45
    _restore_state(
        switched_scope,
        json.loads(json.dumps(snapshot, ensure_ascii=False)),
    )
    assert switched_scope.authorized_entry_ids == {7}
    assert switched_scope.discovered_entry_ids == set()
    assert switched_scope.discovered_entry_fingerprints == {}
    assert switched_scope.focused_entry is None
    assert switched_scope.focused_entry_refs is None
    assert switched_scope.editing_context is None


@pytest.mark.asyncio
async def test_production_adapter_preserves_displayed_entry_discussion_and_candidate(
    monkeypatch,
) -> None:
    """真实 run_turn 串起正文展示、直接分析、候选、对象切换和独立问题。"""

    model_run = 0
    observed: dict[str, object] = {"candidate_inputs": [], "instructions": []}

    def tool_return(messages, tool_name: str) -> dict:
        for message in reversed(messages):
            for part in reversed(message.parts):
                if isinstance(part, ToolReturnPart) and part.tool_name == tool_name:
                    assert isinstance(part.content, dict)
                    return part.content
        raise AssertionError(f"缺少 {tool_name} 工具返回")

    async with async_session_factory() as db:
        user = await create_user(db, "真实对象讨论链")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "材料项目")
        node = await create_child_node(db, project, "板材")
        entries = []
        for index, (title, content) in enumerate(
            (
                ("第一条材料", "第一条正文：建议保留条件并现场确认。"),
                ("第二条材料", "第二条正文：需要单独核对使用场景。"),
                ("第三条材料", "第三条正文：只作为补充背景。"),
            ),
            start=1,
        ):
            source, attachment = await create_source_attachment(
                db,
                workspace,
                project,
                title=f"材料来源 {index}",
                text_content=content,
            )
            entry = await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=title,
                content=content,
                quote=content,
            )
            entries.append(entry)
        await db.commit()
        for row in (user, workspace, project, *entries):
            await db.refresh(row)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="project", project_id=project.id),
        )

        displayed: dict[str, object] = {}

        def display_and_read(messages, info):
            call = int(displayed.get("calls", 0)) + 1
            displayed["calls"] = call
            if call == 1:
                return ModelResponse(parts=[ToolCallPart(
                    "query_entries",
                    {
                        "project_scope": "project",
                        "project_name": project.name,
                        "semantic_query": None,
                        "limit": 3,
                        "sort_field": "created_at",
                        "sort_direction": "asc",
                    },
                )])
            if call == 2:
                result = tool_return(messages, "query_entries")
                items = result["payload"]["items"]
                displayed["parent_handle"] = result["result_handle"]
                displayed["entry_ids"] = [item["entry_id"] for item in items]
                displayed["titles"] = [item["title"] for item in items]
                return ModelResponse(parts=[ToolCallPart(
                    "read_entries", {"entry_ids": displayed["entry_ids"]}
                )])
            result = tool_return(messages, "read_entries")
            displayed["read_handle"] = result["result_handle"]
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {"blocks": [{"kind": "result", "result_handle": result["result_handle"]}]},
            )])

        def discuss_first(_messages, info):
            instructions = str(info.instructions)
            observed["instructions"].append(instructions)
            assert displayed["parent_handle"] in instructions
            assert displayed["titles"][0] in instructions
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {
                    "blocks": [{
                        "kind": "text",
                        "text": "模型分析：第一条的条件性表达合理，并应保留现场确认步骤。",
                    }],
                    "discussion_entry_id": displayed["entry_ids"][0],
                },
            )])

        open_calls = 0
        opened_handles: list[str] = []

        def open_each_entry(messages, info):
            nonlocal open_calls
            open_calls += 1
            if open_calls > 1:
                previous = tool_return(messages, "open_list_item")
                opened_handles.append(previous["result_handle"])
            if open_calls <= 3:
                return ModelResponse(parts=[ToolCallPart(
                    "open_list_item",
                    {
                        "result_set_handle": displayed["parent_handle"],
                        "position": open_calls,
                    },
                )])
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {
                    "blocks": [
                        {"kind": "result", "result_handle": handle}
                        for handle in opened_handles
                    ]
                },
            )])

        candidate_calls = 0

        def create_candidate(messages, info):
            nonlocal candidate_calls
            candidate_calls += 1
            if info.function_tools:
                instructions = str(info.instructions)
                observed["instructions"].append(instructions)
                assert displayed["titles"][0] in instructions
                return ModelResponse(parts=[ToolCallPart(
                    "editing_context",
                    {
                        "action": "edit",
                        "purpose": "candidate",
                        "result_set_handle": displayed["parent_handle"],
                        "position": 1,
                    },
                )])
            serialized = str(messages)
            observed["candidate_inputs"].append(serialized)
            text = (
                "候选修订：建议保留条件性表达，并在现场确认后采用。"
                "这是基于当前记录和模型分析形成的候选，尚未写入正式记录；"
                "新增判断不是 Source 原文。"
            )
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {"blocks": [{"kind": "text", "text": text}]},
            )])

        def switch_second(_messages, info):
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {
                    "blocks": [{
                        "kind": "text",
                        "text": "模型分析：第二条需要结合实际使用场景判断。",
                    }],
                    "discussion_entry_id": displayed["entry_ids"][1],
                },
            )])

        def independent(_messages, info):
            return ModelResponse(parts=[ToolCallPart(
                info.output_tools[0].name,
                {"blocks": [{"kind": "text", "text": "甲醛是一种挥发性有机物。"}]},
            )])

        responders = [
            display_and_read,
            open_each_entry,
            discuss_first,
            create_candidate,
            switch_second,
            independent,
        ]

        async def get_text_model(_db, _workspace_id):
            nonlocal model_run
            responder = responders[model_run]
            model_run += 1
            return FunctionModel(responder, model_name=f"entry-chain-{model_run}")

        monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)

        runs = []
        snapshots = []
        for index, message in enumerate(
            (
                "按创建顺序展示三条正文",
                "逐条打开刚才三条正文",
                "抛开知识库，第一条你觉得合理吗",
                "按刚才分析改成候选",
                "现在分析第二条",
                "甲醛是什么",
            ),
            start=1,
        ):
            _, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"entry-chain-{index}",
                    message=message,
                    basis_mode="auto",
                ),
            )
            run.status = "processing"
            run.current_step = "claim"
            await db.commit()
            await execute_dialogue_loop_run(db, run)
            await db.commit()
            await db.refresh(run)
            run_snapshot = json.loads(run.dialogue_loop_state_json)
            assert run.status == "completed", (
                message,
                run.error,
                run_snapshot.get("completion"),
                run_snapshot.get("diagnostic"),
                run_snapshot.get("answer"),
                [
                        (str(call.get("error"))[:800], call.get("error_kind"))
                    for call in run_snapshot.get("model_calls", [])
                ],
            )
            runs.append(run)
            snapshots.append(run_snapshot)

        assert [run.status for run in runs] == ["completed"] * 6
        open_snapshot = snapshots[1]
        open_records = [
            record
            for record in open_snapshot["records"].values()
            if record["kind"] == "entries"
            and len(record["payload"]["items"]) == 1
            and record["semantics"].get("display_parent_handle")
            == displayed["parent_handle"]
        ]
        assert sorted(
            record["semantics"]["display_positions"][
                str(record["payload"]["items"][0]["entry_id"])
            ]
            for record in open_records
        ) == [1, 2, 3]
        assert all(record["semantics"]["entry_validation_refs"] for record in open_records)
        first_discussion = snapshots[2]["collaboration"]
        assert first_discussion["focused_entry"]["entry_id"] == displayed["entry_ids"][0]
        assert "第一条的条件性表达合理" in first_discussion["editing_context"]["discussion"]
        candidate = snapshots[3]["collaboration"]
        assert candidate["editing_context"]["draft"] is not None
        assert "候选修订" in json.dumps(candidate["editing_context"]["draft"], ensure_ascii=False)
        switched = snapshots[4]["collaboration"]
        assert switched["focused_entry"]["entry_id"] == displayed["entry_ids"][1]
        assert "第二条需要结合" in switched["editing_context"]["discussion"]
        independent_snapshot = snapshots[5]
        assert independent_snapshot["collaboration"] == switched
        assert independent_snapshot["records"]
        assert independent_snapshot["tool_events"] == []
        assert candidate_calls == 2
        assert open_calls == 4
        assert len(observed["candidate_inputs"]) == 1
        assert "第一条正文" in observed["candidate_inputs"][0]
        assert "第一条的条件性表达合理" in observed["candidate_inputs"][0]


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
async def test_completed_entry_collaboration_restores_actual_finalizer_input_across_runs(
    monkeypatch,
) -> None:
    """成功 Run 的分析和候选经正式快照恢复，并在新任务中清除。"""

    finalizer_inputs: list[tuple[str, str]] = []

    async def get_text_model(_db, _workspace_id):
        return FunctionModel(lambda _messages, _info: ModelResponse(parts=[]))

    async with async_session_factory() as db:
        user = await create_user(db, "成功协作上下文")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "安装项目")
        node = await create_child_node(db, project, "设备")
        source, attachment = await create_source_attachment(
            db, workspace, project, title="安装记录", text_content="现场空间有限。"
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="设备安装",
            content="现有记录：安装空间可能需要预留。",
            quote="现场空间有限",
        )
        await db.commit()
        for row in (user, workspace, project, source, attachment, entry):
            await db.refresh(row)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="project", project_id=project.id),
        )

        item = {
            "entry_id": entry.id,
            "title": entry.title,
            "content": entry.content,
            "project_name": project.name,
            "sources": [
                {
                    "source_id": source.id,
                    "source_title": source.title,
                    "attachment_id": attachment.id,
                    "quote": "现场空间有限",
                }
            ],
        }
        refs_holder: dict = {}
        candidate_text = (
            "现有记录提到安装空间可能需要预留；候选建议补充现场测量步骤。"
            "这是模型分析形成的候选，尚未写入正式记录，不属于 Source 原文。"
        )

        def completed_turn(state: LoopState, message: str, text: str) -> tuple[dict, list]:
            completion = {
                "status": "completed",
                "reason_code": "completed",
                "reason": None,
                "incomplete_steps": [],
                "can_continue": False,
                "continuation": None,
            }
            blocks = [{"kind": "text", "text": text}]
            state.remember_turn(
                message, text, state.tool_events, blocks=blocks, completion=completion
            )
            return ({
                "status": "completed",
                "answer": text,
                "blocks": blocks,
                "completion": completion,
                "model_calls": [],
                "tool_calls": list(state.tool_events),
                "budget": state.ledger.snapshot(),
                "error": None,
            }, [])

        async def controlled_run_turn(_agent, state, message, history):
            if message == "分析这条记录":
                refs = await loop_module._database_material_refs(
                    state, [entry.id], [(entry.id, source.id)]
                )
                refs_holder.update(refs)
                state.authorized_entry_ids.add(entry.id)
                state.discovered_entry_ids.add(entry.id)
                state.discovered_entry_fingerprints[entry.id] = "c" * 64
                handle = state.store_result(
                    "entries",
                    {"items": [item]},
                    "completed",
                    "limited",
                    semantics={"entry_validation_refs": {str(entry.id): refs}},
                )
                state.focused_entry = item
                state.focused_entry_refs = refs
                state.editing_context = EditingContext(
                    entry=item,
                    validation_refs=refs,
                    discussion="通用分析：保留“可能”的不确定性，并补充现场测量步骤。",
                    decisions=[message],
                )
                state.tool_events.append({
                    "tool": "editing_context",
                    "result_handle": handle,
                    "status": "completed",
                    "turn_index": state.turn_index,
                })
                return completed_turn(state, message, state.editing_context.discussion)

            if message == "按刚才分析改":
                assert state.editing_context is not None
                await loop_module.select_editing_context(
                    state, "edit", purpose="candidate"
                )

                def candidate_response(messages, info):
                    serialized = str(messages)
                    instructions = str(info.instructions)
                    finalizer_inputs.append((serialized, instructions))
                    assert item["content"] in serialized
                    assert "保留“可能”的不确定性" in serialized
                    assert message in serialized
                    assert "生成候选稿" in instructions
                    assert "尚未写入" in instructions
                    return ModelResponse(parts=[ToolCallPart(
                        info.output_tools[0].name,
                        {"blocks": [{"kind": "text", "text": candidate_text}]},
                    )])

                result = await loop_module._finalize_once(
                    loop_module.build_finalizer_agent(FunctionModel(candidate_response)),
                    state,
                    message,
                    history,
                    [],
                    "test_completed_collaboration",
                )
                return completed_turn(state, message, result.output.blocks[0].text)

            if message == "内容不变，只改得更口语化":
                assert state.editing_context is not None
                assert state.editing_context.draft is not None
                await loop_module.select_editing_context(
                    state, "edit", content_only=True, purpose="candidate"
                )

                def tone_response(messages, info):
                    serialized = str(messages)
                    instructions = str(info.instructions)
                    finalizer_inputs.append((serialized, instructions))
                    assert candidate_text in serialized
                    assert "上一阶段已生成候选修改稿" in serialized
                    assert "模型补充" in instructions
                    text = (
                        "现有记录说安装空间可能要预留；候选建议先量一下现场。"
                        "尚未写入正式记录，模型补充不属于 Source 原文。"
                    )
                    return ModelResponse(parts=[ToolCallPart(
                        info.output_tools[0].name,
                        {"blocks": [{"kind": "text", "text": text}]},
                    )])

                result = await loop_module._finalize_once(
                    loop_module.build_finalizer_agent(FunctionModel(tone_response)),
                    state,
                    message,
                    history,
                    [],
                    "test_tone_rewrite",
                )
                return completed_turn(state, message, result.output.blocks[0].text)

            assert message == "列出项目"
            assert state.editing_context is None
            assert state.focused_entry is None
            return completed_turn(state, message, "当前独立任务。")

        monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)
        monkeypatch.setattr(
            "app.services.knowledge_agent.production_adapter.run_turn",
            controlled_run_turn,
        )

        for index, (message, context_mode) in enumerate(
            [
                ("分析这条记录", "auto"),
                ("按刚才分析改", "auto"),
                ("内容不变，只改得更口语化", "auto"),
                ("列出项目", "new_topic"),
            ],
            start=1,
        ):
            _, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=f"completed-collaboration-{index}",
                    message=message,
                    context_mode=context_mode,
                ),
            )
            run.status = "processing"
            run.current_step = "claim"
            await db.commit()
            await execute_dialogue_loop_run(db, run)
            await db.commit()
            await db.refresh(run)
            assert run.status == "completed"

        assert refs_holder
        assert len(finalizer_inputs) == 2


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


@pytest.mark.asyncio
async def test_run_801_to_802_restores_candidate_editing_context_and_only_finalizes(
    monkeypatch,
) -> None:
    """Run 802 必须经正式快照恢复编辑对象，不重复资料调用。"""

    real_run_turn = loop_module.run_turn
    provider_calls = 0
    resumed_state = None
    first_message = "把这条记录改得更加口语化一些"

    def respond(_messages, info):
        nonlocal provider_calls
        provider_calls += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "text": (
                                    "把现有记录换成口语说法：洗碗机要紧挨水槽安装；"
                                    "水电提前留在旁边柜子的侧面或后面，走线走管要整齐，"
                                    "方便以后检修。还要留20公分的防倒灌空间并安装角阀。"
                                    "另外，单独拉一根10A电线，进水口的角阀要方便关水，"
                                    "排水管要比洗碗机底部高20公分，防止脏水倒灌。\n"
                                    "这是模型整理的候选稿，尚未写入正式 Entry；"
                                    "没有新增的 Source 原文。"
                                ),
                            }
                        ]
                    },
                )
            ]
        )

    async def get_text_model(_db, _workspace_id):
        return FunctionModel(respond, model_name="deterministic-run-802")

    async with async_session_factory() as db:
        user = await create_user(db, "Run801候选续接")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "厨房改造")
        node = await create_child_node(db, project, "洗碗机")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="安装现场记录",
            text_content="现场要求预留防倒灌空间。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="洗碗机安装",
            content=(
                "洗碗机安装要求：1)紧挨水槽安装；2)水电提前留到旁边柜子的"
                "侧面或后面；3)走线走管整齐方便检修。需预留20cm防倒灌空间和角阀。"
                "补充：单独拉一根10A电线；进水口装角阀方便关水；排水管要比洗碗机"
                "底部高20cm防止脏水倒灌。"
            ),
            quote="预留防倒灌空间",
        )
        await db.commit()
        for row in (user, workspace, project, source, attachment, entry):
            await db.refresh(row)

        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="project", project_id=project.id),
        )

        async def controlled_run_turn(agent, state, message, history):
            nonlocal resumed_state
            if message == first_message:
                item = {
                    "entry_id": entry.id,
                    "title": entry.title,
                    "content": entry.content,
                    "project_name": project.name,
                    "sources": [
                        {
                            "source_id": source.id,
                            "source_title": source.title,
                            "attachment_id": attachment.id,
                            "quote": "预留防倒灌空间",
                        }
                    ],
                }
                state.authorized_entry_ids.add(entry.id)
                entry_handle = state.store_result(
                    "entries", {"items": [item]}, "completed", "limited"
                )
                state.tool_events.append(
                    {
                        "tool": "read_entries",
                        "result_handle": entry_handle,
                        "status": "completed",
                        "completeness": "limited",
                        "params": {"entry_ids": [entry.id]},
                        "turn_index": state.turn_index,
                    }
                )
                refs = await loop_module._database_material_refs(
                    state, [entry.id], [(entry.id, source.id)]
                )
                state.editing_context = loop_module.EditingContext(
                    entry=item,
                    validation_refs=refs,
                    decisions=[first_message],
                )
                state.editing_active = True
                state.editing_purpose = "candidate"
                drifted_candidate = (
                    Path(__file__).parent
                    / "fixtures"
                    / "dialogue-run-801-drifted-candidate.txt"
                ).read_text(encoding="utf-8")
                state.candidate_draft = {
                    "blocks": [
                        {
                            "kind": "text",
                            "text": drifted_candidate,
                        }
                    ],
                    "needs_clarification": False,
                }
                state.candidate_draft_errors = [
                    "候选修改稿缺少：原记录与现有内容、来源边界"
                ]
                continuation = await loop_module._create_finalize_continuation(
                    state, message, state.tool_events
                )
                state.continuation = continuation
                stop = StopState(
                    status=TURN_PARTIAL_COMPLETED,
                    reason_code="finalize_output_invalid",
                    reason="候选输出未通过边界校验",
                    incomplete_steps=list(state.candidate_draft_errors),
                    can_continue=True,
                    continuation=continuation,
                )
                text, blocks = loop_module._verified_failure_output(state, stop)
                completion = state.completion_snapshot(TURN_PARTIAL_COMPLETED)
                state.remember_turn(
                    message,
                    text,
                    state.tool_events,
                    blocks=blocks,
                    completion=completion,
                )
                return (
                    {
                        "status": TURN_PARTIAL_COMPLETED,
                        "answer": text,
                        "blocks": blocks,
                        "completion": completion,
                        "model_calls": [],
                        "tool_calls": list(state.tool_events),
                        "budget": state.ledger.snapshot(),
                        "error": None,
                    },
                    history,
                )

            assert message == "继续"
            assert state.active_continuation is not None
            assert state.editing_context is None
            resumed_state = state
            result = await real_run_turn(agent, state, message, history)
            assert state.editing_context is not None
            return result

        monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)
        monkeypatch.setattr(
            "app.services.knowledge_agent.production_adapter.run_turn",
            controlled_run_turn,
        )

        _, run_801 = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="candidate-run-801",
                message=first_message,
            ),
        )
        run_801.status = "processing"
        run_801.current_step = "claim"
        await db.commit()
        await execute_dialogue_loop_run(db, run_801)
        await db.commit()
        await db.refresh(run_801)

        snapshot_801 = json.loads(run_801.dialogue_loop_state_json)
        assert run_801.status == "partial"
        assert snapshot_801["continuation"]["task_type"] == "candidate_draft"
        assert snapshot_801["continuation"]["scope"]["scope_type"] == "project"
        assert snapshot_801["continuation"]["scope"]["project_id"] == project.id
        recoverable = snapshot_801["continuation"]["recoverable_material"]
        assert len(recoverable["records"]) == 1
        assert recoverable["editing_context"]["entry_id"] == entry.id
        assert len(snapshot_801["blocks"]) <= 4

        _, run_802 = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="candidate-run-802",
                message="继续",
            ),
        )
        run_802.status = "processing"
        run_802.current_step = "claim"
        await db.commit()
        await execute_dialogue_loop_run(db, run_802)
        await db.commit()
        await db.refresh(run_802)

        assert run_802.status == "completed"
        assert provider_calls == 1
        assert resumed_state is not None
        assert resumed_state.tool_events == []
        answer_802 = json.loads(run_802.answer_json)["answer"]
        assert "20公分的防倒灌空间" in answer_802
        assert "10A电线" in answer_802
        assert "底部高20公分" in answer_802
        assert "尚未写入正式 Entry" in answer_802
        snapshot_802 = json.loads(run_802.dialogue_loop_state_json)
        assert snapshot_802["continuation"] is None
        assert snapshot_802["tool_events"] == []


@pytest.mark.asyncio
async def test_run_793_to_795_validation_failure_then_new_question_isolated(
    monkeypatch,
) -> None:
    """失败后的新问题必须重新查项目，不能自动续做上一轮整理。"""
    from evals.dialogue_loop.core import StopState
    from evals.dialogue_loop.instrumentation import InvocationLog

    real_run_turn = loop_module.run_turn
    model_calls = 0
    expected_project_handle = ""

    def respond(_messages, info):
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelResponse(parts=[ToolCallPart("list_projects", {})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "blocks": [
                            {
                                "kind": "list",
                                "result_handle": expected_project_handle,
                                "label": "当前项目",
                            },
                            {"kind": "text", "text": "你当前有 2 个项目。"},
                        ]
                    },
                )
            ]
        )

    async def get_text_model(_db, _workspace_id):
        return FunctionModel(respond, model_name="deterministic-run-795")

    async def controlled_run_turn(agent, state, message, history):
        if message == "抛开知识库，你分析一下呢":
            for index in range(11):
                state.store_result(
                    "statistic",
                    {"value": index + 1},
                    "completed",
                    "complete",
                )
            answer = "这是通用分析。如果需要，我可以整理成候选补充。"
            completion = state.completion_snapshot("completed")
            state.remember_turn(
                message,
                answer,
                [],
                blocks=[{"kind": "text", "text": answer}],
                completion=completion,
            )
            return (
                {
                    "status": "completed",
                    "answer": answer,
                    "blocks": [{"kind": "text", "text": answer}],
                    "completion": completion,
                    "model_calls": [],
                    "tool_calls": [],
                    "error": None,
                },
                history,
            )
        if message == "好的，你整理一下":
            # 当前失败任务本身产生 11 个材料，继续覆盖 12 块有界兜底；
            # 上一轮历史材料不再因恢复而自动成为 current。
            for index in range(11):
                state.store_result(
                    "statistic",
                    {"value": index + 1},
                    "completed",
                    "complete",
                )
            state.instrumentation.logs.append(
                InvocationLog(
                    kind="text",
                    provider="fixture",
                    model="validation-fixture",
                    duration_ms=7,
                    usage=None,
                    error="输出结构校验失败",
                    error_kind="validation",
                )
            )
            state.tool_events.append(
                {
                    "tool": "fixture_material",
                    "status": "completed",
                    "turn_index": state.turn_index,
                    "result_summary": {"returned_count": 11},
                }
            )
            stop = StopState(
                status="failed",
                reason_code="output_validation_failed",
                reason="模型输出未通过结构校验",
                incomplete_steps=["候选整理尚未完成"],
                can_continue=False,
            )
            state.stop(stop)
            answer, blocks = loop_module._verified_failure_output(state, stop)
            completion = state.completion_snapshot("failed")
            state.remember_turn(
                message,
                answer,
                state.tool_events,
                blocks=blocks,
                completion=completion,
            )
            return (
                {
                    "status": "failed",
                    "answer": answer,
                    "blocks": blocks,
                    "completion": completion,
                    "model_calls": [asdict(item) for item in state.instrumentation.logs],
                    "tool_calls": list(state.tool_events),
                    "error": "ValidationError: 输出结构校验失败",
                },
                history,
            )
        assert message == "我有几个项目"
        assert state.current_handles == set()
        assert history == []
        return await real_run_turn(agent, state, message, history)

    monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)
    monkeypatch.setattr(
        "app.services.knowledge_agent.production_adapter.run_turn",
        controlled_run_turn,
    )

    async with async_session_factory() as db:
        user = await create_user(db, "Run 793-795")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "项目甲")
        await create_project(db, workspace, "项目乙")
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )

        saved_runs = []
        for client_id, message in (
            ("run-793-analysis", "抛开知识库，你分析一下呢"),
            ("run-794-organize", "好的，你整理一下"),
            ("run-795-project-count", "我有几个项目"),
        ):
            _, run = await submit_message(
                db,
                conversation,
                KnowledgeRunSubmitRequest(
                    client_message_id=client_id,
                    message=message,
                    basis_mode="auto",
                ),
            )
            run.status = "processing"
            run.current_step = "claim"
            await db.commit()
            if message == "我有几个项目":
                expected_project_handle = f"rs-{conversation.id}-1"
            await execute_dialogue_loop_run(db, run)
            await db.commit()
            await db.refresh(run)
            saved_runs.append(run)

        run_793, run_794, run_795 = saved_runs
        failed_snapshot = json.loads(run_794.dialogue_loop_state_json)
        assert run_793.status == "completed"
        assert run_794.status == "failed"
        assert len(failed_snapshot["blocks"]) == 12
        assert failed_snapshot["tool_events"][-1]["tool"] == "fixture_material"
        invocations_794 = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run_794.id
                )
            )
        ).scalars().all()
        assert len(invocations_794) == 1
        assert run_795.status == "completed"
        assert "2 个项目" in json.loads(run_795.answer_json)["answer"]
        tool_calls_795 = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run_795.id
                )
            )
        ).scalars().all()
        assert [call.tool_name for call in tool_calls_795] == ["list_projects"]


@pytest.mark.asyncio
async def test_unhandled_validation_error_preserves_audit_and_continue_state(
    monkeypatch,
) -> None:
    """生产异常边界保存脱敏现场；显式“继续”仍恢复合法 continuation。"""
    from evals.dialogue_loop.core import DialogueAnswer
    from evals.dialogue_loop.instrumentation import InvocationLog

    async def get_text_model(_db, _workspace_id):
        return FunctionModel(
            lambda _messages, _info: None,
            model_name="unexpected-validation-fixture",
        )

    async def controlled_run_turn(_agent, state, message, history):
        if message == "整理候选":
            handle = state.store_result(
                "statistic",
                {"value": 3},
                "completed",
                "complete",
            )
            state.tool_events.append(
                {
                    "tool": "fixture_material",
                    "status": "completed",
                    "result_handle": handle,
                    "turn_index": state.turn_index,
                }
            )
            state.instrumentation.logs.append(
                InvocationLog(
                    kind="text",
                    provider="fixture",
                    model="unexpected-validation-fixture",
                    duration_ms=9,
                    usage=None,
                    error="模型输出结构校验失败",
                    error_kind="validation",
                )
            )
            state.continuation = ContinuationState(
                task_type="finalize_answer",
                tool_name="finalize_answer",
                scope={
                    "workspace_id": state.workspace_id,
                    "user_id": state.user_id,
                },
                pending_steps=[{"step": "finalize_answer"}],
                original_question=message,
                recoverable_material={
                    "mode": "grove_material",
                    "records": {},
                    "evidence": {},
                    "events": [],
                },
            )
            DialogueAnswer.model_validate({"blocks": []})
            raise AssertionError("空 blocks 应先触发 ValidationError")
        assert message == "继续"
        assert state.active_continuation is not None
        assert state.active_continuation.task_type == "finalize_answer"
        answer = "已恢复并完成。"
        completion = {"status": "completed", "can_continue": False}
        return (
            {
                "status": "completed",
                "answer": answer,
                "blocks": [{"kind": "text", "text": answer}],
                "completion": completion,
                "model_calls": [],
                "tool_calls": [],
                "error": None,
            },
            history,
        )

    monkeypatch.setattr("app.services.ai_models.get_text_model", get_text_model)
    monkeypatch.setattr(
        "app.services.knowledge_agent.production_adapter.run_turn",
        controlled_run_turn,
    )

    async with async_session_factory() as db:
        user = await create_user(db, "异常恢复")
        workspace = await create_workspace(db, user)
        conversation = await create_conversation(
            db,
            workspace.id,
            user.id,
            KnowledgeConversationCreate(scope_type="workspace"),
        )
        _, failed_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="unexpected-validation-1",
                message="整理候选",
            ),
        )
        failed_run.status = "processing"
        failed_run.current_step = "claim"
        await db.commit()
        await execute_dialogue_loop_run(db, failed_run)
        await db.commit()
        await db.refresh(failed_run)

        snapshot = json.loads(failed_run.dialogue_loop_state_json)
        assert failed_run.status == "failed"
        assert snapshot["diagnostic"] == {
            "code": "dialogue_loop_unhandled_exception",
            "exception_type": "ValidationError",
            "validation_errors": [
                {
                    "type": "too_short",
                    "loc": ["blocks"],
                    "msg": "List should have at least 1 item after validation, not 0",
                }
            ],
        }
        assert snapshot["blocks"][0]["kind"] == "insufficient"
        assert snapshot["tool_events"][0]["tool"] == "fixture_material"
        assert len(snapshot["model_calls"]) == 1
        assert snapshot["continuation"]["task_type"] == "finalize_answer"
        assert len(snapshot["records"]) == 1
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == failed_run.id
                )
            )
        ).scalars().all()
        assert len(invocations) == 1
        assert invocations[0].outcome == "model_call_failed"

        _, continued_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="unexpected-validation-2",
                message="继续",
            ),
        )
        continued_run.status = "processing"
        continued_run.current_step = "claim"
        await db.commit()
        await execute_dialogue_loop_run(db, continued_run)
        await db.commit()
        await db.refresh(continued_run)

        assert continued_run.status == "completed"
        assert "已恢复并完成" in json.loads(continued_run.answer_json)["answer"]
