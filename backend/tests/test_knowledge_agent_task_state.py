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
