"""结构化查询计划校验、预算与规范化测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.semantic import SemanticRankingDraft, SemanticRankResult
from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import Settings
from app.db.session import async_session_factory
from app.models import KnowledgeAgentModelInvocation, KnowledgeAgentRun, KnowledgeConversation
from app.models.knowledge_agent import ACTIVE_SLOT, RUN_PROCESSING, SCOPE_WORKSPACE
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.structured_query import (
    StructuredQueryPlanError,
    normalize_structured_query_plan,
    persist_structured_query_plan,
    plan_and_persist_structured_query,
    restore_structured_query_plan,
)
from app.services.knowledge_agent.structured_query_execution import (
    StructuredQueryExecutionResult,
    apply_execution_byte_budget,
    execute_structured_query_plan,
)
from app.services.knowledge_agent.structured_query_tools import (
    AggregateEntriesParams,
    QueryEntriesParams,
    aggregate_entries_handler,
    query_entries_handler,
)
from app.services.knowledge_agent.tools import RunToolContext
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


def _plan(**entry_set) -> dict:
    return {
        "schema_version": "v1",
        "entry_set": {"schema_version": "v1", **entry_set},
        "outputs": [{"kind": "count"}],
    }


@pytest.mark.parametrize(
    "forbidden",
    [
        {"workspace_id": 1},
        {"project_id": 1},
        {"node_id": 1},
        {"entry_ids": [1]},
        {"sql": "select * from entries"},
        {"operator": "contains"},
        {"unknown_field": "x"},
    ],
)
def test_validation_rejects_scope_ids_sql_and_unknown_fields(forbidden: dict) -> None:
    """范围、对象标识、SQL、任意运算符和未知字段整体拒绝。"""
    with pytest.raises(StructuredQueryPlanError):
        normalize_structured_query_plan(_plan(**forbidden))


def test_validation_normalizes_utc_range_and_enum_order() -> None:
    """时间转 UTC，枚举去重并按服务端顺序固化。"""
    plan = normalize_structured_query_plan(
        _plan(
            main_types=["reminder", "knowledge", "reminder"],
            info_natures=["unspecified", "fact"],
            updated_at={
                "from": "2026-01-01T08:00:00+08:00",
                "to": "2026-02-01T08:00:00+08:00",
            },
        )
    )

    assert plan.entry_set.main_types == ["knowledge", "reminder"]
    assert plan.entry_set.info_natures == ["fact", "unspecified"]
    assert plan.entry_set.updated_at is not None
    assert plan.entry_set.updated_at.from_ == datetime(
        2026, 1, 1, tzinfo=UTC
    )
    assert plan.entry_set.updated_at.to == datetime(
        2026, 2, 1, tzinfo=UTC
    )


def test_validation_rejects_naive_or_contradictory_time_range() -> None:
    """无时区或 from >= to 的范围不得被隐式猜测。"""
    with pytest.raises(StructuredQueryPlanError, match="必须包含时区"):
        normalize_structured_query_plan(
            _plan(updated_at={"from": "2026-01-01T00:00:00"})
        )
    with pytest.raises(StructuredQueryPlanError, match="from < to"):
        normalize_structured_query_plan(
            _plan(
                updated_at={
                    "from": "2026-02-01T00:00:00Z",
                    "to": "2026-01-01T00:00:00Z",
                }
            )
        )


def test_validation_rejects_relevance_without_semantic_query() -> None:
    """非语义集合不能请求没有定义的相关性排序。"""
    raw = _plan()
    raw["outputs"] = [
        {
            "kind": "entries",
            "limit": 5,
            "sort": {"field": "relevance", "direction": "desc"},
        }
    ]
    with pytest.raises(StructuredQueryPlanError, match="relevance"):
        normalize_structured_query_plan(raw)


def test_plan_outputs_are_unique_and_stably_ordered() -> None:
    """输出去重门禁与固定 count → group_count → entries 执行顺序。"""
    raw = _plan(semantic_query="血压")
    raw["outputs"] = [
        {
            "kind": "entries",
            "limit": 5,
            "sort": {"field": "relevance", "direction": "desc"},
        },
        {"kind": "group_count", "group_by": "info_nature"},
        {"kind": "count"},
    ]
    plan = normalize_structured_query_plan(raw)
    assert [item.kind for item in plan.outputs] == [
        "count",
        "group_count",
        "entries",
    ]

    raw["outputs"] = [{"kind": "count"}, {"kind": "count"}]
    with pytest.raises(StructuredQueryPlanError, match="不得重复"):
        normalize_structured_query_plan(raw)


def test_budget_rejects_excess_entry_limit_and_output_count() -> None:
    """模型请求只能收紧预算，不能扩大列表或输出数量。"""
    settings = Settings(
        knowledge_agent_structured_query_entry_limit=4,
        knowledge_agent_structured_query_max_outputs=2,
    )
    raw = _plan()
    raw["outputs"] = [
        {
            "kind": "entries",
            "limit": 5,
            "sort": {"field": "updated_at", "direction": "desc"},
        }
    ]
    with pytest.raises(StructuredQueryPlanError, match="entries.limit"):
        normalize_structured_query_plan(raw, settings=settings)

    raw["outputs"] = [
        {"kind": "count"},
        {"kind": "group_count", "group_by": "main_type"},
        {
            "kind": "entries",
            "limit": 4,
            "sort": {"field": "updated_at", "direction": "desc"},
        },
    ]
    with pytest.raises(StructuredQueryPlanError, match="输出数"):
        normalize_structured_query_plan(raw, settings=settings)


def test_structured_query_plan_snapshot_is_normalized_and_immutable() -> None:
    """只保存规范化计划；已有快照恢复时不得被后续候选覆盖。"""
    first = normalize_structured_query_plan(
        _plan(main_types=["reminder", "knowledge", "reminder"])
    )
    run = SimpleNamespace(structured_query_plan_json=None)
    persist_structured_query_plan(run, first)
    raw = run.structured_query_plan_json
    assert raw is not None and "reason" not in raw
    assert restore_structured_query_plan(raw) == first

    different = normalize_structured_query_plan(_plan(main_types=["method"]))
    restored = persist_structured_query_plan(run, different)
    assert restored == first
    assert run.structured_query_plan_json == raw


@pytest.mark.asyncio
async def test_plan_validation_fallback_is_observable(monkeypatch) -> None:
    """服务端硬校验失败时留痕并返回旧查找信号，不固化非法计划。"""

    async def _invalid_planner(db, workspace_id, **kwargs):
        del db, workspace_id, kwargs
        return (
            StructuredQueryPlanDraft.model_validate(
                {
                    "entry_set": {},
                    "outputs": [
                        {
                            "kind": "entries",
                            "limit": 5,
                            "sort": {"field": "relevance", "direction": "desc"},
                        }
                    ],
                }
            ),
            StageMeta(
                purpose="structured_query_plan",
                provider="test",
                model="test-model",
                is_fallback=False,
                error=None,
                duration_ms=3,
                usage={"requests": 1},
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner",
        _invalid_planner,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "计划降级")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="计划降级",
        )
        db.add(conversation)
        await db.flush()
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot=ACTIVE_SLOT,
        )
        db.add(run)
        await db.flush()

        plan = await plan_and_persist_structured_query(
            db,
            run,
            objective="列出相关知识",
            scope_label="全部知识",
        )

        invocation = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalar_one()
        assert plan is None
        assert run.structured_query_plan_json is None
        assert invocation.is_fallback is True
        assert "relevance" in (invocation.error or "")
        assert invocation.usage_json is not None


@pytest.mark.asyncio
async def test_query_entries_filters_scope_type_nature_time_and_stable_sort() -> None:
    """纯结构化查询只读当前范围正式 Entry，并按时间 + id 稳定排序。"""
    async with async_session_factory() as db:
        user = await create_user(db, "结构化列表")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "目标项目")
        node = await create_child_node(db, project, "记录")
        other_project = await create_project(db, workspace, "其他项目")
        other_node = await create_child_node(db, other_project, "其他")
        source, attachment = await create_source_attachment(db, workspace, project)
        first = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="经验一",
            main_type="knowledge",
            info_nature="experience",
        )
        second = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="经验二",
            main_type="knowledge",
            info_nature="experience",
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="项目内其他类型",
            main_type="method",
            info_nature="experience",
        )
        other_source, other_attachment = await create_source_attachment(
            db, workspace, other_project
        )
        await create_entry_with_evidence(
            db,
            other_project,
            other_node,
            other_source,
            other_attachment,
            title="范围外经验",
            info_nature="experience",
        )
        tied = datetime(2026, 5, 1, tzinfo=UTC)
        first.updated_at = tied
        second.updated_at = tied
        await db.flush()
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
        )
        params = QueryEntriesParams.model_validate(
            {
                "entry_set": {
                    "main_types": ["knowledge"],
                    "info_natures": ["experience"],
                    "updated_at": {
                        "from": "2026-01-01T00:00:00Z",
                        "to": "2027-01-01T00:00:00Z",
                    },
                },
                "limit": 10,
                "sort": {"field": "updated_at", "direction": "desc"},
            }
        )

        result = await query_entries_handler(db, ctx, params)

    ids = [item["entry_id"] for item in result.payload["items"]]
    assert ids == sorted([first.id, second.id], reverse=True)
    assert result.completeness == "complete"
    assert result.payload["has_more"] is False


@pytest.mark.asyncio
async def test_query_entries_limit_marks_only_list_as_limited() -> None:
    """列表达到 limit 时明确 limited，不把返回卡片数冒充集合总数。"""
    async with async_session_factory() as db:
        user = await create_user(db, "结构化列表上限")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace)
        node = await create_child_node(db, project, "记录")
        source, attachment = await create_source_attachment(db, workspace, project)
        for index in range(3):
            await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"记录{index}",
            )
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
        )
        params = QueryEntriesParams.model_validate(
            {
                "entry_set": {},
                "limit": 2,
                "sort": {"field": "created_at", "direction": "asc"},
            }
        )

        result = await query_entries_handler(db, ctx, params)

    assert result.status == "limited"
    assert result.completeness == "limited"
    assert result.payload["returned_count"] == 2
    assert "total" not in result.payload


@pytest.mark.asyncio
async def test_semantic_query_combines_structured_filters_and_stays_limited(
    monkeypatch,
) -> None:
    """语义召回只看结构化合法子集，top-k 即使未满也不宣称全集。"""
    seen_titles: list[str] = []

    async def _hybrid(db, workspace_id, entries, query, limit):
        del db, workspace_id, query, limit
        seen_titles.extend(entry.title for entry in entries)
        return list(entries), {}, None

    async def _rerank(db, workspace_id, query, entries, strict=False):
        del db, workspace_id, query
        assert strict is True
        return (
            SemanticRankingDraft(
                results=[
                    SemanticRankResult(entry_id=entry.id, reason="匹配")
                    for entry in reversed(entries)
                ]
            ),
            "test",
            "test-model",
            False,
            None,
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query_tools.hybrid_recall_by_query_with_meta",
        _hybrid,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query_tools.run_semantic_agent",
        _rerank,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "语义组合")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace)
        node = await create_child_node(db, project, "记录")
        source, attachment = await create_source_attachment(db, workspace, project)
        allowed = []
        for index in range(2):
            allowed.append(
                await create_entry_with_evidence(
                    db,
                    project,
                    node,
                    source,
                    attachment,
                    title=f"血压经验{index}",
                    info_nature="experience",
                )
            )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="血压事实",
            info_nature="fact",
        )
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
        )
        params = QueryEntriesParams.model_validate(
            {
                "entry_set": {
                    "semantic_query": "血压",
                    "info_natures": ["experience"],
                },
                "limit": 10,
                "sort": {"field": "relevance", "direction": "desc"},
            }
        )

        result = await query_entries_handler(db, ctx, params)

    assert seen_titles == [entry.title for entry in allowed]
    assert [item["entry_id"] for item in result.payload["items"]] == [
        entry.id for entry in reversed(allowed)
    ]
    assert result.status == "limited"
    assert result.completeness == "limited"


@pytest.mark.asyncio
async def test_aggregate_count_queries_full_shared_set_not_entry_limit() -> None:
    """count 直接覆盖共享集合，不从有界列表返回数反推。"""
    async with async_session_factory() as db:
        user = await create_user(db, "精确聚合")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace)
        node = await create_child_node(db, project, "记录")
        source, attachment = await create_source_attachment(db, workspace, project)
        for index in range(7):
            await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"经验{index}",
                info_nature="experience",
            )
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
        )
        params = AggregateEntriesParams.model_validate(
            {
                "entry_set": {"info_natures": ["experience"]},
                "operation": "count",
            }
        )

        result = await aggregate_entries_handler(db, ctx, params)

    assert result.payload == {"value": 7}
    assert result.completeness == "complete"
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_aggregate_groups_null_nature_and_utc_month_stably() -> None:
    """NULL 性质统一为 unspecified，UTC 月桶按 YYYY-MM 稳定排序。"""
    async with async_session_factory() as db:
        user = await create_user(db, "分组聚合")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace)
        node = await create_child_node(db, project, "记录")
        source, attachment = await create_source_attachment(db, workspace, project)
        first = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="未标注一",
            info_nature=None,
        )
        second = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="未标注二",
            info_nature=None,
        )
        third = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="事实",
            info_nature="fact",
        )
        first.updated_at = datetime(2026, 2, 1, tzinfo=UTC)
        second.updated_at = datetime(2026, 1, 31, 23, 59, tzinfo=UTC)
        third.updated_at = datetime(2026, 2, 15, tzinfo=UTC)
        await db.flush()
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
        )
        nature = await aggregate_entries_handler(
            db,
            ctx,
            AggregateEntriesParams.model_validate(
                {"entry_set": {}, "operation": "group_count", "group_by": "info_nature"}
            ),
        )
        months = await aggregate_entries_handler(
            db,
            ctx,
            AggregateEntriesParams.model_validate(
                {"entry_set": {}, "operation": "group_count", "group_by": "updated_month"}
            ),
        )

    assert nature.payload["buckets"] == [
        {"key": "fact", "count": 1},
        {"key": "unspecified", "count": 2},
    ]
    assert months.payload["buckets"] == [
        {"key": "2026-01", "count": 1},
        {"key": "2026-02", "count": 2},
    ]
    assert nature.completeness == months.completeness == "complete"


async def _no_cancel() -> None:
    return None


@pytest.mark.asyncio
async def test_combined_count_group_and_list_share_collection() -> None:
    """统计、分组、列表共享筛选；列表 limit 不降低精确 count/group。"""
    async with async_session_factory() as db:
        user = await create_user(db, "组合查询")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace)
        node = await create_child_node(db, project, "记录")
        source, attachment = await create_source_attachment(db, workspace, project)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            title="组合查询",
        )
        db.add(conversation)
        await db.flush()
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            project_name=project.name,
            status=RUN_PROCESSING,
            active_slot=ACTIVE_SLOT,
        )
        db.add(run)
        await db.flush()
        for index, nature in enumerate(["experience", "experience", "fact"]):
            await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"记录{index}",
                info_nature=nature,
            )
        plan = normalize_structured_query_plan(
            {
                "entry_set": {},
                "outputs": [
                    {"kind": "count"},
                    {"kind": "group_count", "group_by": "info_nature"},
                    {
                        "kind": "entries",
                        "limit": 1,
                        "sort": {"field": "updated_at", "direction": "desc"},
                    },
                ],
            }
        )
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=run.workspace_id,
            owner_user_id=run.owner_user_id,
            scope_type=run.scope_type,
            project_id=run.project_id,
            project_name=run.project_name,
        )

        result = await execute_structured_query_plan(
            db, ctx, plan, cancel_check=_no_cancel
        )

    assert result.count == {
        "value": 3,
        "status": "completed",
        "completeness": "complete",
    }
    assert result.group_counts[0]["buckets"] == [
        {"key": "experience", "count": 2},
        {"key": "fact", "count": 1},
    ]
    assert result.output_completeness["group_count"]["info_nature"] == "complete"
    assert result.entries is not None and result.entries["returned_count"] == 1
    assert result.output_completeness["entries"] == "limited"


def test_truncation_preserves_count_and_marks_affected_outputs() -> None:
    """JSON 字节截断只降低列表/分组，不篡改已经完成的精确 count。"""
    result = StructuredQueryExecutionResult(
        status="completed",
        set_completeness="complete",
        entries={
            "items": [{"entry_id": index, "excerpt": "长正文" * 100} for index in range(5)],
            "returned_count": 5,
            "has_more": False,
            "completeness": "complete",
        },
        count={"value": 50, "status": "completed", "completeness": "complete"},
        group_counts=[
            {
                "group_by": "updated_month",
                "buckets": [
                    {"key": f"2026-{month:02d}", "count": month}
                    for month in range(1, 13)
                ],
                "truncated": False,
                "completeness": "complete",
            }
        ],
        output_completeness={
            "entries": "complete",
            "count": "complete",
            "group_count": {"updated_month": "complete"},
        },
        warnings=[],
    )

    bounded = apply_execution_byte_budget(result, max_bytes=900)

    assert bounded.count == result.count
    assert bounded.output_completeness["count"] == "complete"
    assert bounded.output_completeness["entries"] == "limited"
    assert bounded.entries is not None and bounded.entries["has_more"] is True
    assert bounded.warnings
