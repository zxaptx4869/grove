"""220304 会话的跨层展示、实际派发与编辑对象确定性回归。"""

import json
from pathlib import Path

import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.db.session import async_session_factory
from app.models import Entry, WorkspaceMember
from evals.dialogue_loop import loop
from evals.dialogue_loop.core import DialogueAnswer
from evals.dialogue_loop.instrumentation import BudgetedModel, estimate_input_tokens
from tests.test_knowledge_agent_dialogue_loop import _seed_finalize_material, _state


def output(info, blocks):
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"blocks": blocks})])


def result_fixture():
    state = _state()
    projects = state.store_result("projects", {"projects": [
        {"id": 11, "name": "房子装修", "status": "active"},
        {"id": 12, "name": "空项目", "status": "active"},
    ]}, "completed", "complete", semantics={"subject": "projects"})
    grouped = state.store_result("statistic", {"buckets": [
        {"key": "11", "label": "房子装修", "count": 4},
        {"key": "12", "label": "空项目", "count": 0},
    ], "group_by": "project"}, "completed", "complete", semantics={
        "subject": "entries", "group_by": "project", "group_by_display_name": "项目",
    })
    answer = DialogueAnswer.model_validate({"blocks": [
        {"kind": "result", "result_handle": projects},
        # 第十轮失败形态：声明成列表的真实统计，不能让模型重复猜类型。
        {"kind": "list", "result_handle": grouped, "label": "随意标签"},
    ]})
    assert loop.output_errors(answer, state) == []
    return state, answer, loop.render_answer(answer, state)[1]


def test_backend_projection_matches_frontend_card_fixture():
    _, _, blocks = result_fixture()
    fixture = Path(__file__).parent / "fixtures/dialogue-workbench-result-blocks.json"
    assert blocks == json.loads(fixture.read_text())
    assert blocks[1]["buckets"][1]["count"] == 0


@pytest.mark.asyncio
async def test_finalizer_resolves_statistic_and_projects_without_tools():
    state, answer, blocks = result_fixture()
    state.instrumentation.context_policy_enabled = True
    calls = []

    def respond(messages, info):
        calls.append(info)
        assert not info.function_tools
        return output(info, answer.model_dump()["blocks"])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation)
    result = await loop._finalize_once(loop.build_finalizer_agent(model), state,
                                       "分项目统计，包含空项目", [], [], "test")
    assert loop.render_answer(result.output, state)[1] == blocks
    assert len(calls) == 1
    assert state.ledger.active_tool_calls == 0


@pytest.mark.parametrize("invalid", ["missing", "historical", "hidden", "error", "evidence"])
def test_generic_result_cannot_bypass_handle_boundaries(invalid):
    state = _state()
    handle = state.store_result("evidence" if invalid == "evidence" else "list",
                                {"items": [{"entry_id": 9, "title": "不能泄漏"}]},
                                "error" if invalid == "error" else "completed", "complete",
                                displayable=invalid != "hidden")
    if invalid == "historical":
        state.begin_turn(5, "新问题")
    if invalid == "missing":
        handle = "forged"
    answer = DialogueAnswer.model_validate(
        {"blocks": [{"kind": "result", "result_handle": handle}]}
    )
    assert loop.output_errors(answer, state)
    if invalid != "evidence":
        forged_source = DialogueAnswer.model_validate({"blocks": [
            {"kind": "evidence", "evidence_handle": handle},
        ]})
        assert loop.output_errors(forged_source, state)


@pytest.mark.asyncio
async def test_long_history_compacts_actual_full_request_and_next_topic_executes():
    state = _state()
    state.instrumentation.context_policy_enabled = True
    for index in range(35):
        state.turn_index = index
        state.remember_turn(f"历史问题{index}", "旧失败提示" * 1500, [], blocks=[
            {"kind": "text", "text": "甲" * 1200},
        ], completion={"status": "not_executed" if index < 29 else "completed"})
    state.begin_turn(60, "请精简当前稿")
    state.editing_active = True
    state.editing_content_only = True
    draft = {"blocks": [{"kind": "text", "text": "保留最新稿件" + "乙" * 3600}]}
    state.editing_context = loop.EditingContext(
        entry={"entry_id": 91, "title": "国标ENF"}, validation_refs={}, draft=draft,
        decisions=["仅修改 ENF，不扩展 E0；数值留待核验"],
    )
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        if len(calls) == 1:
            assert "乙" * 3600 in info.instructions
            assert "仅修改 ENF，不扩展 E0" in info.instructions
            assert "国标ENF" in info.instructions
            assert "旧失败提示" not in str(messages)
            return output(info, [{"kind": "text", "text": "ENF 候选正文"}])
        assert "乙" * 3600 not in info.instructions
        return output(info, [{"kind": "text", "text": "新话题回答"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, history = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == "completed"
    log = next(log for log in turn["model_calls"] if log["kind"] == "text")
    compression = log["estimate_components"]["history_compaction"]
    assert compression["before_tokens"] > 12000
    assert compression["removed_summaries"] > 0
    assert log["estimated_input_tokens"] <= 12000
    assert len(state.history_turns) == 36
    state.begin_turn(61, "抛开知识库，聊聊音乐")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, history)
    assert turn["status"] == "completed"
    assert len(calls) == 2
    assert len(state.history_turns) == 37
    assert state.editing_context.draft is not None


@pytest.mark.asyncio
async def test_required_user_decisions_cannot_be_silently_compressed():
    state = _state()
    state.instrumentation.context_policy_enabled = True
    state.editing_active = True
    state.editing_context = loop.EditingContext(
        entry={"entry_id": 91, "title": "ENF"}, validation_refs={},
        decisions=["不可省略的限制" * 4000],
    )
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return output(info, [{"kind": "text", "text": "不应执行"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, "精简", [])
    assert calls == []
    assert turn["status"] == "not_executed"
    assert "不可省略的限制" * 4000 == state.editing_context.decisions[0]


async def pin_seeded_entry(state):
    seeded = await _seed_finalize_material(state)
    state.focused_entry = next(record.payload["items"][0] for record in state.result_sets.values()
                               if record.kind == "entries")
    state.focused_entry_refs = await loop._database_material_refs(
        state, [seeded["entry_id"]], [(seeded["entry_id"], seeded["source_id"])])
    return seeded


@pytest.mark.asyncio
async def test_current_entry_draft_simplify_suspend_resume_end_to_end():
    state = _state()
    state.instrumentation.context_policy_enabled = True
    seeded = await pin_seeded_entry(state)
    state.focused_entry = None
    state.focused_entry_refs = None
    # 调用真实 open_list_item 路径固定当前对象，随后不重复资料读取。
    state.discovered_entry_ids.add(seeded["entry_id"])
    step = 0

    def respond(messages, info):
        nonlocal step
        step += 1
        if step == 1:
            return ModelResponse(parts=[ToolCallPart("open_list_item", {
                "result_set_handle": seeded["list_handle"], "position": 1,
            })])
        if step in {3, 5, 9}:
            return ModelResponse(parts=[ToolCallPart("editing_context", {
                "action": "resume" if step == 9 else "edit", "content_only": step != 3,
            })])
        if step == 2:
            return output(info, [{"kind": "text", "text": "当前只讨论第一条 ENF。"}])
        if step == 7:
            assert not state.editing_active
            assert state.candidate_draft is None
            return ModelResponse(parts=[ToolCallPart("list_projects", {})])
        if step == 8:
            assert not state.editing_active and state.candidate_draft is None
            handle = state.tool_events[-1]["result_handle"]
            assert state.result_sets[handle].kind == "projects"
            assert state.editing_context.draft is not None
            return output(info, [{"kind": "result", "result_handle": handle}])
        task = state.editing_context
        assert task.entry["entry_id"] == seeded["entry_id"]
        assert "国标" in task.entry["title"]
        text = "原记录 ENF；建议补充检测条件。这是候选稿，尚未写入，补充不属于来源原文。"
        if step >= 6:
            assert task.draft is not None
            text = "ENF 修改后候选正文"
        return output(info, [{"kind": "text", "text": text}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    agent = loop.build_agent(model)
    history = []
    for i, message in enumerate([
        "第一条说的是什么", "按你的分析，帮我补充一下知识，发给我",
        "只输出修改后候选版本即可，其他不用", "先查询其他主题", "回到原稿再精简",
    ]):
        state.begin_turn(100 + i, message)
        turn, history = await loop.run_turn(agent, state, message, history)
        assert turn["status"] == "completed", turn
        assert state.continuation is None
        if i == 3:
            assert "房子装修" in turn["answer"]
            assert "记录1" not in turn["answer"]
    assert state.editing_context.entry["entry_id"] == seeded["entry_id"]
    assert len(state.editing_context.decisions) == 3
    assert "ENF 修改后候选正文" in str(state.editing_context.draft)
    async with async_session_factory() as db:
        entry = await db.get(Entry, seeded["entry_id"])
        assert entry.content == seeded["content"]


@pytest.mark.parametrize("mutation", ["permission", "content", "authorization"])
@pytest.mark.asyncio
async def test_return_to_draft_revalidates_permission_and_material(mutation):
    state = _state()
    seeded = await pin_seeded_entry(state)
    await loop.select_editing_context(state, "edit")
    await loop.select_editing_context(state, "suspend")
    if mutation == "authorization":
        state.authorized_entry_ids.clear()
    else:
        async with async_session_factory() as db:
            if mutation == "content":
                entry = await db.get(Entry, seeded["entry_id"])
                entry.content = "已经改变"
            else:
                from sqlalchemy import delete
                await db.execute(delete(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == seeded["workspace_id"],
                    WorkspaceMember.user_id == seeded["user_id"],
                ))
            await db.commit()
    with pytest.raises(ModelRetry):
        await loop.select_editing_context(state, "resume")
    assert state.editing_active is False
    assert state.candidate_draft is None


def test_failed_histories_do_not_accumulate_model_error_notices():
    state = _state()
    for _ in range(40):
        state.remember_turn("短问题", "重复错误" * 1000, [], blocks=[
            {"kind": "insufficient", "text": "重复错误" * 1000},
        ], completion={"status": "not_executed"})
    history = loop.build_compact_history(state)
    assert "重复错误" not in str(history)
    assert estimate_input_tokens(history) < 2000
    assert len(state.history_turns) == 40


@pytest.mark.asyncio
async def test_editing_draft_continuation_and_new_topic_do_not_mix():
    state = _state()
    state.instrumentation.context_policy_enabled = True
    await pin_seeded_entry(state)
    state.current_message = "只输出修改后版本"
    await loop.select_editing_context(state, "edit", content_only=True)
    draft = DialogueAnswer.model_validate({"blocks": [{"kind": "text", "text": "ENF 候选原稿"}]})
    state.candidate_draft = draft.model_dump()
    loop.preserve_editing_draft(state, draft)
    calls = []

    def respond(messages, info):
        calls.append((messages, info))
        assert not info.function_tools
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("read_evidence", {})])
        assert "ENF 候选原稿" in str(messages)
        return output(info, [{"kind": "text", "text": "ENF 精简稿"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    finalizer = loop.build_finalizer_agent(model)
    from evals.dialogue_loop.instrumentation import FinalizeToolAttempted
    with pytest.raises(FinalizeToolAttempted):
        await loop._finalize_once(finalizer, state, state.current_message, [], [], "test")
    assert await loop._attach_finalize_continuation(state, state.current_message, [])
    assert state.continuation.scope["editing_content_only"] is True
    state.begin_turn(61, "继续")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, "继续", [], finalizer)
    assert turn["status"] == "completed"
    assert turn["context"]["continuation_mode"] == "finalize_only"
    assert state.continuation is None
    assert "ENF 精简稿" in str(state.editing_context.draft)
    state.begin_turn(62, "新话题")
    assert not state.editing_active and state.candidate_draft is None
    assert state.active_continuation is None
    assert "ENF 精简稿" in str(state.editing_context.draft)
    await loop.select_editing_context(state, "resume", content_only=True)
    assert "ENF 精简稿" in str(state.candidate_draft)
    assert len(calls) == 2


def test_result_entry_reference_renders_body_without_guessing_type():
    state = _state()
    handle = state.store_result("entries", {"items": [
        {"entry_id": i, "title": f"记录{i}", "content": f"正文{i}"} for i in range(20)
    ]}, "completed", "complete")
    answer = DialogueAnswer.model_validate({"blocks": [
        {"kind": "result", "result_handle": handle},
    ]})
    assert loop.output_errors(answer, state) == []
    _, blocks = loop.render_answer(answer, state)
    assert len(blocks) == 20
    assert all(block["kind"] == "entry" for block in blocks)
    assert blocks[-1]["content"] == "正文19"


@pytest.mark.asyncio
async def test_real_group_query_includes_empty_project_and_suspends_draft():
    from app.models import Project

    state = _state()
    state.instrumentation.context_policy_enabled = True
    await pin_seeded_entry(state)
    async with async_session_factory() as db:
        db.add(Project(workspace_id=state.workspace_id, name="空项目"))
        await db.commit()
    await loop.select_editing_context(state, "edit", content_only=True)
    loop.preserve_editing_draft(state, DialogueAnswer.model_validate({"blocks": [
        {"kind": "text", "text": "旧 ENF 候选稿"},
    ]}))
    state.current_message = "换个问题，分项目统计，包含空项目"
    calls = []

    def respond(messages, info):
        calls.append(info)
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("group_entries", {
                "project_scope": "all", "project_name": None, "group_by": "project",
            })])
        assert not state.editing_active and not state.editing_content_only
        assert state.candidate_draft is None
        handle = state.tool_events[-1]["result_handle"]
        return output(info, [{"kind": "list", "result_handle": handle, "label": "列表"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == "completed", turn
    assert turn["blocks"][0]["result_type"] == "statistic"
    buckets = {item["label"]: item["count"] for item in turn["blocks"][0]["buckets"]}
    assert buckets == {"房子装修": 1, "空项目": 0}
    assert "旧 ENF 候选稿" in str(state.editing_context.draft)
    assert len(calls) == 2
