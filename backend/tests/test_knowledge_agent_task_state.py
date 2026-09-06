"""任务归并、恢复、实体绑定与失败边界的数据库回归。"""

import json

import pytest

from app.agents.dialogue_task import QueryTaskDeltaDraft, TaskDecisionDraft
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import KnowledgeConversation, KnowledgeMessage
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.task_state import (
    TaskStateError,
    finalize_task,
    load_task_dialogue,
    merge_query_delta,
    read_state,
    select_task,
    verify_task_project,
    write_state,
)
from tests._knowledge_agent_fixtures import create_project, create_user, create_workspace


@pytest.fixture(autouse=True)
def task_protocol(monkeypatch):
    monkeypatch.setattr(get_settings(), "knowledge_agent_task_state_enabled", True)


async def conversation(db):
    user = await create_user(db)
    workspace = await create_workspace(db, user)
    item = KnowledgeConversation(
        workspace_id=workspace.id, owner_user_id=user.id, scope_type="workspace", title="任务测试"
    )
    db.add(item)
    await db.flush()
    return item, workspace


async def begin(db, item, message, *, mode="auto"):
    _, run = await submit_message(
        db,
        item,
        KnowledgeRunSubmitRequest(
            client_message_id=f"task-{message}",
            message=message,
            context_mode=mode,
        ),
    )
    await load_task_dialogue(db, run)
    return run


async def select_frame(db, run, operation="start", handle=None, **kwargs):
    message = await db.get(KnowledgeMessage, run.user_message_id)
    return await select_task(
        db,
        run,
        TaskDecisionDraft(
            operation=operation,
            task_handle=handle,
            topic_label="统计",
            standalone_query=message.content,
            **kwargs,
        ),
        message.content,
    )


def delta(message, changes=None, *, outputs=None):
    return QueryTaskDeltaDraft.model_validate(
        {
            "changes": [dict(change, source="current", quote=message) for change in changes or []],
            "outputs": outputs,
            "output_quote": message if outputs else "",
        }
    )


async def complete(db, run, *, usable=True):
    finalize_task(run, usable=usable)
    run.status = "completed" if usable else "failed"
    run.active_slot = None
    run.context_decision = "new_topic" if read_state(run).operation == "start" else "continue"
    await db.flush()


@pytest.mark.asyncio
async def test_replace_clear_branch_resume_and_scope_grounding():
    async with async_session_factory() as db:
        item, workspace = await conversation(db)
        project = await create_project(db, workspace, "房子装修")
        first = await begin(db, item, "统计全部知识总数")
        await select_frame(db, first)
        merge_query_delta(first, delta("统计全部知识总数", outputs=[{"kind": "count"}]))
        root = read_state(first).frame.handle
        await complete(db, first)

        child = await begin(db, item, "其中房子装修的方法有多少")
        state, _ = await select_frame(db, child, "branch", root, project_mentions=["房子装修"])
        assert state.input["projects"] == [{"name": "房子装修", "status": "unique"}]
        plan = merge_query_delta(
            child,
            delta(
                "其中房子装修的方法有多少",
                [
                    {"field": "project_name", "operation": "set", "value": "房子装修"},
                    {"field": "main_types", "operation": "set", "value": ["method"]},
                ],
            ),
        )
        await verify_task_project(db, child, plan)
        assert read_state(child).frame.binding.project_id == project.id
        child_handle = read_state(child).frame.handle
        await complete(db, child)

        changed = await begin(db, item, "改成参数，其他不变")
        await select_frame(db, changed, "continue", child_handle)
        plan = merge_query_delta(
            changed,
            delta(
                "改成参数，其他不变",
                [
                    {"field": "main_types", "operation": "set", "value": ["parameter"]},
                ],
            ),
        )
        assert plan.entry_set.main_types == ["parameter"]
        assert plan.entry_set.project_name == "房子装修"
        assert plan.outputs[0].kind == "count"
        await complete(db, changed)

        cleared = await begin(db, item, "取消类型限制")
        await select_frame(db, cleared, "continue", child_handle)
        plan = merge_query_delta(
            cleared,
            delta(
                "取消类型限制",
                [
                    {"field": "main_types", "operation": "clear"},
                ],
            ),
        )
        assert plan.entry_set.main_types == []
        assert plan.entry_set.project_name == "房子装修"
        await complete(db, cleared)

        resumed = await begin(db, item, "回到全部项目统计，按项目分组")
        await select_frame(db, resumed, "resume", root)
        plan = merge_query_delta(
            resumed,
            delta(
                "回到全部项目统计，按项目分组",
                outputs=[{"kind": "group_count", "group_by": "project"}],
            ),
        )
        assert plan.entry_set.project_name is None
        assert plan.entry_set.main_types == []
        assert read_state(resumed).statement_message_ids == [first.user_message_id]


@pytest.mark.asyncio
async def test_pause_resume_preserves_only_selected_basis_and_messages():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        query = await begin(db, item, "统计方法数量")
        await select_frame(db, query)
        merge_query_delta(
            query,
            delta(
                "统计方法数量",
                [
                    {"field": "main_types", "operation": "set", "value": ["method"]},
                ],
                outputs=[{"kind": "count"}],
            ),
        )
        root = read_state(query).frame.handle
        await complete(db, query)
        aside = await begin(db, item, "只用通用知识解释番茄工作法，不查知识库")
        await select_frame(db, aside, basis="no_grove", basis_quote="不查知识库")
        await complete(db, aside)
        resumed = await begin(db, item, "回到刚才的方法统计")
        state, _ = await select_frame(db, resumed, "resume", root)
        assert state.frame.basis == "auto"
        assert aside.user_message_id not in state.statement_message_ids
        assert query.user_message_id in state.statement_message_ids


@pytest.mark.asyncio
async def test_failed_candidate_and_clarification_do_not_replace_committed_state():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        first = await begin(db, item, "统计方法")
        await select_frame(db, first)
        merge_query_delta(
            first,
            delta(
                "统计方法",
                [
                    {"field": "main_types", "operation": "set", "value": ["method"]},
                ],
                outputs=[{"kind": "count"}],
            ),
        )
        root = read_state(first).frame.handle
        await complete(db, first)
        failed = await begin(db, item, "改成提醒")
        await select_frame(db, failed, "continue", root)
        merge_query_delta(
            failed,
            delta(
                "改成提醒",
                [
                    {"field": "main_types", "operation": "set", "value": ["reminder"]},
                ],
            ),
        )
        await complete(db, failed, usable=False)
        follow = await begin(db, item, "刚才统计呢")
        state, _ = await select_frame(db, follow, "continue", root)
        assert state.frame.plan["entry_set"]["main_types"] == ["method"]
        assert state.input["pending"]["request"] == "改成提醒"
        merge_query_delta(follow, QueryTaskDeltaDraft(clarify_question="统计方法还是提醒？"))
        finalize_task(follow, usable=False, clarification="统计方法还是提醒？")
        follow.status, follow.active_slot = "completed", None
        await db.flush()
        reply = await begin(db, item, "方法")
        assert read_state(reply).input["pending"]["question"] == "统计方法还是提醒？"


@pytest.mark.asyncio
async def test_hard_reset_and_foreign_task_handles_rejected():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        first = await begin(db, item, "旧任务")
        await select_frame(db, first)
        root = read_state(first).frame.handle
        await complete(db, first)
        reset = await begin(db, item, "新任务", mode="new_topic")
        assert read_state(reset).pool == []
        with pytest.raises(TaskStateError, match="不可用"):
            await select_frame(db, reset, "resume", root)
        with pytest.raises(TaskStateError, match="不可用"):
            await select_frame(db, reset, "resume", "t999999")
        await select_frame(db, reset)
        await complete(db, reset)
        current = await begin(db, item, "恢复旧任务")
        assert root not in {f.handle for f in read_state(current).pool}


@pytest.mark.asyncio
async def test_project_replacement_same_name_cannot_hijack_restored_task():
    async with async_session_factory() as db:
        item, workspace = await conversation(db)
        original = await create_project(db, workspace, "同名")
        run = await begin(db, item, "统计同名项目")
        await select_frame(db, run, project_mentions=["同名"])
        plan = merge_query_delta(
            run,
            delta(
                "统计同名项目",
                [
                    {"field": "project_name", "operation": "set", "value": "同名"},
                ],
                outputs=[{"kind": "count"}],
            ),
        )
        await verify_task_project(db, run, plan)
        original.name = "已经改名"
        await create_project(db, workspace, "同名")
        await db.flush()
        with pytest.raises(TaskStateError, match="同名"):
            await verify_task_project(db, run, plan)


@pytest.mark.asyncio
async def test_current_message_budget_is_checked_after_task_selection(monkeypatch):
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        run = await begin(db, item, "统计全部知识")
        monkeypatch.setattr(get_settings(), "knowledge_agent_task_context_bytes", 4000)
        with pytest.raises(TaskStateError, match="预算"):
            await select_task(
                db,
                run,
                TaskDecisionDraft(operation="start", topic_label="统计", standalone_query="统计"),
                "统计" * 2000,
            )


@pytest.mark.asyncio
async def test_scope_boundary_and_foreign_persisted_frame_are_excluded():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        foreign_item, _ = await conversation(db)
        foreign = await begin(db, foreign_item, "外部任务")
        await select_frame(db, foreign)
        await complete(db, foreign)
        local = await begin(db, item, "本地任务")
        await select_frame(db, local)
        await complete(db, local)
        state = read_state(local)
        state.pool.append(read_state(foreign).frame)
        write_state(local, state)
        current = await begin(db, item, "继续本地")
        assert [f.handle for f in read_state(current).pool] == [read_state(local).frame.handle]
        await select_frame(db, current, "continue", read_state(local).frame.handle)
        await complete(db, current)
        db.add(
            KnowledgeMessage(
                conversation_id=item.id,
                role="system",
                message_type="scope_change",
                content="切换范围",
                scope_type="workspace",
            )
        )
        await db.flush()
        changed = await begin(db, item, "范围切换后继续")
        assert read_state(changed).pool == []


@pytest.mark.asyncio
async def test_literal_project_candidates_are_scoped_bounded_and_not_filters():
    async with async_session_factory() as db:
        item, workspace = await conversation(db)
        _, foreign_workspace = await conversation(db)
        await create_project(db, workspace, "甲计划")
        await create_project(db, foreign_workspace, "外部计划")
        run = await begin(db, item, "不限定甲计划，统计全部项目，包括外部计划吗")
        state, _ = await select_frame(db, run)
        assert state.input["projects"] == [{"name": "甲计划", "status": "unique"}]
        plan = merge_query_delta(run, delta("统计全部项目", outputs=[{"kind": "count"}]))
        assert plan.entry_set.project_name is None
        await complete(db, run)
        for i in range(6):
            await create_project(db, workspace, f"项目{i}")
        crowded = await begin(db, item, "项目0项目1项目2项目3项目4项目5")
        with pytest.raises(TaskStateError, match="上限"):
            await select_frame(db, crowded)


@pytest.mark.asyncio
async def test_empty_display_replaces_reference_and_cancellation_keeps_previous_state():
    from app.services.knowledge_agent.runs import finalize_cancelled

    async with async_session_factory() as db:
        item, _ = await conversation(db)
        first = await begin(db, item, "列出记录")
        await select_frame(db, first)
        first.entry_result_json = json.dumps(
            {
                "schema_version": "v1",
                "items": [
                    {"entry_id": 1, "title": "旧条目"},
                ],
            }
        )
        await complete(db, first)
        empty = await begin(db, item, "列出空集合")
        await select_frame(db, empty, "continue", read_state(first).frame.handle)
        empty.entry_result_json = json.dumps(
            {
                "schema_version": "v2",
                "items": [],
                "output_completeness": {"entries": "complete"},
            }
        )
        await complete(db, empty)
        current = await begin(db, item, "第一条")
        with pytest.raises(TaskStateError, match="序号"):
            await select_frame(
                db, current, "continue", read_state(first).frame.handle, result_position=1
            )
        await select_frame(db, current)
        await finalize_cancelled(db, current)
        follow = await begin(db, item, "接着来")
        assert [f.handle for f in read_state(follow).pool] == [read_state(first).frame.handle]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["context", "query", "nature"])
@pytest.mark.parametrize("always_invalid", [False, True])
async def test_model_output_repair_is_bounded_and_observable(monkeypatch, stage, always_invalid):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from app.agents import knowledge_context, structured_query

    calls = []

    def respond(messages, info):
        calls.append(messages)
        invalid = always_invalid or len(calls) == 1
        if stage == "context":
            output = TaskDecisionDraft(
                operation="resume",
                task_handle="t999" if invalid else "t1",
                topic_label="统计",
                standalone_query="按项目分组",
            ).model_dump()
        else:
            assert "不应进入输入的旧改写" not in str(messages)
            output = delta(
                "不属于原话" if invalid and stage == "query" else "按项目分组",
                changes=[{"field": "info_natures", "operation": "set", "value": ["fact"]}]
                if invalid and stage == "nature"
                else None,
                outputs=[{"kind": "group_count", "group_by": "project"}],
            ).model_dump()
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, output)])

    async def model(db, workspace_id):
        return FunctionModel(respond)

    context = {
        "protocol": "dialogue_task_v1",
        "tasks": [{"handle": "t1"}],
        "current_message": "按项目分组",
        "history": [],
    }
    if stage == "context":
        monkeypatch.setattr(knowledge_context, "get_text_model", model)
        result, meta = await knowledge_context.run_context_decision_agent(
            None,
            1,
            current_message="按项目分组",
            active_topic_label=None,
            working_set_titles=[],
            history=[],
            task_context=context,
        )
        if not always_invalid:
            assert result.task_handle == "t1"
    else:
        monkeypatch.setattr(structured_query, "get_text_model", model)
        result, meta = await structured_query.run_structured_query_planner(
            None,
            1,
            objective="不应进入输入的旧改写",
            scope_label="工作区",
            task_context=context,
        )
        if not always_invalid:
            assert result.output_quote == "按项目分组"
    assert len(calls) == 2
    assert meta.is_fallback is always_invalid
    if not always_invalid:
        assert meta.usage["requests"] == 2


@pytest.mark.asyncio
async def test_ui_project_is_a_trusted_entity_source_without_name_in_message():
    async with async_session_factory() as db:
        item, workspace = await conversation(db)
        project = await create_project(db, workspace, "界面项目")
        item.scope_type, item.project_id = "project", project.id
        run = await begin(db, item, "当前项目有多少条")
        state, _ = await select_frame(db, run, project_mentions=["界面项目"])
        assert state.input["projects"] == [{"name": "界面项目", "status": "unique"}]
        assert run.project_id == project.id


@pytest.mark.parametrize(
    "value,quote",
    [
        ("fact", "只统计事实类"),
        ("experience", "只统计经验"),
        ("advice", "性质是建议"),
        ("speculation", "推测性质"),
        ("other", "性质为其他"),
        ("unspecified", "未指定信息性质的记录"),
    ],
)
def test_explicit_info_nature_filters_remain_supported(value, quote):
    from app.agents.dialogue_task import validate_info_nature_source

    draft = delta(quote, [{"field": "info_natures", "operation": "set", "value": [value]}])
    validate_info_nature_source(draft.changes[0])


@pytest.mark.asyncio
async def test_legacy_basis_is_preserved_without_inventing_condition_sources():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        old = await begin(db, item, "不查知识库，只用通用知识讨论")
        old.context_meta_json = "{}"
        old.request_basis_mode = "auto"
        old.status, old.active_slot = "completed", None
        old.context_decision = "new_topic"
        await db.flush()
        current = await begin(db, item, "接着讨论")
        frame = read_state(current).pool[0]
        assert frame.legacy and frame.sources == {}
        state, _ = await select_frame(db, current, "resume", frame.handle)
        assert state.frame.basis == "no_grove"
        assert state.frame.basis_source["message_id"] == old.user_message_id


@pytest.mark.asyncio
async def test_task_pool_and_branch_depth_are_bounded():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        for index in range(7):
            run = await begin(db, item, f"任务{index}")
            await select_frame(db, run)
            await complete(db, run)
        assert len(read_state(run).pool) == 5
        parent = read_state(run).frame.handle
        for depth in range(1, 3):
            child = await begin(db, item, f"深入{depth}")
            state, _ = await select_frame(db, child, "branch", parent)
            assert state.frame.depth == depth
            await complete(db, child)
            assert parent in {f.handle for f in read_state(child).pool}
            parent = state.frame.handle
        excessive = await begin(db, item, "继续深入")
        with pytest.raises(TaskStateError, match="上限"):
            await select_frame(db, excessive, "branch", parent)


@pytest.mark.asyncio
async def test_condition_source_and_conflicting_operations_rejected():
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        run = await begin(db, item, "统计知识")
        await select_frame(db, run)
        with pytest.raises(TaskStateError, match="原文"):
            merge_query_delta(
                run,
                delta(
                    "用户没有说过的内容",
                    [
                        {"field": "main_types", "operation": "set", "value": ["method"]},
                    ],
                    outputs=[{"kind": "count"}],
                ),
            )
        with pytest.raises(TaskStateError, match="多个"):
            merge_query_delta(
                run,
                delta(
                    "统计知识",
                    [
                        {"field": "main_types", "operation": "clear"},
                        {"field": "main_types", "operation": "set", "value": ["method"]},
                    ],
                    outputs=[{"kind": "count"}],
                ),
            )
        assert read_state(run).phase == "selected"


@pytest.mark.asyncio
async def test_protocol_is_fixed_at_submission_and_invalid_version_not_downgraded(monkeypatch):
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        run = await begin(db, item, "统计总数")
        monkeypatch.setattr(get_settings(), "knowledge_agent_task_state_enabled", False)
        assert read_state(run).protocol == "dialogue_task_v1"
        state = read_state(run)
        write_state(run, state)
        payload = json.loads(run.context_meta_json)
        payload["dialogue_task"]["protocol"] = "unknown"
        run.context_meta_json = json.dumps(payload)
        with pytest.raises(TaskStateError, match="版本"):
            read_state(run)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_runner_compiles_once_keeps_raw_request_and_never_falls_back_to_search(
    monkeypatch, invalid
):
    from sqlalchemy import func, select

    from app.models import KnowledgeAgentToolCall
    from app.services.knowledge_agent.observability import StageMeta
    from app.services.knowledge_agent.runner import execute_run

    def meta(purpose):
        return StageMeta(
            purpose=purpose,
            provider="test",
            model="task-test",
            is_fallback=False,
            error=None,
            duration_ms=1,
        )

    async def decide(db, workspace_id, **kwargs):
        assert kwargs["current_message"] == "当前范围共有多少条知识"
        return TaskDecisionDraft(
            operation="start",
            topic_label="统计",
            standalone_query="故意不用于条件解析的摘要",
        ), meta("context_decision")

    calls = []

    async def planner(db, workspace_id, **kwargs):
        assert kwargs["task_context"]["current_message"] == "当前范围共有多少条知识"
        calls.append(kwargs)
        return delta(
            "不存在的原文" if invalid else "当前范围共有多少条知识",
            outputs=[{"kind": "count"}],
        ), meta("structured_query_plan")

    monkeypatch.setattr("app.services.knowledge_agent.follow_up.run_context_decision_agent", decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner", planner
    )
    monkeypatch.setattr(get_settings(), "knowledge_agent_structured_query_enabled", True)
    async with async_session_factory() as db:
        item, _ = await conversation(db)
        run = await begin(db, item, "当前范围共有多少条知识")
        run.request_result_mode = "entries"
        run.status = "processing"
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        count = (
            await db.execute(
                select(func.count())
                .select_from(KnowledgeAgentToolCall)
                .where(
                    KnowledgeAgentToolCall.run_id == run.id,
                )
            )
        ).scalar()
        assert len(calls) == 1
        if invalid:
            assert count == 0
            assert read_state(run).phase == "pending"
            assert json.loads(run.answer_json)["status"] == "clarification"
            assert run.structured_query_plan_json is None
        else:
            assert count == 1
            assert read_state(run).phase == "committed"
            assert json.loads(run.entry_result_json)["count"]["value"] == 0
            assert json.loads(run.structured_query_plan_json)["prompt_version"] == "task-v1"
            await execute_run(db, run)
            assert len(calls) == 1
