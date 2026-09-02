"""统一只读工具 dispatcher 的白名单、可信上下文与审计测试。"""

import json

import pytest
from pydantic import Field
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import KnowledgeAgentRun, KnowledgeAgentToolCall, KnowledgeConversation
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    RESULT_COMPLETENESS_COMPLETE,
    RUN_PROCESSING,
    SCOPE_PROJECT,
    TOOL_COMPLETED,
    TOOL_DENIED,
)
from app.services.knowledge_agent.read_tools import (
    ReadToolBudget,
    ReadToolExecution,
    ReadToolParams,
    ReadToolSpec,
    dispatch_read_tool,
)
from app.services.knowledge_agent.tools import RunToolContext
from tests._knowledge_agent_fixtures import create_project, create_user, create_workspace


class _FakeParams(ReadToolParams):
    query: str = Field(min_length=1, max_length=20)


async def _run_context(db):
    user = await create_user(db, "dispatcher")
    workspace = await create_workspace(db, user)
    project = await create_project(db, workspace, "可信项目")
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_PROJECT,
        project_id=project.id,
        title="dispatcher",
    )
    db.add(conversation)
    await db.flush()
    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_PROJECT,
        project_id=project.id,
        project_name=project.name,
        status=RUN_PROCESSING,
        active_slot=ACTIVE_SLOT,
    )
    db.add(run)
    await db.flush()
    return run, RunToolContext(
        run_id=run.id,
        workspace_id=run.workspace_id,
        owner_user_id=run.owner_user_id,
        scope_type=run.scope_type,
        project_id=run.project_id,
        project_name=run.project_name,
    )


@pytest.mark.asyncio
async def test_dispatcher_injects_run_scope_and_records_bounded_audit() -> None:
    """处理器只能从可信 ctx 读取项目范围，审计不复制正文。"""
    seen: dict = {}

    async def _handler(db, ctx, params):
        del db
        seen.update(
            workspace_id=ctx.workspace_id,
            project_id=ctx.project_id,
            query=params.query,
        )
        return ReadToolExecution(
            status=TOOL_COMPLETED,
            payload={"count": 1},
            completeness=RESULT_COMPLETENESS_COMPLETE,
            audit_summary={"count": 1, "completeness": "complete"},
        )

    registry = {
        "fake_query": ReadToolSpec("fake_query", "v1", _FakeParams, _handler)
    }
    async with async_session_factory() as db:
        run, ctx = await _run_context(db)
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="fake_query",
            tool_version="v1",
            params={"query": "经验"},
            budget=ReadToolBudget(1, 1, 1000),
            cancel_check=_noop_cancel,
            registry=registry,
        )
        call = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalar_one()

    assert result.status == TOOL_COMPLETED
    assert seen["project_id"] == ctx.project_id
    params_summary = json.loads(call.params_summary or "{}")
    assert params_summary["tool_version"] == "v1"
    assert len(params_summary["fingerprint"]) == 64
    assert "workspace_id" not in params_summary["params"]


@pytest.mark.asyncio
async def test_dispatcher_denies_unknown_tool_without_guessing() -> None:
    """未知名称只记录 denied，不动态导入、反射或猜测相近工具。"""
    async with async_session_factory() as db:
        run, ctx = await _run_context(db)
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="fake_query_similar",
            tool_version="v1",
            params={"query": "经验", "sql": "select 1"},
            budget=ReadToolBudget(1, 1, 1000),
            cancel_check=_noop_cancel,
            registry={},
        )
        call = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalar_one()

    assert result.status == TOOL_DENIED
    assert call.status == TOOL_DENIED
    assert "select 1" not in (call.params_summary or "")


@pytest.mark.asyncio
async def test_dispatcher_denies_scope_fields_before_handler() -> None:
    """参数模型没有项目/Workspace 字段，越权字段整体拒绝。"""
    called = False

    async def _handler(db, ctx, params):
        nonlocal called
        del db, ctx, params
        called = True
        return ReadToolExecution(status=TOOL_COMPLETED, payload={})

    registry = {"fake": ReadToolSpec("fake", "v1", _FakeParams, _handler)}
    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="fake",
            tool_version="v1",
            params={"query": "经验", "project_id": 999},
            budget=ReadToolBudget(1, 1, 1000),
            cancel_check=_noop_cancel,
            registry=registry,
        )

    assert result.status == TOOL_DENIED
    assert called is False


async def _noop_cancel() -> None:
    return None
