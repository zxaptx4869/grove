"""复合回答第一阶段能力矩阵、安全门禁与只读性评估。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.agents.composite_answer import CompositeAnswerPlanDraft
from app.db.session import async_session_factory
from app.models import (
    Candidate,
    Entry,
    KnowledgeCandidateDraft,
    KnowledgeWorkingSetItem,
    Node,
    Source,
)
from app.services.knowledge_agent.composite_answer import (
    CompositeAnswerPlanError,
    normalize_composite_answer_plan,
)
from app.services.knowledge_agent.composite_answer_execution import (
    execute_composite_answer_plan,
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
from tests.test_knowledge_agent_runner import _conversation_and_run


def _base(requirements: list[dict]) -> dict:
    return {
        "schema_version": "v1",
        "requirements": requirements,
        "statement_message_ids": [],
        "retrieval_requests": [],
        "structured_requests": [],
        "reason": "按回答义务与共享数据需求规划",
    }


def _requirement(
    item_id: str,
    order: int,
    summary: str,
    kind: str,
    policy: str,
) -> dict:
    return {
        "id": item_id,
        "order": order,
        "summary": summary,
        "kind": kind,
        "basis_policy": policy,
    }


@pytest.mark.parametrize(
    ("name", "candidate", "expected"),
    [
        (
            "general",
            _base([_requirement("explain", 0, "解释什么是甲醛", "explain", "model_allowed")]),
            (1, 0, 0),
        ),
        (
            "concept_grove",
            {
                **_base(
                    [
                        _requirement("explain", 0, "解释甲醛", "explain", "model_allowed"),
                        _requirement(
                            "source",
                            1,
                            "结合我的知识说明来源",
                            "retrieve",
                            "grove_required",
                        ),
                    ]
                ),
                "retrieval_requests": [
                    {"id": "q", "query": "甲醛来源", "requirement_ids": ["source"]}
                ],
            },
            (2, 1, 0),
        ),
        (
            "concept_count",
            {
                **_base(
                    [
                        _requirement("explain", 0, "解释环保等级", "explain", "model_allowed"),
                        _requirement("count", 1, "统计参数知识数量", "aggregate", "grove_only"),
                    ]
                ),
                "structured_requests": [
                    {
                        "id": "s",
                        "entry_set": {"main_types": ["parameter"]},
                        "outputs": [{"kind": "count"}],
                        "requirement_ids": ["count"],
                    }
                ],
            },
            (2, 0, 1),
        ),
        (
            "shared_request",
            {
                **_base(
                    [
                        _requirement("total", 0, "统计总数", "aggregate", "grove_only"),
                        _requirement("groups", 1, "按性质分组", "aggregate", "grove_only"),
                    ]
                ),
                "structured_requests": [
                    {
                        "id": "s",
                        "entry_set": {},
                        "outputs": [
                            {"kind": "count"},
                            {"kind": "group_count", "group_by": "info_nature"},
                        ],
                        "requirement_ids": ["total", "groups"],
                    }
                ],
            },
            (2, 0, 1),
        ),
        (
            "compare_recommend",
            {
                **_base(
                    [
                        _requirement("compare", 0, "比较两种方案", "compare", "grove_required"),
                        _requirement("recommend", 1, "给出选择建议", "recommend", "grove_required"),
                    ]
                ),
                "retrieval_requests": [
                    {
                        "id": "q",
                        "query": "方案对比与适用条件",
                        "requirement_ids": ["compare", "recommend"],
                    }
                ],
            },
            (2, 1, 0),
        ),
        (
            "external",
            _base(
                [
                    _requirement(
                        "current",
                        0,
                        "核对当前实时政策",
                        "other",
                        "external_required",
                    )
                ]
            ),
            (1, 0, 0),
        ),
    ],
)
def test_composite_planning_capability_matrix(name, candidate, expected) -> None:
    """代表性问题按义务与输入需求表达，不依赖某个问法关键词。"""
    del name
    plan = normalize_composite_answer_plan(candidate)
    assert (
        len(plan.requirements),
        len(plan.retrieval_requests),
        len(plan.structured_requests),
    ) == expected


def test_natural_knowledge_only_hardens_every_requirement() -> None:
    """自然语言 knowledge-only 的服务端收紧不允许保留通用知识权限。"""
    candidate = {
        **_base(
            [
                _requirement("first", 0, "解释甲醛", "explain", "model_allowed"),
                _requirement("second", 1, "说明来源", "retrieve", "grove_required"),
            ]
        ),
        "retrieval_requests": [
            {
                "id": "q",
                "query": "甲醛定义与来源",
                "requirement_ids": ["first", "second"],
            }
        ],
    }
    plan = normalize_composite_answer_plan(candidate, knowledge_only=True)
    assert [item.summary for item in plan.requirements][0] == "解释甲醛"
    assert {item.basis_policy for item in plan.requirements} == {"grove_only"}


@pytest.mark.parametrize(
    "injected",
    [
        {"workspace_id": 99},
        {"project_id": 88},
        {"entry_ids": [1]},
        {"sql": "DELETE FROM entries"},
        {"tool": "write_entry"},
        {"operation": "update"},
    ],
)
def test_guardrail_rejects_scope_object_sql_unknown_tool_and_write(injected) -> None:
    """授权范围、对象 id、SQL、未知工具与写操作均无法进入候选 schema。"""
    candidate = _base(
        [_requirement("r", 0, "解释概念", "explain", "model_allowed")]
    )
    candidate.update(injected)
    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(candidate)


def test_guardrail_rejects_grove_requirement_without_read_input() -> None:
    """Grove 义务没有关联只读输入时整份计划被拒绝。"""
    with pytest.raises(CompositeAnswerPlanError, match="没有关联只读输入"):
        normalize_composite_answer_plan(
            _base(
                [
                    _requirement(
                        "private",
                        0,
                        "说明我的知识",
                        "retrieve",
                        "grove_only",
                    )
                ]
            )
        )


async def _table_counts(db) -> dict[str, int]:
    models = [Candidate, Entry, KnowledgeCandidateDraft, KnowledgeWorkingSetItem, Node, Source]
    return {
        model.__tablename__: int(
            (await db.execute(select(func.count()).select_from(model))).scalar_one()
        )
        for model in models
    }


@pytest.mark.asyncio
async def test_guardrail_structured_execution_is_readonly_and_project_scoped() -> None:
    """结构化执行只统计 Run 固化项目，不修改事实、候选、草稿、目录或工作集。"""
    async with async_session_factory() as db:
        user = await create_user(db, "复合只读")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "范围内")
        other_project = await create_project(db, workspace, "范围外")
        node = await create_child_node(db, project, "节点")
        other_node = await create_child_node(db, other_project, "其他节点")
        source, attachment = await create_source_attachment(db, workspace, project)
        other_source, other_attachment = await create_source_attachment(
            db, workspace, other_project
        )
        await create_entry_with_evidence(db, project, node, source, attachment)
        await create_entry_with_evidence(
            db,
            other_project,
            other_node,
            other_source,
            other_attachment,
            title="范围外知识",
        )
        _conversation, run = await _conversation_and_run(db, user, workspace, "统计知识")
        run.scope_type = "project"
        run.project_id = project.id
        run.project_name = project.name
        await db.commit()
        before = await _table_counts(db)
        plan = normalize_composite_answer_plan(
            {
                **_base(
                    [
                        _requirement(
                            "count",
                            0,
                            "统计当前项目知识",
                            "aggregate",
                            "grove_only",
                        )
                    ]
                ),
                "structured_requests": [
                    {
                        "id": "s",
                        "entry_set": {},
                        "outputs": [{"kind": "count"}],
                        "requirement_ids": ["count"],
                    }
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

        async def _not_cancelled():
            return None

        artifacts = await execute_composite_answer_plan(
            db,
            run,
            ctx,
            plan,
            cancel_check=_not_cancelled,
        )
        after = await _table_counts(db)

    assert artifacts.snapshot.tool_facts[0].summary["value"] == 1
    assert before == after


def test_guardrail_snapshot_has_no_client_scope_override() -> None:
    """执行器的范围只能来自 RunToolContext，计划与快照均无授权字段。"""
    plan = normalize_composite_answer_plan(
        _base([_requirement("r", 0, "解释概念", "explain", "model_allowed")])
    )
    raw = plan.model_dump(mode="json")
    assert "workspace_id" not in raw and "project_id" not in raw
    assert SimpleNamespace(**raw).schema_version == "v1"
