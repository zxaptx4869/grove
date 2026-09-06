"""真实数据库验证多轮意图边界、项目子集与序号对象复验。"""

import json
from dataclasses import replace

import pytest
from sqlalchemy.dialects import mysql, sqlite

from app.agents.knowledge_context import ContextDecisionDraft, _format_context
from app.db.session import async_session_factory
from app.models import KnowledgeConversation, KnowledgeMessage
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.basis import (
    contains_knowledge_only_restriction,
    contains_no_grove_restriction,
    load_allowed_user_statements,
    resolve_basis_plan,
)
from app.services.knowledge_agent.dialogue_context import DialogueContext, load_dialogue_context
from app.services.knowledge_agent.follow_up import decide_context
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.structured_query import normalize_structured_query_plan
from app.services.knowledge_agent.structured_query_tools import (
    AggregateEntriesParams,
    aggregate_entries_handler,
    resolve_project_filter,
    structured_aggregate_statement,
)
from app.services.knowledge_agent.tools import RunToolContext, resolve_recent_result_entries
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


async def turn(db, conversation, text, *, mode="auto", complete=True):
    message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"case-{text}",
            message=text,
            context_mode=mode,
        ),
    )
    run.standalone_query = text
    if complete:
        run.status = "completed"
        run.active_slot = None
        run.context_decision = "new_topic" if mode == "new_topic" else "continue"
        run.topic_label = "统计任务"
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assistant.content = "当前任务的回答"
    await db.flush()
    return message, run


@pytest.mark.asyncio
async def test_statistics_without_evidence_continue_and_stop_at_topic_scope_owner_boundary():
    async with async_session_factory() as db:
        user = await create_user(db)
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id, owner_user_id=user.id, scope_type="workspace", title="多轮"
        )
        db.add(conversation)
        await db.flush()
        first_message, first = await turn(db, conversation, "统计全部类型", mode="new_topic")
        first.entry_result_json = json.dumps({"set_summary": {"main_types": []}})
        _, clarification = await turn(db, conversation, "按那个分组")
        clarification.context_decision = "clarify"
        clarification.context_meta_json = json.dumps({"clarify_question": "按哪个字段？"})
        _, current = await turn(db, conversation, "按项目", complete=False)
        context = await load_dialogue_context(db, current, limit=8, message_chars=500)
        assert first.output_context_version_id is None
        assert first_message.id in context.message_ids
        assert context.task["pending_question"] == "按哪个字段？"
        statements = await load_allowed_user_statements(
            db,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            conversation_id=conversation.id,
            scope_type="workspace",
            project_id=None,
            context_decision="continue",
            current_message_id=current.user_message_id,
            history_message_ids=context.message_ids,
            limit=6,
            message_chars=500,
        )
        assert [item.content for item in statements] == ["统计全部类型", "按那个分组", "按项目"]
        current.request_context_mode = "new_topic"
        assert not (await load_dialogue_context(db, current, limit=8, message_chars=500)).history
        current.request_context_mode = "auto"
        current.project_id = 999
        assert not (await load_dialogue_context(db, current, limit=8, message_chars=500)).history
        current.project_id = None
        current.owner_user_id = user.id + 1000
        assert not (await load_dialogue_context(db, current, limit=8, message_chars=500)).history


@pytest.mark.asyncio
@pytest.mark.parametrize("position,expected", [(2, "continue"), (3, "clarify")])
async def test_context_uses_scope_and_validates_list_position(monkeypatch, position, expected):
    async def planner(db, workspace_id, **kwargs):
        assert kwargs["scope_label"] == "项目：装修"
        assert kwargs["task_context"]["previous_query"] == "最近两条方法"
        return ContextDecisionDraft(
            action="continue",
            standalone_query="解释第二条并给出原文",
            topic_label="方法",
            result_position=position,
        ), StageMeta(
            purpose="context_decision",
            provider="test",
            model="test",
            is_fallback=False,
            error=None,
            duration_ms=0,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent", planner
    )
    context = DialogueContext(
        history=[{"role": "user", "content": "列出方法"}],
        message_ids=[1],
        task={"previous_query": "最近两条方法"},
        result_items=[{"entry_id": 10}, {"entry_id": 20}],
    )
    decision = await decide_context(
        None,
        workspace_id=1,
        conversation_id=1,
        current_message="第二条",
        request_mode="auto",
        active_topic_label=None,
        working_set_titles=[],
        history_limit=8,
        history_message_chars=500,
        dialogue=context,
        scope_label="项目：装修",
    )
    assert decision.decision == expected
    assert decision.referenced_entry_ids == ([20] if position == 2 else [])
    assert "项目：装修" in _format_context(
        current_message="一共几条",
        active_topic_label=None,
        working_set_titles=[],
        history=[],
        scope_label="项目：装修",
    )


@pytest.mark.asyncio
async def test_project_groups_zero_projects_named_subset_and_no_scope_expansion():
    async with async_session_factory() as db:
        user = await create_user(db)
        workspace = await create_workspace(db, user)
        foreign = await create_workspace(db, user)
        project = await create_project(db, workspace, "装修")
        empty = await create_project(db, workspace, "旅行")
        second = await create_project(db, workspace, "学习")
        await create_project(db, foreign, "装修")
        outside = await create_project(db, foreign, "私有项目")
        node = await create_child_node(db, project, "方法")
        source, attachment = await create_source_attachment(db, workspace, project)
        entry = await create_entry_with_evidence(
            db, project, node, source, attachment, main_type="method"
        )
        second_node = await create_child_node(db, second, "笔记")
        second_source, second_attachment = await create_source_attachment(db, workspace, second)
        for index in range(2):
            await create_entry_with_evidence(
                db, second, second_node, second_source, second_attachment, title=f"笔记{index}"
            )
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            project_id=None,
            project_name=None,
        )
        all_set = normalize_structured_query_plan(
            {"entry_set": {}, "outputs": [{"kind": "count"}]}
        ).entry_set
        grouped = await aggregate_entries_handler(
            db,
            ctx,
            AggregateEntriesParams(
                entry_set=all_set,
                operation="group_count",
                group_by="project",
            ),
        )
        assert grouped.payload["buckets"] == [
            {"key": str(project.id), "label": "装修", "count": 1},
            {"key": str(empty.id), "label": "旅行", "count": 0},
            {"key": str(second.id), "label": "学习", "count": 2},
        ]
        named = all_set.model_copy(update={"project_name": "旅行"})
        count = await aggregate_entries_handler(
            db, ctx, AggregateEntriesParams(entry_set=named, operation="count")
        )
        populated = await aggregate_entries_handler(
            db,
            ctx,
            AggregateEntriesParams(
                entry_set=all_set.model_copy(update={"project_name": "学习"}),
                operation="count",
            ),
        )
        assert populated.payload["value"] == 2
        assert populated.payload["scope"]["project_id"] == second.id
        assert count.payload["value"] == 0
        assert count.payload["scope"]["project_id"] == empty.id
        assert ctx.project_id is None
        for name in [outside.name, "不存在"]:
            with pytest.raises(ValueError, match="当前授权范围"):
                await resolve_project_filter(
                    db, ctx, all_set.model_copy(update={"project_name": name})
                )
        with pytest.raises(ValueError):
            await resolve_project_filter(db, replace(ctx, project_id=project.id), named)
        await create_project(db, workspace, "旅行")
        with pytest.raises(ValueError, match="同名"):
            await resolve_project_filter(db, ctx, named)
        selected = await resolve_recent_result_entries(db, ctx, [entry.id])
        assert [item.entry_id for item in selected.items] == [entry.id]
        assert not (
            await resolve_recent_result_entries(db, replace(ctx, project_id=empty.id), [entry.id])
        ).items
        await db.delete(entry)
        await db.flush()
        assert not (await resolve_recent_result_entries(db, ctx, [entry.id])).items


@pytest.mark.parametrize("dialect", [sqlite.dialect(), mysql.dialect()])
def test_project_group_sql_preserves_empty_and_authorized_scopes(dialect):
    ctx = RunToolContext(
        run_id=1,
        workspace_id=8,
        owner_user_id=1,
        scope_type="project",
        project_id=9,
        project_name="装修",
    )
    entry_set = normalize_structured_query_plan(
        {"entry_set": {"project_name": "装修"}, "outputs": [{"kind": "count"}]}
    ).entry_set
    stmt = structured_aggregate_statement(
        ctx,
        AggregateEntriesParams(
            entry_set=entry_set,
            operation="group_count",
            group_by="project",
        ),
        dialect_name=dialect.name,
        bucket_limit=5,
    )
    sql = str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).lower()
    assert "left outer join" in sql and "coalesce" in sql
    assert "projects.workspace_id = 8" in sql and "projects.id = 9" in sql
    assert "projects.name = '装修'" in sql and "limit 6" in sql


@pytest.mark.parametrize(
    "message",
    [
        "只用通用知识，简单解释番茄工作法，不查我的知识库。",
        "换个话题：只用通用知识解释番茄工作法，不查知识库。",
        "把刚才的方法压缩成三个步骤，仍然不用查知识库。",
    ],
)
@pytest.mark.asyncio
async def test_no_grove_does_not_become_knowledge_only_even_without_planner(message):
    assert not contains_knowledge_only_restriction(message)
    assert contains_no_grove_restriction(message)
    plan = await resolve_basis_plan(
        None,
        workspace_id=1,
        request_basis_mode="auto",
        objective=message,
        scope_label="全部知识",
        topic_summary=None,
        context_decision="new_topic",
        current_message=message,
        allowed_statements=[],
        feature_enabled=True,
    )
    assert plan.strategy == "model_first" and not plan.needs_grove
    assert contains_knowledge_only_restriction("只用我的知识库，不要补充模型知识")
    assert not contains_no_grove_restriction("不要只查知识库，可以结合通用知识")


@pytest.mark.asyncio
async def test_new_topic_and_scope_markers_cut_off_old_statistics():
    async with async_session_factory() as db:
        user = await create_user(db)
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id, owner_user_id=user.id, scope_type="workspace", title="边界"
        )
        db.add(conversation)
        await db.flush()
        old_message, _ = await turn(db, conversation, "方法统计", mode="new_topic")
        new_message, new = await turn(db, conversation, "通用讨论", mode="new_topic")
        _, current = await turn(db, conversation, "继续解释", complete=False)
        context = await load_dialogue_context(db, current, limit=8, message_chars=5)
        assert old_message.id not in context.message_ids and new_message.id in context.message_ids
        assert all(len(item["content"]) <= 5 for item in context.history)
        new.status = "failed"
        assert not (await load_dialogue_context(db, current, limit=8, message_chars=500)).history
        current.status = "completed"
        current.active_slot = None
        db.add(
            KnowledgeMessage(
                conversation_id=conversation.id,
                role="system",
                message_type="scope_change",
                content="切换范围",
                scope_type="workspace",
            )
        )
        await db.flush()
        _, after = await turn(db, conversation, "当前范围几条", complete=False)
        assert not (await load_dialogue_context(db, after, limit=8, message_chars=500)).history


def test_old_entry_set_fingerprint_and_saved_decision_stay_compatible():
    from types import SimpleNamespace

    from app.services.knowledge_agent.follow_up import ContextDecisionResult
    from app.services.knowledge_agent.runner import _persist_decision, _restore_decision

    old = {
        "schema_version": "v1",
        "semantic_query": None,
        "main_types": [],
        "info_natures": [],
        "updated_at": None,
    }
    plan = normalize_structured_query_plan({"entry_set": old, "outputs": [{"kind": "count"}]})
    assert plan.entry_set.model_dump(mode="json", by_alias=True) == old
    run = SimpleNamespace()
    decision = ContextDecisionResult(
        decision="continue",
        standalone_query="解释第二条",
        topic_label="方法",
        clarify_question=None,
        degraded=False,
        history_message_ids=[1, 2],
        referenced_entry_ids=[81],
        meta=StageMeta(
            purpose="context_decision",
            provider="server",
            model=None,
            is_fallback=False,
            error=None,
            duration_ms=0,
        ),
    )
    _persist_decision(run, decision)
    restored = _restore_decision(run)
    assert restored.history_message_ids == [1, 2] and restored.referenced_entry_ids == [81]


@pytest.mark.asyncio
async def test_project_tool_failure_never_turns_into_zero_count(monkeypatch):
    from types import SimpleNamespace

    from app.schemas.knowledge_agent import KnowledgeEntryResultSnapshotOut
    from app.services.knowledge_agent.structured_entry_search import _assistant_compatibility_text
    from app.services.knowledge_agent.structured_query_execution import (
        execute_structured_query_plan,
    )

    async def dispatch(*args, **kwargs):
        return SimpleNamespace(
            status="error", payload={}, completeness="unknown", error="当前授权范围内没有这个项目"
        )

    async def nothing():
        pass

    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query_execution.dispatch_read_tool", dispatch
    )
    plan = normalize_structured_query_plan(
        {
            "entry_set": {"project_name": "不存在"},
            "outputs": [{"kind": "count"}, {"kind": "group_count", "group_by": "project"}],
        }
    )
    result = await execute_structured_query_plan(
        SimpleNamespace(commit=nothing), None, plan, cancel_check=nothing
    )
    assert result.count is None and result.status == "partial"
    assert result.group_counts[0]["group_by"] == "project"
    snapshot = KnowledgeEntryResultSnapshotOut(
        schema_version="v2",
        query="统计不存在项目",
        status="partial",
        completeness="unknown",
        items=[],
        returned_count=0,
        candidate_limit=50,
        snapshot_updated_at="2026-09-06T00:00:00Z",
        warning=result.warnings[0],
    )
    assert "没有这个项目" in _assistant_compatibility_text(snapshot)


@pytest.mark.asyncio
async def test_no_grove_conflict_cannot_open_model_permission():
    with pytest.raises(ValueError, match="冲突"):
        await resolve_basis_plan(
            None,
            workspace_id=1,
            request_basis_mode="knowledge_only",
            objective="不查我的知识库",
            scope_label="全部知识",
            topic_summary=None,
            context_decision="new_topic",
            current_message="不查我的知识库",
            allowed_statements=[],
            feature_enabled=True,
        )
