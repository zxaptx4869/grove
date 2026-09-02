"""结构化 Entry 结果 v1/v2 协议兼容测试。"""

from datetime import UTC, datetime

from app.schemas.knowledge_agent import KnowledgeEntryResultSnapshotOut


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
