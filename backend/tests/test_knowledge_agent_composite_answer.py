"""知识 Agent quick 复合回答计划与快照协议测试。"""

import pytest
from pydantic import ValidationError

from app.agents.composite_answer import CompositeAnswerPlanDraft
from app.schemas.knowledge_agent import (
    KnowledgeAnswerPointOut,
    KnowledgeCompositeAnswerCoverageOut,
    KnowledgeCompositeAnswerPlanSummaryOut,
)
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
)


def _candidate_plan() -> dict:
    return {
        "schema_version": "v1",
        "requirements": [
            {
                "id": "definition",
                "order": 0,
                "summary": "解释甲醛是什么",
                "kind": "explain",
                "basis_policy": "model_allowed",
            },
            {
                "id": "sources",
                "order": 1,
                "summary": "结合个人知识说明甲醛来源",
                "kind": "retrieve",
                "basis_policy": "grove_required",
            },
        ],
        "statement_message_ids": [12],
        "retrieval_requests": [
            {
                "id": "search_sources",
                "query": "甲醛 来源",
                "requirement_ids": ["sources"],
            }
        ],
        "structured_requests": [],
        "reason": "概念解释与个人知识需要不同依据",
    }


def test_composite_answer_draft_uses_closed_bounded_schema() -> None:
    """候选协议允许多义务，但拒绝未知字段、未知枚举和越界列表。"""
    plan = CompositeAnswerPlanDraft.model_validate(_candidate_plan())
    assert [item.id for item in plan.requirements] == ["definition", "sources"]
    assert plan.retrieval_requests[0].requirement_ids == ["sources"]

    invalid = _candidate_plan()
    invalid["workspace_id"] = 999
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)

    invalid = _candidate_plan()
    invalid["requirements"][0]["basis_policy"] = "browse_everything"
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)

    invalid = _candidate_plan()
    invalid["requirements"] = invalid["requirements"] * 5
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(invalid)


def test_composite_execution_and_coverage_snapshots_reject_unknown_fields() -> None:
    """恢复快照同样使用闭合 schema，历史 JSON 不能扩大解释。"""
    execution = CompositeAnswerExecutionSnapshot.model_validate(
        {
            "schema_version": "v1",
            "inputs": [
                {
                    "request_id": "search_sources",
                    "kind": "retrieval",
                    "requirement_ids": ["r2"],
                    "fingerprint": "a" * 64,
                    "status": "completed",
                    "completeness": "limited",
                    "entry_ids": [1],
                    "evidence_handles": ["ev_12345678"],
                }
            ],
            "tool_facts": [],
        }
    )
    assert execution.inputs[0].request_id == "search_sources"

    with pytest.raises(ValidationError):
        CompositeAnswerExecutionSnapshot.model_validate(
            {"schema_version": "v1", "inputs": [], "tool_facts": [], "scope": "all"}
        )

    coverage = CompositeAnswerCoverageSnapshot.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "requirement_id": "r1",
                    "status": "answered",
                    "model_knowledge_used": True,
                }
            ],
        }
    )
    assert coverage.requirements[0].status == "answered"


def test_public_composite_fields_are_optional_and_legacy_points_remain_valid() -> None:
    """新增字段为可选；旧 point 可读取，新 point 可保留义务绑定。"""
    legacy = KnowledgeAnswerPointOut.model_validate(
        {"section": "定义", "text": "甲醛是一种挥发性有机化合物。"}
    )
    assert legacy.requirement_ids == []

    current = KnowledgeAnswerPointOut.model_validate(
        {
            "section": "定义",
            "text": "甲醛是一种挥发性有机化合物。",
            "requirement_ids": ["r1"],
        }
    )
    assert current.requirement_ids == ["r1"]

    plan = KnowledgeCompositeAnswerPlanSummaryOut.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "id": "r1",
                    "order": 0,
                    "summary": "解释甲醛是什么",
                    "kind": "explain",
                    "basis_policy": "model_allowed",
                }
            ],
            "input_kinds": [],
        }
    )
    assert plan.requirements[0].id == "r1"

    public_coverage = KnowledgeCompositeAnswerCoverageOut.model_validate(
        {
            "schema_version": "v1",
            "requirements": [
                {
                    "requirement_id": "r1",
                    "summary": "解释甲醛是什么",
                    "status": "answered",
                    "basis_kinds": ["model_knowledge"],
                }
            ],
        }
    )
    assert public_coverage.requirements[0].basis_kinds == ["model_knowledge"]
