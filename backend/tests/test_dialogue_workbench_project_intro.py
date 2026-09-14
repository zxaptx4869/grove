"""104716 会话：真实项目快照、纯文本交付与授权前预算停止。"""

import json
from datetime import UTC, datetime

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models import Entry, Project, ProjectContext, WorkspaceMember
from evals.dialogue_loop import loop
from evals.dialogue_loop.instrumentation import BudgetedModel, estimate_input_tokens
from evals.dialogue_loop.project_material import read_project_material
from tests.test_dialogue_workbench_continuity import output
from tests.test_knowledge_agent_dialogue_loop import _seed_finalize_material, _state


async def project_state(with_context=True):
    state = _state()
    seed = await _seed_finalize_material(state)
    async with async_session_factory() as db:
        entry = await db.get(Entry, seed["entry_id"])
        project = await db.get(Project, entry.project_id)
        project.description = "给父母改造旧居，目标是减少台阶，预算优先保障安全。"
        if with_context:
            db.add(ProjectContext(
                project_id=project.id, project_summary="过时的自动摘要",
                current_focus="旧重点", user_corrections=json.dumps({
                    "project_summary": "适老化改造项目", "current_focus": "确认浴室防滑方案",
                }, ensure_ascii=False), status="ready", version=3,
                generated_at=datetime(2026, 9, 1, tzinfo=UTC), is_fallback=True,
                provider="demo", model="deterministic", refresh_due_at=None,
            ))
        await db.commit()
        seed["project_id"] = project.id
    state.begin_turn(5, "总结房子装修项目")
    state.instrumentation.context_policy_enabled = True
    return state, seed


@pytest.mark.asyncio
@pytest.mark.parametrize("with_context", [True, False])
async def test_project_read_has_no_generation_or_write_side_effect(with_context):
    state, seed = await project_state(with_context)
    async with async_session_factory() as db:
        before = (await db.scalars(select(ProjectContext))).all()
        before_values = [(r.id, r.version, r.status, r.refresh_due_at) for r in before]
    material = await read_project_material(state.workspace_id, state.user_id, "房子装修")
    assert "给父母" in material["user_description"]
    if with_context:
        ctx = material["saved_context"]
        assert ctx["project_summary"] == "适老化改造项目"
        assert ctx["current_focus"] == "确认浴室防滑方案"
        assert ctx["is_fallback"] and ctx["provider"] == "demo"
        assert ctx["version"] == 3 and not ctx["refresh_pending"]
    else:
        assert material["saved_context"] is None
    async with async_session_factory() as db:
        after = (await db.scalars(select(ProjectContext))).all()
        assert [(r.id, r.version, r.status, r.refresh_due_at) for r in after] == before_values
        assert (await db.get(Entry, seed["entry_id"])).content == seed["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["other_workspace", "revoked", "ambiguous"])
async def test_project_reader_rejects_invalid_scope(invalid):
    state, seed = await project_state()
    if invalid == "other_workspace":
        other, _ = await project_state()
        state.workspace_id = other.workspace_id
    else:
        async with async_session_factory() as db:
            if invalid == "revoked":
                await db.execute(delete(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == state.workspace_id,
                ))
            else:
                db.add(Project(workspace_id=state.workspace_id, name="房子装修"))
            await db.commit()
    with pytest.raises(ValueError):
        await read_project_material(state.workspace_id, state.user_id, "房子装修")


@pytest.mark.asyncio
async def test_project_intro_and_prose_followup_use_only_needed_tools():
    state, seed = await project_state()
    calls = []
    prose = "这是给父母改造旧居的适老化项目，优先保障安全，目前关注浴室防滑。上下文为已存摘要。"

    def respond(messages, info):
        calls.append(info)
        assert "介绍具体项目用 read_project_context" in info.instructions
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("read_project_context", {
                "project_name": "房子装修",
            })])
        if len(calls) == 2:
            assert "给父母改造旧居" in str(messages)
            assert "确认浴室防滑方案" in str(messages)
            assert "过时的自动摘要" not in str(messages)
        return output(info, [{"kind": "text", "text": prose}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    agent = loop.build_agent(model)
    turn, history = await loop.run_turn(agent, state, state.current_message, [])
    assert turn["status"] == "completed", turn
    assert [t["tool"] for t in turn["tool_calls"]] == ["read_project_context"]
    assert turn["blocks"] == [{"kind": "text", "text": prose}]
    state.begin_turn(6, "用文本概括就行")
    turn, _ = await loop.run_turn(agent, state, state.current_message, history)
    assert turn["status"] == "completed", turn
    assert turn["tool_calls"] == [] and len(calls) == 3
    assert all(b["kind"] == "text" for b in turn["blocks"])


@pytest.mark.asyncio
async def test_context_result_projects_to_text_and_rejects_stale_handle():
    state, _ = await project_state()
    payload = await read_project_material(state.workspace_id, state.user_id, "房子装修")
    handle = state.store_result("project_context", payload, "completed", "complete")
    answer = loop.DialogueAnswer.model_validate({"blocks": [{
        "kind": "result", "result_handle": handle,
    }]})
    assert loop.output_errors(answer, state) == []
    text, blocks = loop.render_answer(answer, state)
    assert "给父母" in text and "降级" in text
    assert all(b["kind"] == "text" for b in blocks)
    state.begin_turn(6, "新话题")
    assert loop.output_errors(answer, state)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "description", "context", "permission"])
async def test_project_finalize_continuation_revalidates_material(change):
    state, seed = await project_state()
    payload = await read_project_material(state.workspace_id, state.user_id, "房子装修")
    handle = state.store_result("project_context", payload, "completed", "complete")
    events = [{"tool": "read_project_context", "result_handle": handle, "status": "completed"}]
    state.instrumentation.finalize_status = "invalid_output"
    continuation = await loop._create_finalize_continuation(state, state.current_message, events)
    async with async_session_factory() as db:
        if change == "description":
            (await db.get(Project, seed["project_id"])).description = "新目标"
        elif change == "context":
            context = await db.scalar(select(ProjectContext).where(
                ProjectContext.project_id == seed["project_id"],
            ))
            context.user_corrections = '{"current_focus":"新决定"}'
        elif change == "permission":
            await db.execute(delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == state.workspace_id,
            ))
        await db.commit()
    valid, reason = await loop._validate_finalize_continuation(state, continuation)
    assert valid == (change == "none"), reason


def fake_search(monkeypatch, state, *, padding=0):
    dispatches = []

    async def dispatch(ctx, tool_name, params, kind, **kwargs):
        await state.ledger.reserve_tool()
        dispatches.append(params)
        payload = {"items": [{"entry_id": 7, "title": "洗碗机安装要点"}],
                   "has_more": False, "returned_count": 1}
        if padding:
            payload["necessary_material"] = "不可裁剪的本轮查询约束" * padding
        handle = state.store_result("list", payload, "limited", "limited", displayable=False,
                                    semantics={"result_role": "candidate"})
        event = {"tool": "search_knowledge", "result_handle": handle, "status": "limited",
                 "turn_index": state.turn_index, "params": params,
                 "result_summary": {"has_more": False, "returned_count": 1}}
        state.tool_events.append(event)
        return {**event, "payload": payload}

    monkeypatch.setattr(loop, "_dispatch", dispatch)
    return dispatches


@pytest.mark.asyncio
async def test_pending_search_at_real_soft_boundary_is_partial_without_old_results(monkeypatch):
    state = _state()
    state.instrumentation.context_policy_enabled = True
    old = state.store_result("statistic", {"value": 92}, "completed", "complete")
    state.remember_turn("旧项目统计", "旧材料不应冒充当前结果", [{
        "tool": "count_entries", "result_handle": old, "status": "completed",
    }], blocks=[{"kind": "statistic", "handle": old}], completion={"status": "completed"})
    state.begin_turn(6, "里面有洗碗机知识吗")
    dispatches = fake_search(monkeypatch, state, padding=450)
    calls = []

    def respond(messages, info):
        calls.append(info)
        assert info.function_tools
        return ModelResponse(parts=[ToolCallPart("search_knowledge", {
            "project_scope": "project", "project_name": "房子装修", "query": "洗碗机",
        })])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == "partial_completed", turn
    assert turn["completion"]["reason_code"] == "relevance_selection_pending"
    assert "搜索已执行" in turn["answer"] and "尚未完成" in turn["answer"]
    assert "92" not in turn["answer"] and "洗碗机安装要点" not in turn["answer"]
    assert not turn["completion"]["can_continue"] and state.continuation is None
    assert len(dispatches) == len(calls) == 1
    transition = next(m for m in turn["model_calls"] if m["kind"] == "finalize_transition")
    assert transition["projected_input_tokens"] >= 9000
    assert not turn["finalization"]["attempted"]


@pytest.mark.asyncio
async def test_long_structured_history_search_select_and_new_topic_execute(monkeypatch):
    state = _state()
    state.instrumentation.context_policy_enabled = True
    # 保存真实形状的大量历史工具数据与叙述，不通过降低预算来假触发压缩。
    for i in range(20):
        handle = state.store_result("statistic", {"buckets": [
            {"key": str(j), "label": "旧统计桶" * 15, "count": j} for j in range(30)
        ]}, "completed", "complete")
        state.remember_turn(f"历史问题{i}", "旧结论" * 400, [{
            "tool": "group_entries", "result_handle": handle, "status": "completed",
        }], blocks=[{"kind": "text", "text": "旧结论" * 400}],
            completion={"status": "completed"})
    state.begin_turn(6, "项目里有洗碗机知识吗")
    assert len(json.dumps(state.history_turns, ensure_ascii=False)) > 40000
    dispatches = fake_search(monkeypatch, state)
    calls = []

    def respond(messages, info):
        calls.append(info)
        assert "旧统计桶" not in str(messages)
        assert info.function_tools
        if len(calls) == 1:
            return ModelResponse(parts=[ToolCallPart("search_knowledge", {
                "project_scope": "project", "project_name": "房子装修", "query": "洗碗机",
            })])
        if len(calls) == 2:
            candidate = next(iter(loop._pending_semantic_candidates(state)))
            return ModelResponse(parts=[ToolCallPart("select_relevant_entries", {
                "candidate_result_handle": candidate,
                "classifications": [{"entry_id": 7, "relevance": "direct", "reason": "直接相关"}],
            })])
        if len(calls) == 3:
            authorized = next(r.handle for r in loop._reliable_current_records(state))
            return output(info, [{"kind": "result", "result_handle": authorized}])
        return output(info, [{"kind": "text", "text": "新话题回答"}])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    agent = loop.build_agent(model)
    turn, history = await loop.run_turn(agent, state, state.current_message, [])
    assert turn["status"] == "completed", json.dumps(turn["model_calls"], ensure_ascii=False)
    assert "洗碗机安装要点" in turn["answer"] and len(dispatches) == 1
    assert [e["tool"] for e in turn["tool_calls"]] == [
        "search_knowledge", "select_relevant_entries",
    ]
    logs = [m for m in turn["model_calls"] if m["kind"] == "text"]
    assert any(m["estimate_components"]["history_compaction"]["removed_summaries"] > 0
               for m in logs)
    assert all(m["estimated_input_tokens"] < 9000 for m in logs)
    state.begin_turn(7, "不查知识库，聊聊音乐")
    turn, _ = await loop.run_turn(agent, state, state.current_message, history)
    assert turn["status"] == "completed" and turn["tool_calls"] == []
    assert len(calls) == 4 and len(state.history_turns) == 22


def test_finalizer_history_does_not_replay_old_statistics():
    state = _state()
    old = ModelRequest(parts=[UserPromptPart(content="旧项目统计92条" * 50)])
    history = loop._current_material_history(state, "查新主题", [old], [])
    assert "旧项目统计" not in str(history)
    assert estimate_input_tokens(history) < 300


@pytest.mark.asyncio
async def test_failed_project_answer_continues_with_no_material_tools():
    state, _ = await project_state()
    solve_calls = []
    finalize_calls = []

    def solve(messages, info):
        solve_calls.append(info)
        if len(solve_calls) == 1:
            return ModelResponse(parts=[ToolCallPart("read_project_context", {
                "project_name": "房子装修",
            })])
        raise loop.FinalizeRequired("text_request_budget")

    def finalize(messages, info):
        finalize_calls.append(info)
        assert not info.function_tools
        assert "项目介绍使用背景目标和已保存上下文，以自然段概括" in info.instructions
        assert "确认浴室防滑方案" in str(messages)
        if len(finalize_calls) == 1:
            raise RuntimeError("确定性收尾故障")
        return output(info, [{"kind": "text", "text": "这是适老化改造项目，关注浴室防滑。"}])

    agent = loop.build_agent(BudgetedModel(FunctionModel(solve), state.instrumentation))
    finalizer = loop.build_finalizer_agent(
        BudgetedModel(FunctionModel(finalize), state.instrumentation)
    )
    turn, history = await loop.run_turn(agent, state, state.current_message, [], finalizer)
    assert turn["status"] == "partial_completed", turn
    assert turn["completion"]["can_continue"]
    assert state.continuation.task_type == "finalize_answer"
    state.begin_turn(6, "继续")
    turn, _ = await loop.run_turn(agent, state, state.current_message, history, finalizer)
    assert turn["status"] == "completed", turn
    assert turn["tool_calls"] == [] and len(solve_calls) == 2
    assert len(finalize_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed"])
async def test_project_non_ready_snapshot_keeps_status_without_refresh(status):
    state, seed = await project_state()
    async with async_session_factory() as db:
        context = await db.scalar(select(ProjectContext).where(
            ProjectContext.project_id == seed["project_id"],
        ))
        context.status = status
        context.refresh_due_at = datetime(2026, 9, 14, tzinfo=UTC)
        await db.commit()
    material = await read_project_material(state.workspace_id, state.user_id, "房子装修")
    assert material["saved_context"]["status"] == status
    assert material["saved_context"]["refresh_pending"]
    assert material["saved_context"]["project_summary"] == "适老化改造项目"


def test_part_compaction_keeps_protected_parts_and_tool_pairs():
    from pydantic_ai.messages import TextPart, ToolReturnPart
    from pydantic_ai.models import ModelRequestParameters

    from evals.dialogue_loop.instrumentation import compact_request_history

    # 模拟框架合并后消息级 metadata 已丢失，必要对象与可删叙述在同一消息内。
    protected = TextPart("当前对象：Entry 7；用户决定：只讨论安装")
    request = ModelRequest(parts=[UserPromptPart("当前问题必须保留")], instructions="当前规则")
    history = [ModelResponse(parts=[
        protected, TextPart("旧话题" * 4000, provider_name="grove-history",
                            provider_details={"optional_history": True}),
        ToolCallPart("search_knowledge", {"query": "洗碗机"}, tool_call_id="search"),
    ]), ModelRequest(parts=[ToolReturnPart("search_knowledge", {"items": [7]},
                                          tool_call_id="search")]), request]
    result, metrics = compact_request_history(history, ModelRequestParameters())
    assert metrics["before_tokens"] > 12000
    assert metrics["after_tokens"] < 9000 and metrics["removed_summaries"] == 1
    assert result[0].parts[0] == protected
    assert result[0].parts[1].tool_call_id == result[1].parts[0].tool_call_id == "search"
    assert result[-1] == request
