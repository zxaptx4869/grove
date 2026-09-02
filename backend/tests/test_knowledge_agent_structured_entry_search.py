"""结构化 Entry 结果 v1/v2 协议兼容测试。"""

import json
from datetime import UTC, datetime

import pytest

from app.agents.structured_query import StructuredQueryPlanDraft
from app.core.config import get_settings
from app.db.session import async_session_factory
from app.schemas.knowledge_agent import KnowledgeEntryResultSnapshotOut
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runner import execute_run
from tests.test_knowledge_agent_entry_search import (
    _decision,
    _run_for_search,
    _seed_workspace,
    _user_workspace,
)


def _base_snapshot() -> dict:
    return {
        "query": "最近的经验",
        "status": "completed",
        "completeness": "complete",
        "items": [],
        "returned_count": 0,
        "candidate_limit": 50,
        "snapshot_updated_at": datetime.now(UTC).isoformat(),
    }


def test_entry_result_v1_remains_readable() -> None:
    """旧 v1 缺少结构化追加字段时继续按原协议解析。"""
    snapshot = KnowledgeEntryResultSnapshotOut.model_validate(_base_snapshot())

    assert snapshot.schema_version == "v1"
    assert snapshot.set_summary is None
    assert snapshot.count is None
    assert snapshot.group_counts == []
    assert snapshot.output_completeness is None


def test_entry_result_v2_adds_aggregate_without_breaking_v1_fields() -> None:
    """v2 在保留旧客户端字段的同时表达共享集合与独立完整性。"""
    payload = {
        **_base_snapshot(),
        "schema_version": "v2",
        "set_summary": {
            "scope_type": "workspace",
            "main_types": ["knowledge"],
            "info_natures": ["experience"],
            "completeness": "complete",
        },
        "sort": {"field": "updated_at", "direction": "desc"},
        "count": {
            "value": 0,
            "completeness": "complete",
            "status": "empty",
        },
        "group_counts": [
            {
                "group_by": "info_nature",
                "buckets": [{"key": "unspecified", "count": 0}],
                "completeness": "complete",
                "status": "empty",
            }
        ],
        "output_completeness": {
            "entries": "complete",
            "count": "complete",
            "group_count": {"info_nature": "complete"},
        },
    }

    snapshot = KnowledgeEntryResultSnapshotOut.model_validate(payload)

    assert snapshot.schema_version == "v2"
    assert snapshot.query == "最近的经验"
    assert snapshot.items == []
    assert snapshot.count is not None and snapshot.count.value == 0
    assert snapshot.group_counts[0].buckets[0].key == "unspecified"
    assert snapshot.output_completeness is not None
    assert snapshot.output_completeness.count == "complete"


@pytest.mark.asyncio
async def test_entries_runner_uses_one_plan_and_v2_when_enabled(monkeypatch) -> None:
    """开关开启时 entries 走一次计划 + 确定性执行，旧回答分支不受影响。"""

    async def _decide(db, **kwargs):
        del db, kwargs
        return _decision()

    async def _planner(db, workspace_id, **kwargs):
        del db, workspace_id, kwargs
        return (
            StructuredQueryPlanDraft.model_validate(
                {
                    "entry_set": {"main_types": ["knowledge"]},
                    "outputs": [
                        {"kind": "count"},
                        {
                            "kind": "entries",
                            "limit": 2,
                            "sort": {"field": "updated_at", "direction": "desc"},
                        },
                    ],
                }
            ),
            StageMeta(
                purpose="structured_query_plan",
                provider="test",
                model="test-model",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner",
        _planner,
    )
    monkeypatch.setattr(
        get_settings(), "knowledge_agent_structured_query_enabled", True
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db, "v2")
        await _seed_workspace(db, workspace, entry_count=3)
        run = await _run_for_search(db, user, workspace)
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        snapshot = json.loads(run.entry_result_json or "{}")
        assert snapshot["schema_version"] == "v2"
        assert snapshot["count"] == {
            "value": 3,
            "completeness": "complete",
            "status": "completed",
        }
        assert snapshot["returned_count"] == 2
        assert snapshot["output_completeness"]["count"] == "complete"
        assert snapshot["output_completeness"]["entries"] == "limited"
        assert run.structured_query_plan_json is not None


@pytest.mark.asyncio
async def test_entries_runner_falls_back_to_v1_when_plan_fails(monkeypatch) -> None:
    """规划失败显式留痕并回退旧有限查找，不伪造 v2 聚合。"""

    async def _decide(db, **kwargs):
        del db, kwargs
        return _decision()

    async def _planner(db, workspace_id, **kwargs):
        del db, workspace_id, kwargs
        return (
            None,
            StageMeta(
                purpose="structured_query_plan",
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置模型",
                duration_ms=1,
            ),
        )

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.structured_query.run_structured_query_planner",
        _planner,
    )
    monkeypatch.setattr(
        get_settings(), "knowledge_agent_structured_query_enabled", True
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db, "v1fallback")
        await _seed_workspace(db, workspace, entry_count=1)
        run = await _run_for_search(db, user, workspace)
        await db.commit()

        await execute_run(db, run)
        await db.commit()

        snapshot = json.loads(run.entry_result_json or "{}")
        fallback = json.loads(run.fallback_summary or "{}")
        assert snapshot["schema_version"] == "v1"
        assert snapshot.get("count") is None
        assert fallback["has_fallback"] is True
        assert any(
            stage["purpose"] == "structured_query_plan"
            for stage in fallback["stages"]
        )
