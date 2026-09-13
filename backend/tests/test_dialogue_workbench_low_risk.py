"""155042 会话：声明去重、纯结构文案和完整零值复用的边界回归。"""

import copy
from types import SimpleNamespace

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from app.db.session import async_session_factory
from app.models import Entry, Node, WorkspaceMember
from evals.dialogue_loop import loop
from evals.dialogue_loop.core import DialogueAnswer
from evals.dialogue_loop.instrumentation import BudgetedModel
from tests.test_dialogue_workbench_continuity import output
from tests.test_knowledge_agent_dialogue_loop import _seed_finalize_material, _state


def text_answer(text):
    return DialogueAnswer.model_validate({"blocks": [{"kind": "text", "text": text}]})


@pytest.mark.parametrize("source", ["Source原文", "Source 原文", "Source\n原文", "来源原文"])
def test_candidate_boundary_whitespace_does_not_add_second_note(source):
    text = f"候选正文保持原样。尚未写入正式记录，模型补充不属于{source}。"
    result = loop._content_only_boundary(text_answer(text))
    assert result.blocks[0].text == text
    assert loop._content_only_boundary(result) == result


def test_semantic_query_cache_is_cleared_before_each_turn():
    state = _state()
    state.semantic_search_results["same"] = "rs-old"
    state.begin_turn(99, "重新查一下洗碗机")
    assert state.semantic_search_results == {}


@pytest.mark.asyncio
async def test_semantic_query_reuse_requires_current_turn_handle(monkeypatch):
    state = _state()
    state.begin_turn(10, "第一次查询")
    calls = []

    async def fake_dispatch(ctx, tool_name, params, kind, *, surface_tool, audit_params):
        calls.append(params)
        handle = state.store_result(
            "list", {"items": [{"entry_id": 1}]}, "completed", "complete"
        )
        return {"tool": surface_tool, "result_handle": handle, "status": "completed",
                "completeness": "complete", "payload": {"items": [{"entry_id": 1}]}}

    monkeypatch.setattr(loop, "_dispatch", fake_dispatch)
    ctx = SimpleNamespace(deps=SimpleNamespace(state=state))
    first = await loop._semantic_search_dispatch(
        ctx, search_key="same", dispatch_tool="search_knowledge", params={"q": "x"},
        surface_tool="search_knowledge", audit_params={"q": "x"},
    )
    second = await loop._semantic_search_dispatch(
        ctx, search_key="same", dispatch_tool="query_entries", params={"q": "x"},
        surface_tool="query_entries", audit_params={"q": "x"},
    )
    assert len(calls) == 1
    assert second["reason_code"] == "duplicate_semantic_query"
    assert second["result_handle"] == first["result_handle"]

    state.begin_turn(11, "明确重新查询")
    third = await loop._semantic_search_dispatch(
        ctx, search_key="same", dispatch_tool="search_knowledge", params={"q": "x"},
        surface_tool="search_knowledge", audit_params={"q": "x"},
    )
    assert len(calls) == 2
    assert third["status"] == "completed"


@pytest.mark.asyncio
async def test_semantic_query_does_not_reuse_error_or_not_executed_record(monkeypatch):
    state = _state()
    state.begin_turn(10, "查询")
    calls = []

    async def fake_dispatch(ctx, tool_name, params, kind, *, surface_tool, audit_params):
        calls.append(params)
        handle = state.store_result("list", {"items": []}, "error", "limited")
        return {"tool": surface_tool, "result_handle": handle, "status": "error",
                "completeness": "limited", "payload": {"items": []}}

    monkeypatch.setattr(loop, "_dispatch", fake_dispatch)
    ctx = SimpleNamespace(deps=SimpleNamespace(state=state))
    first = await loop._semantic_search_dispatch(
        ctx, search_key="same", dispatch_tool="search_knowledge", params={},
        surface_tool="search_knowledge", audit_params={},
    )
    second = await loop._semantic_search_dispatch(
        ctx, search_key="same", dispatch_tool="search_knowledge", params={},
        surface_tool="search_knowledge", audit_params={},
    )
    assert first["status"] == second["status"] == "error"
    assert len(calls) == 2


def test_only_duplicate_program_note_is_removed_without_rewriting_candidate():
    text = "正文和待核实项都保持原样。尚未写入，模型补充不属于Source原文。"
    duplicated = text + "\n（模型补充不属于 Source 原文。）"
    assert loop._content_only_boundary(text_answer(duplicated)).blocks[0].text == text
    missing = loop._content_only_boundary(text_answer("完整候选正文"))
    assert missing.blocks[0].text.startswith("完整候选正文")
    assert missing.blocks[0].text.count("尚未写入") == 1
    assert missing.blocks[0].text.count("Source 原文") == 1
    state = _state()
    state.editing_active = True
    state.editing_purpose = "candidate"
    state.editing_content_only = True
    invalid = loop._content_only_boundary(
        text_answer("已写入正式 Entry。模型补充不属于Source原文。")
    )
    assert "候选修改稿不得声称已经写入或修改正式记录" in loop.output_errors(invalid, state)


@pytest.mark.parametrize("kind", ["statistic", "directories", "projects"])
def test_structural_render_removes_only_irrelevant_fixed_sentence(kind):
    state = _state()
    state.current_message = "查一下数量和目录"
    handle = state.store_result(
        kind, {"value": 0, "items": [], "projects": []}, "completed", "complete"
    )
    scope = "仅统计目录本身，不含子目录。"
    redundant = "该统计不代表对记录内容做过官方交叉验证。"
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "text", "text": scope + redundant},
                {"kind": "result", "result_handle": handle},
            ]
        }
    )
    text, blocks = loop.render_answer(answer, state)
    assert scope in text and redundant not in text
    assert blocks[-1]["handle"] == handle
    state.current_message = "这个统计经过官方核验了吗，来源是什么"
    assert redundant in loop.render_answer(answer, state)[0]
    state.current_message = "数量是多少"
    state.result_sets[handle].completeness = "partial"
    assert redundant in loop.render_answer(answer, state)[0]


def test_mixed_entry_answer_keeps_source_explanation():
    state = _state()
    count = state.store_result("statistic", {"value": 1}, "completed", "complete")
    entry = state.store_result(
        "entries",
        {"items": [{"entry_id": 1, "title": "原记录", "content": "已有内容"}]},
        "completed",
        "complete",
    )
    note = "该统计不代表对记录内容做过官方交叉验证。"
    answer = DialogueAnswer.model_validate(
        {
            "blocks": [
                {"kind": "result", "result_handle": count},
                {"kind": "result", "result_handle": entry},
                {"kind": "text", "text": note},
            ]
        }
    )
    assert note in loop.render_answer(answer, state)[0]


def zero_proof_state():
    state = _state()
    params = loop._count_params("project", "房子装修", ["knowledge"])
    params.update(project_id=1, node_id=2, node_scope="direct")
    handle = state.store_result("statistic", {"value": 0}, "empty", "complete")
    state.tool_events.append(
        {
            "tool": "count_entries",
            "shared_tool": "aggregate_entries",
            "shared_params": params,
            "result_handle": handle,
            "turn_index": state.turn_index,
        }
    )
    query = copy.deepcopy(params)
    query.pop("operation")
    query.pop("group_by")
    return state, handle, query


@pytest.mark.parametrize(
    "mutation",
    [
        "historical",
        "hidden",
        "failed",
        "partial",
        "truncated",
        "group",
        "search",
        "boolean",
        "nonzero",
        "missing_value",
        "project",
        "node",
        "subtree",
        "type",
        "semantic_count",
    ],
)
def test_zero_proof_never_leaks_across_scope_or_uses_incomplete_results(mutation):
    state, handle, query = zero_proof_state()
    assert loop._zero_count_proof(state, query).handle == handle
    record = state.result_sets[handle]
    event = state.tool_events[-1]
    if mutation == "historical":
        state.begin_turn(99, "新问题")
    elif mutation == "hidden":
        record.displayable = False
    elif mutation == "failed":
        record.status = "error"
    elif mutation == "partial":
        record.completeness = "partial"
    elif mutation == "truncated":
        record.payload["truncated"] = True
    elif mutation == "group":
        event["shared_params"]["operation"] = "group_count"
        record.payload["buckets"] = [{"count": 0}]
    elif mutation == "search":
        event["shared_tool"] = "search_knowledge"
    elif mutation == "boolean":
        record.payload["value"] = False
    elif mutation == "nonzero":
        record.payload["value"] = 1
    elif mutation == "missing_value":
        record.payload.pop("value")
    elif mutation == "project":
        query["project_id"] = 9
    elif mutation == "node":
        query["node_id"] = 9
    elif mutation == "subtree":
        query["node_scope"] = "subtree"
    elif mutation == "type":
        query["entry_set"]["main_types"] = ["method"]
    elif mutation == "semantic_count":
        event["shared_params"]["entry_set"]["semantic_query"] = "局部召回"
    assert loop._zero_count_proof(state, query) is None


@pytest.mark.asyncio
async def test_real_empty_directory_reuses_zero_but_subtree_still_executes():
    state = _state()
    seeded = await _seed_finalize_material(state)
    async with async_session_factory() as db:
        entry = await db.get(Entry, seeded["entry_id"])
        child = await db.get(Node, entry.node_id)
        parent = Node(project_id=entry.project_id, name="风格设计", position=0)
        db.add(parent)
        await db.flush()
        child.parent_id = parent.id
        await db.commit()
        parent_id, project_id = parent.id, parent.project_id
    state.instrumentation.context_policy_enabled = True
    state.begin_turn(100, "先列出目录本身，再列出包含子目录的记录")
    directory = state.store_result(
        "directories",
        {
            "project": {"id": project_id, "name": "房子装修"},
            "items": [
                {
                    "node_id": parent_id,
                    "name": "风格设计",
                    "project_id": project_id,
                    "project_name": "房子装修",
                    "path": "风格设计",
                }
            ],
        },
        "completed",
        "complete",
    )
    base = {
        "project_scope": "project",
        "project_name": "房子装修",
        "directory_result_handle": directory,
        "directory_position": 1,
    }
    handles = []
    calls = []

    def respond(messages, info):
        calls.append(info)
        if len(calls) == 1:
            return ModelResponse(
                parts=[ToolCallPart("count_entries", {**base, "directory_scope": "direct"})]
            )
        handles.append(state.tool_events[-1]["result_handle"])
        if len(calls) == 2:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_entries",
                        {
                            **base,
                            "directory_scope": "direct",
                            "semantic_query": "风格设计",
                        },
                    )
                ]
            )
        if len(calls) == 3:
            assert state.tool_events[-1]["reason_code"] == "zero_count_reused"
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_entries",
                        {
                            **base,
                            "directory_scope": "subtree",
                            "semantic_query": None,
                        },
                    )
                ]
            )
        return output(info, [{"kind": "result", "result_handle": handle} for handle in handles])

    model = BudgetedModel(FunctionModel(respond), state.instrumentation, "dialogue_agent")
    turn, _ = await loop.run_turn(loop.build_agent(model), state, state.current_message, [])
    assert turn["status"] == "completed", turn
    assert [e.get("reason_code") for e in turn["tool_calls"]].count("zero_count_reused") == 1
    assert len([e for e in turn["tool_calls"] if e.get("shared_tool") == "query_entries"]) == 1
    assert state.result_sets[handles[1]].payload["items"] == []
    assert state.result_sets[handles[2]].payload["items"][0]["entry_id"] == seeded["entry_id"]
    assert turn["budget"]["turn"]["tool_calls"] == 2
    assert turn["budget"]["turn"]["embedding_requests"] == 0


@pytest.mark.asyncio
async def test_zero_cache_revalidates_workspace_membership():
    state, _, query = zero_proof_state()
    seeded = await _seed_finalize_material(state)
    from sqlalchemy import delete

    async with async_session_factory() as db:
        await db.execute(
            delete(WorkspaceMember).where(
                WorkspaceMember.workspace_id == seeded["workspace_id"],
                WorkspaceMember.user_id == seeded["user_id"],
            )
        )
        await db.commit()
    with pytest.raises(ValueError):
        await loop._reuse_zero_count(state, query, {})
