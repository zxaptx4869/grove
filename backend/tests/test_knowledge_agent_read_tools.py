"""统一只读工具 dispatcher 的白名单、可信上下文与审计测试。"""

import json

import pytest
from pydantic import Field
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentRun,
    KnowledgeAgentToolCall,
    KnowledgeConversation,
    Node,
    Project,
    Workspace,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    RESULT_COMPLETENESS_COMPLETE,
    RUN_PROCESSING,
    SCOPE_PROJECT,
    TOOL_COMPLETED,
    TOOL_DENIED,
    TOOL_EMPTY,
)
from app.services.knowledge_agent.directory_tools import ListProjectDirectoriesParams
from app.services.knowledge_agent.read_tool_adapters import (
    KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
)
from app.services.knowledge_agent.read_tools import (
    ReadToolBudget,
    ReadToolExecution,
    ReadToolParams,
    ReadToolSpec,
    dispatch_read_tool,
)
from app.services.knowledge_agent.tools import RunToolContext
from tests._knowledge_agent_fixtures import (
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


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
async def test_dispatcher_can_return_outcome_without_writing_audit() -> None:
    """并行节点可把审计交给协调器，独立会话不抢占工具序号。"""

    async def _handler(db, ctx, params):
        del db, ctx, params
        return ReadToolExecution(
            status=TOOL_COMPLETED,
            payload={"count": 1},
            completeness=RESULT_COMPLETENESS_COMPLETE,
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
            record_audit=False,
        )
        calls = list(
            (
                await db.execute(
                    select(KnowledgeAgentToolCall).where(
                        KnowledgeAgentToolCall.run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert result.status == TOOL_COMPLETED
    assert calls == []


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


def test_dispatcher_registry_contains_structured_and_existing_read_tools() -> None:
    """统一静态 registry 明确列出工具，不通过模块扫描或名称猜测发现。"""
    assert set(KNOWLEDGE_AGENT_READ_TOOL_REGISTRY) == {
        "query_entries",
        "aggregate_entries",
        "list_project_directories",
        "search_knowledge",
        "read_entries",
        "read_evidence",
    }


@pytest.mark.asyncio
async def test_directory_tool_returns_real_order_empty_nodes_and_direct_children() -> None:
    """目录查询只读真实 Node，空目录计入且后代不冒充一级目录。"""
    async with async_session_factory() as db:
        run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        root = Node(project_id=project.id, parent_id=None, name="根目录", position=0)
        first = Node(project_id=project.id, parent_id=None, name="一号", position=1)
        second = Node(project_id=project.id, parent_id=None, name="二号空目录", position=2)
        db.add_all([root, first, second])
        await db.flush()
        child = Node(project_id=project.id, parent_id=first.id, name="子目录", position=0)
        db.add(child)
        await db.flush()
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        nested = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id, "parent_node_id": first.id},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )

    assert result.status == TOOL_COMPLETED
    assert result.completeness == RESULT_COMPLETENESS_COMPLETE
    assert result.payload["total_count"] == 4
    assert [item["name"] for item in result.payload["items"]] == [
        "根",
        "根目录",
        "一号",
        "二号空目录",
    ]
    assert result.payload["items"][3]["entry_count"] == 0
    assert nested.payload["total_count"] == 1
    assert nested.payload["items"][0]["name"] == "子目录"


@pytest.mark.asyncio
async def test_directory_tool_aggregates_real_leaf_nodes_in_one_call() -> None:
    """叶子数量由完整 Node 父子关系计算，不把直接子目录数量当作叶子数。"""

    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        root = Node(project_id=project.id, parent_id=None, name="规划", position=10)
        db.add(root)
        await db.flush()
        branch = Node(project_id=project.id, parent_id=root.id, name="空间布局", position=0)
        direct_leaf = Node(project_id=project.id, parent_id=root.id, name="图纸", position=1)
        db.add_all([branch, direct_leaf])
        await db.flush()
        db.add_all(
            [
                Node(project_id=project.id, parent_id=branch.id, name="功能分区", position=0),
                Node(project_id=project.id, parent_id=branch.id, name="收纳设计", position=1),
                Node(project_id=project.id, parent_id=branch.id, name="动线优化", position=2),
            ]
        )
        await db.flush()
        rows = (
            await db.execute(select(Node).where(Node.project_id == project.id))
        ).scalars().all()
        parent_ids = {node.parent_id for node in rows if node.parent_id is not None}
        expected_leaf_count = sum(node.id not in parent_ids for node in rows)
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id, "operation": "leaf_summary"},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
    assert result.status == TOOL_COMPLETED
    assert result.completeness == RESULT_COMPLETENESS_COMPLETE
    assert result.payload["value"] == expected_leaf_count
    assert result.payload["total_count"] == expected_leaf_count
    assert result.payload["has_more"] is False
    planning = next(item for item in result.payload["buckets"] if item["label"] == "规划")
    assert planning["count"] == 4


@pytest.mark.asyncio
async def test_directory_tool_rejects_foreign_workspace_and_parent() -> None:
    """项目与父节点归属错误都拒绝且不回退到根目录。"""
    async with async_session_factory() as db:
        run, ctx = await _run_context(db)
        foreign_user = await create_user(db, "foreign-directory")
        foreign_workspace = await create_workspace(db, foreign_user)
        foreign_project = await create_project(db, foreign_workspace, "同名项目")
        local_project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        foreign_node = Node(
            project_id=foreign_project.id, parent_id=None, name="不可见", position=0
        )
        db.add(foreign_node)
        await db.flush()

        foreign_result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_name": "同名项目"},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        wrong_parent = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": local_project.id, "parent_node_id": foreign_node.id},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )

    assert foreign_result.status == TOOL_DENIED
    assert foreign_result.audit_summary["reason_code"] == "project_not_found"
    assert "不存在" in (foreign_result.error or "")
    assert wrong_parent.status == TOOL_DENIED
    assert "父节点不属于指定项目" in (wrong_parent.error or "")


def test_directory_params_require_explicit_project_reference() -> None:
    with pytest.raises(ValueError, match="project_id 或 project_name"):
        ListProjectDirectoriesParams()


@pytest.mark.asyncio
async def test_directory_find_exact_name_returns_real_deep_path_and_leaf_state() -> None:
    """已知深层名称可一次定位，路径、深度和叶子状态都来自真实 Node 树。"""

    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        planning = Node(project_id=project.id, name="设计规划", position=1)
        db.add(planning)
        await db.flush()
        style = Node(project_id=project.id, parent_id=planning.id, name="风格设计", position=0)
        db.add(style)
        await db.flush()
        material = Node(project_id=project.id, parent_id=style.id, name="材质选择", position=0)
        db.add(material)
        await db.flush()
        tile = Node(project_id=project.id, parent_id=material.id, name="瓷砖地材", position=0)
        db.add(tile)
        await db.flush()

        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_name": project.name,
                "operation": "find",
                "name": "瓷砖地材",
                "match": "exact",
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        contains_with_exact = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_name": project.name,
                "operation": "find",
                "name": "瓷砖地材",
                "match": "contains",
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        contains_only = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_name": project.name,
                "operation": "find",
                "name": "地材",
                "match": "contains",
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )

    assert result.status == TOOL_COMPLETED
    assert result.completeness == RESULT_COMPLETENESS_COMPLETE
    assert result.payload["match_status"] == "unique"
    assert result.payload["total_count"] == result.payload["returned_count"] == 1
    assert result.payload["has_more"] is False
    assert result.payload["items"] == [
        {
            "node_id": tile.id,
            "name": "瓷砖地材",
            "project_id": project.id,
            "project_name": project.name,
            "parent_node_id": material.id,
            "path": "设计规划 / 风格设计 / 材质选择 / 瓷砖地材",
            "depth": 3,
            "is_leaf": True,
            "position": 0,
        }
    ]
    assert contains_with_exact.payload["query"]["applied_match"] == "exact"
    assert contains_with_exact.payload["total_count"] == 1
    assert contains_only.status == "partial"
    assert contains_only.payload["match_status"] == "contains_candidates"
    assert contains_only.payload["items"][0]["node_id"] == tile.id


@pytest.mark.asyncio
async def test_directory_find_path_disambiguates_and_never_mixes_projects() -> None:
    """同项目同名返回候选；完整路径唯一定位，其他项目同名不会混入。"""

    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        workspace = await db.get(Workspace, ctx.workspace_id)
        assert workspace is not None
        first_root = Node(project_id=project.id, name="设计规划", position=1)
        second_root = Node(project_id=project.id, name="施工执行", position=2)
        db.add_all([first_root, second_root])
        await db.flush()
        first = Node(project_id=project.id, parent_id=first_root.id, name="瓷砖地材")
        second = Node(project_id=project.id, parent_id=second_root.id, name="瓷砖地材")
        other_project = await create_project(db, workspace, "另一项目")
        other = Node(project_id=other_project.id, name="瓷砖地材")
        db.add_all([first, second, other])
        await db.flush()

        ambiguous = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id, "operation": "find", "name": "瓷砖地材"},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        exact_path = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_id": project.id,
                "operation": "find",
                "path": " 设计规划/ 瓷砖地材 ",
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )

    assert ambiguous.status == "partial"
    assert ambiguous.payload["match_status"] == "ambiguous"
    assert ambiguous.payload["total_count"] == 2
    assert {item["node_id"] for item in ambiguous.payload["items"]} == {first.id, second.id}
    assert other.id not in {item["node_id"] for item in ambiguous.payload["items"]}
    assert exact_path.status == TOOL_COMPLETED
    assert exact_path.payload["items"][0]["node_id"] == first.id
    assert exact_path.payload["query"]["path"] == "设计规划 / 瓷砖地材"


@pytest.mark.asyncio
async def test_directory_find_reports_missing_denied_and_truncated_states() -> None:
    """不存在、无 Workspace 权限、项目越权与候选截断保持可区分状态。"""

    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        workspace = await db.get(Workspace, ctx.workspace_id)
        assert workspace is not None
        db.add_all(
            [Node(project_id=project.id, name="重复目录", position=index) for index in range(3)]
        )
        foreign_user = await create_user(db, "目录无权限")
        await db.flush()

        missing = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id, "operation": "find", "name": "墙纸施工"},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        truncated = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_id": project.id,
                "operation": "find",
                "name": "重复目录",
                "limit": 1,
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        invalid_params = await dispatch_read_tool(
            db,
            ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={
                "project_id": project.id,
                "operation": "children",
                "parent_node_id": 0,
            },
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
            record_audit=False,
        )
        denied_ctx = RunToolContext(
            run_id=ctx.run_id,
            workspace_id=ctx.workspace_id,
            owner_user_id=foreign_user.id,
            scope_type=ctx.scope_type,
            project_id=ctx.project_id,
            project_name=ctx.project_name,
        )
        denied = await dispatch_read_tool(
            db,
            denied_ctx,
            tool_name="list_project_directories",
            tool_version="v1",
            params={"project_id": project.id, "operation": "find", "name": "重复目录"},
            budget=ReadToolBudget(1, 1, 10_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
            record_audit=False,
        )

    assert missing.status == TOOL_EMPTY
    assert missing.payload["match_status"] == "not_found"
    assert missing.payload["reason_code"] == "directory_not_found"
    assert truncated.status == "partial"
    assert truncated.completeness == "limited"
    assert truncated.payload["total_count"] == 3
    assert truncated.payload["returned_count"] == 1
    assert truncated.payload["has_more"] is True
    assert invalid_params.status == TOOL_DENIED
    assert invalid_params.audit_summary["reason_code"] == "invalid_tool_params"
    assert denied.status == TOOL_DENIED
    assert denied.audit_summary["reason_code"] == "workspace_access_denied"


@pytest.mark.asyncio
async def test_located_node_scope_queries_only_real_directory_entries() -> None:
    """定位后的 Node direct/subtree 查询复用现有 Entry 工具且不按名称相关性推算。"""

    async with async_session_factory() as db:
        _run, ctx = await _run_context(db)
        project = (
            await db.execute(select(Project).where(Project.id == ctx.project_id))
        ).scalar_one()
        workspace = await db.get(Workspace, ctx.workspace_id)
        assert workspace is not None
        tile = Node(project_id=project.id, name="瓷砖地材", position=1)
        db.add(tile)
        await db.flush()
        child = Node(project_id=project.id, parent_id=tile.id, name="铺贴工艺")
        outside = Node(project_id=project.id, name="墙面材料", position=2)
        db.add_all([child, outside])
        await db.flush()
        foreign_project = await create_project(db, workspace, "同空间其他项目")
        foreign_node = Node(project_id=foreign_project.id, name="瓷砖地材")
        db.add(foreign_node)
        await db.flush()
        source, attachment = await create_source_attachment(db, workspace, project)
        direct = await create_entry_with_evidence(
            db, project, tile, source, attachment, title="瓷砖选购"
        )
        nested = await create_entry_with_evidence(
            db, project, child, source, attachment, title="薄贴法"
        )
        await create_entry_with_evidence(
            db, project, outside, source, attachment, title="乳胶漆"
        )

        direct_result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="query_entries",
            tool_version="v1",
            params={
                "entry_set": {"project_name": project.name},
                "limit": 10,
                "sort": {"field": "created_at", "direction": "asc"},
                "project_id": project.id,
                "node_id": tile.id,
                "node_scope": "direct",
            },
            budget=ReadToolBudget(1, 2, 20_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        subtree_result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="aggregate_entries",
            tool_version="v1",
            params={
                "entry_set": {"project_name": project.name},
                "operation": "count",
                "group_by": None,
                "project_id": project.id,
                "node_id": tile.id,
                "node_scope": "subtree",
            },
            budget=ReadToolBudget(1, 2, 20_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        denied = await dispatch_read_tool(
            db,
            ctx,
            tool_name="query_entries",
            tool_version="v1",
            params={
                "entry_set": {"project_name": project.name},
                "limit": 10,
                "sort": {"field": "created_at", "direction": "asc"},
                "project_id": project.id,
                "node_id": foreign_node.id,
                "node_scope": "subtree",
            },
            budget=ReadToolBudget(1, 2, 20_000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )

    assert [item["entry_id"] for item in direct_result.payload["items"]] == [direct.id]
    assert subtree_result.payload["value"] == 2
    assert subtree_result.payload["node_scope"] == {
        "project_id": project.id,
        "node_id": tile.id,
        "scope": "subtree",
    }
    assert nested.id != direct.id
    assert denied.status == TOOL_DENIED
    assert denied.audit_summary["reason_code"] == "node_scope_denied"
    assert "瓷砖地材" not in (denied.error or "")


@pytest.mark.asyncio
async def test_read_entries_adapter_keeps_discovered_set_boundary() -> None:
    """统一入口不能让未发现 Entry id 绕过既有权限边界。"""
    async with async_session_factory() as db:
        run, ctx = await _run_context(db)
        result = await dispatch_read_tool(
            db,
            ctx,
            tool_name="read_entries",
            tool_version="v1",
            params={"entry_ids": [999999]},
            budget=ReadToolBudget(1, 1, 4000),
            cancel_check=_noop_cancel,
            registry=KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
        )
        call = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalar_one()

    assert result.status == TOOL_DENIED
    assert result.payload["denied_entry_ids"] == [999999]
    assert "content" not in (call.result_summary or "")
