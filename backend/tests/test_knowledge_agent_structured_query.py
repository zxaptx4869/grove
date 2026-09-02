"""结构化查询计划校验、预算与规范化测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.knowledge_agent.structured_query import (
    StructuredQueryPlanError,
    normalize_structured_query_plan,
    persist_structured_query_plan,
    restore_structured_query_plan,
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
