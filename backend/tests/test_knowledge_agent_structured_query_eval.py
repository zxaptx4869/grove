"""知识 Agent B1 结构化查询代表性评估。

评估夹具描述用户目标和期望结构，不参与生产路由或计划生成，避免把单条
中文问法固化为关键词规则。模型候选仍必须经过服务端规范化后才能执行。
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.agents.result_mode import ResultModeRouteDraft
from app.agents.semantic import SemanticRankingDraft, SemanticRankResult
from app.db.session import async_session_factory
from app.models import KnowledgeAgentRun, KnowledgeConversation
from app.models.knowledge_agent import ACTIVE_SLOT, RUN_PROCESSING, SCOPE_PROJECT
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.result_mode import resolve_result_mode
from app.services.knowledge_agent.structured_query import (
    normalize_structured_query_plan,
)
from app.services.knowledge_agent.structured_query_execution import (
    execute_structured_query_plan,
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

PLAN_EVAL_CASES = [
    pytest.param(
        "统计今年一月至二月的经验，并按月份分组后列出最近五条",
        {
            "entry_set": {
                "info_natures": ["experience"],
                "updated_at": {
                    "from": "2026-01-01T00:00:00+08:00",
                    "to": "2026-03-01T00:00:00+08:00",
                },
            },
            "outputs": [
                {
                    "kind": "entries",
                    "limit": 5,
                    "sort": {"field": "updated_at", "direction": "desc"},
                },
                {"kind": "group_count", "group_by": "updated_month"},
                {"kind": "count"},
            ],
        },
        ["count", "group_count", "entries"],
        "exact_filter_count_sort_group",
        id="natural-date-count-group-list",
    ),
    pytest.param(
        "找与防水验收相关的方法，并按相关性列出",
        {
            "entry_set": {
                "semantic_query": "防水验收",
                "main_types": ["method"],
            },
            "outputs": [
                {"kind": "count"},
                {
                    "kind": "entries",
                    "limit": 6,
                    "sort": {"field": "relevance", "direction": "desc"},
                },
            ],
        },
        ["count", "entries"],
        "semantic_structured_combination",
        id="semantic-and-structured",
    ),
]


@pytest.mark.parametrize(
    ("objective", "candidate", "expected_outputs", "capability"),
    PLAN_EVAL_CASES,
)
def test_eval_candidate_plan_is_normalized_without_phrase_rules(
    objective: str,
    candidate: dict,
    expected_outputs: list[str],
    capability: str,
) -> None:
    """代表性问法只作为评估输入，结果由闭合候选协议与服务端校验决定。"""
    plan = normalize_structured_query_plan(candidate)

    assert objective
    assert capability in {
        "exact_filter_count_sort_group",
        "semantic_structured_combination",
    }
    assert [output.kind for output in plan.outputs] == expected_outputs
    assert plan.prompt_version == "v1"
    assert "reason" not in plan.model_dump(mode="json")
    if plan.entry_set.updated_at is not None:
        assert plan.entry_set.updated_at.from_ == datetime(2025, 12, 31, 16, tzinfo=UTC)
        assert plan.entry_set.updated_at.to == datetime(2026, 2, 28, 16, tzinfo=UTC)


async def _seed_run_context(db, *, label: str):
    user = await create_user(db, label)
    workspace = await create_workspace(db, user)
    project = await create_project(db, workspace, "目标项目")
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_PROJECT,
        project_id=project.id,
        title=label,
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
    return (
        workspace,
        project,
        run,
        RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=project.id,
            project_name=project.name,
        ),
    )


async def _no_cancel() -> None:
    return None


@pytest.mark.asyncio
async def test_eval_exact_count_group_and_recent_list_share_one_set() -> None:
    """精确聚合直接查询共享集合，Entry limit 只降低列表完整性。"""
    async with async_session_factory() as db:
        workspace, project, _run, ctx = await _seed_run_context(db, label="精确组合评估")
        node = await create_child_node(db, project, "经验")
        source, attachment = await create_source_attachment(db, workspace, project)
        entries = []
        for index, month in enumerate((1, 2, 2), start=1):
            entry = await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"经验 {index}",
                info_nature="experience",
            )
            entry.updated_at = datetime(2026, month, index, tzinfo=UTC)
            entries.append(entry)
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="范围内事实",
            info_nature="fact",
        )
        await db.flush()
        plan = normalize_structured_query_plan(
            {
                "entry_set": {
                    "info_natures": ["experience"],
                    "updated_at": {
                        "from": "2026-01-01T00:00:00Z",
                        "to": "2026-03-01T00:00:00Z",
                    },
                },
                "outputs": [
                    {"kind": "count"},
                    {"kind": "group_count", "group_by": "updated_month"},
                    {
                        "kind": "entries",
                        "limit": 2,
                        "sort": {"field": "updated_at", "direction": "desc"},
                    },
                ],
            }
        )

        result = await execute_structured_query_plan(db, ctx, plan, cancel_check=_no_cancel)

    assert result.count == {
        "value": 3,
        "status": "completed",
        "completeness": "complete",
    }
    assert result.group_counts[0]["buckets"] == [
        {"key": "2026-01", "count": 1},
        {"key": "2026-02", "count": 2},
    ]
    assert result.output_completeness == {
        "entries": "limited",
        "count": "complete",
        "group_count": {"updated_month": "complete"},
    }
    assert [item["entry_id"] for item in result.entries["items"]] == [
        entries[2].id,
        entries[1].id,
    ]


@pytest.mark.asyncio
async def test_eval_semantic_combination_reuses_top_k_and_never_claims_total(
    monkeypatch,
) -> None:
    """语义与结构化组合只召回一次，count/list 均保持 limited。"""
    recall_calls = 0

    async def _hybrid(db, workspace_id, entries, query, limit):
        nonlocal recall_calls
        del db, workspace_id, query, limit
        recall_calls += 1
        return list(entries), {}, None

    async def _rerank(db, workspace_id, query, entries, strict=False):
        del db, workspace_id, query
        assert strict is True
        return (
            SemanticRankingDraft(
                results=[
                    SemanticRankResult(entry_id=entry.id, reason="相关")
                    for entry in reversed(entries)
                ]
            ),
            "test",
            "eval-model",
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
        workspace, project, _run, ctx = await _seed_run_context(db, label="语义组合评估")
        node = await create_child_node(db, project, "方法")
        source, attachment = await create_source_attachment(db, workspace, project)
        for index in range(2):
            await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"防水方法 {index}",
                main_type="method",
            )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="范围内事实",
            main_type="knowledge",
        )
        plan = normalize_structured_query_plan(
            {
                "entry_set": {
                    "semantic_query": "防水验收",
                    "main_types": ["method"],
                },
                "outputs": [
                    {"kind": "count"},
                    {
                        "kind": "entries",
                        "limit": 6,
                        "sort": {"field": "relevance", "direction": "desc"},
                    },
                ],
            }
        )

        result = await execute_structured_query_plan(db, ctx, plan, cancel_check=_no_cancel)

    assert recall_calls == 1
    assert result.set_completeness == "limited"
    assert result.count["value"] == 2
    assert result.count["completeness"] == "limited"
    assert result.entries["completeness"] == "limited"


@pytest.mark.asyncio
async def test_eval_result_shape_route_keeps_explicit_and_auto_contract(
    monkeypatch,
) -> None:
    """显式 entries 不调用模型；auto 只采用结构化路由结果。"""
    calls = 0

    async def _router(db, workspace_id, **kwargs):
        nonlocal calls
        del db, workspace_id, kwargs
        calls += 1
        return (
            ResultModeRouteDraft(mode="entries", reason="需要返回知识对象"),
            StageMeta(
                purpose="result_mode_route",
                provider="test",
                model="eval-router",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.result_mode.get_settings",
        lambda: SimpleNamespace(knowledge_agent_result_mode_router_enabled=True),
    )
    monkeypatch.setattr("app.services.knowledge_agent.result_mode.run_result_mode_router", _router)
    explicit = await resolve_result_mode(
        object(),
        workspace_id=1,
        request_mode="entries",
        objective="列对象",
        scope_label="全部知识",
        topic_summary=None,
    )
    automatic = await resolve_result_mode(
        object(),
        workspace_id=1,
        request_mode="auto",
        objective="列对象",
        scope_label="全部知识",
        topic_summary=None,
    )

    assert explicit.mode == automatic.mode == "entries"
    assert explicit.meta is None
    assert automatic.meta is not None and automatic.meta.model == "eval-router"
    assert calls == 1
