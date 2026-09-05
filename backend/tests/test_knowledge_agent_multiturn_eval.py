"""评测器自身的反例测试，确保错误结果不会被算作通过。"""

import copy
import sqlite3

import httpx
import pytest

from evals.knowledge_agent_cases import Turn, build_cases
from evals.knowledge_agent_multiturn import (
    Oracle,
    blocked_reason,
    collect_facts,
    compare_reports,
    evaluate_turn,
    wait_run,
)


def sample():
    snapshot = {
        "projects": [{"id": 1, "name": "有记录"}, {"id": 2, "name": "空项目"}],
        "entries": [
            {"id": 10, "project_id": 1, "main_type": "knowledge", "updated_at": "2026-01-01"},
            {"id": 11, "project_id": 1, "main_type": "method", "updated_at": "2026-01-02"},
        ],
    }
    run = {
        "status": "completed",
        "context_decision": "new_topic",
        "answer": None,
        "entry_result": {
            "set_summary": {"main_types": [], "completeness": "complete"},
            "count": {"value": 2, "completeness": "complete"},
            "items": [],
        },
    }
    observation = {
        "model_invocations": [
            {"model": "真实模型", "provider": "llm", "is_fallback": False},
        ],
        "tool_calls": [],
    }
    return snapshot, run, observation


def test_count_rejects_narrowed_scope_and_incomplete_even_with_matching_number():
    snapshot, run, observation = sample()
    turn = Turn("全部正式记录多少条")
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "pass"
    run["entry_result"]["set_summary"]["main_types"] = ["knowledge"]
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "fail"
    run["entry_result"]["set_summary"]["main_types"] = []
    run["entry_result"]["count"]["completeness"] = "limited"
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "fail"


def test_fallback_or_clarification_cannot_pass_count():
    snapshot, run, observation = sample()
    observation["model_invocations"][0]["is_fallback"] = True
    result = evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)
    assert result["status"] == "fail"
    assert "未证明本轮真实模型调用成功" in result["errors"]
    observation["model_invocations"][0]["is_fallback"] = False
    run["context_decision"] = "clarify"
    result = evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)
    assert "不必要澄清" in result["errors"]


def test_group_requires_all_expected_buckets_including_empty_projects():
    snapshot, run, observation = sample()
    run["entry_result"].pop("count")
    group = {
        "group_by": "project",
        "completeness": "complete",
        "buckets": [{"key": "1", "count": 2}],
    }
    run["entry_result"]["group_counts"] = [group]
    turn = Turn("按项目分，含零条项目", "group", group_by="project")
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "fail"
    group["buckets"].append({"key": "2", "count": 0})
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "pass"


def test_list_checks_order_and_reference_uses_actually_displayed_second_item():
    snapshot, run, observation = sample()
    turn = Turn("最近五条", "list")
    run["entry_result"]["items"] = [{"entry_id": 11}, {"entry_id": 10}]
    assert evaluate_turn(turn, run, {}, observation, snapshot, 1)["status"] == "pass"
    run["entry_result"]["items"].reverse()
    assert evaluate_turn(turn, run, {}, observation, snapshot, 1)["status"] == "fail"
    previous = {"run": copy.deepcopy(run)}
    run["entry_result"] = None
    run["answer"] = {"answer": "解释", "citations": [{"entry_id": 10}]}
    follow = Turn("第二条", "reference", review=True)
    assert evaluate_turn(follow, run, {}, observation, snapshot, 1, previous)["status"] == "fail"
    run["answer"]["citations"] = [{"entry_id": 11}]
    assert evaluate_turn(follow, run, {}, observation, snapshot, 1, previous)["status"] == "review"
    assert evaluate_turn(follow, run, {}, observation, snapshot, 1)["status"] == "blocked"


def test_composite_tool_fact_must_be_displayed_and_linked_to_matching_set():
    diagnostic = {
        "composite_answer_plan": {
            "structured_requests": [
                {"id": "s1", "query_plan": {"entry_set": {"main_types": []}}},
            ]
        },
        "composite_answer_execution": {
            "tool_facts": [
                {
                    "request_id": "s1",
                    "kind": "count",
                    "text": "共 2 条。\n完整统计。",
                    "completeness": "complete",
                    "summary": {"value": 2},
                }
            ]
        },
    }
    run = {"answer": {"answer": "没展示统计"}}
    assert collect_facts(run, diagnostic) == []
    run["answer"]["answer"] = "共 2 条。\n完整统计。"
    assert collect_facts(run, diagnostic)[0]["value"] == 2


def test_oracle_is_read_only_and_resolves_default_workspace(tmp_path):
    path = tmp_path / "oracle.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE users(id INTEGER, username TEXT);
            CREATE TABLE workspace_members(user_id INTEGER, workspace_id INTEGER, created_at TEXT);
            INSERT INTO users VALUES(1, 'demo');
            INSERT INTO workspace_members VALUES(1, 7, '2026');
        """)
    oracle = Oracle(path, "demo")
    assert oracle.workspace_id == 7
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        oracle.db.execute("DELETE FROM users")
    oracle.db.close()


def test_discussion_followup_is_blocked_after_failed_explanation():
    turn = Turn("把刚才的方法压缩一下", "discussion", requires_previous_answer=True)
    previous = {"evaluation": {"status": "fail"}}
    assert blocked_reason(turn, previous) is not None
    previous["evaluation"]["status"] = "review"
    assert blocked_reason(turn, previous) is None
    # 补充统计条件仍可独立执行，不因上轮失败就一律跳过。
    assert (
        blocked_reason(
            Turn("包含所有类型，重新统计总数"),
            {"evaluation": {"status": "fail"}},
        )
        is None
    )


@pytest.mark.asyncio
async def test_run_polling_waits_for_terminal_and_requests_cancel_on_timeout():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"id": 5, "status": "cancelled"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        result = await wait_run(client, 5, 0)
    assert result["status"] == "cancelled"
    assert calls == [
        ("POST", "/api/knowledge-agent/runs/5/cancel"),
        ("GET", "/api/knowledge-agent/runs/5"),
    ]


def test_suite_comparison_rejects_changed_data_or_scenarios():
    old = {
        "baseline": {"domain_hashes": {"entries": "same"}},
        "provider": ["model"],
        "suite_digest": "same",
        "domain_unchanged": True,
        "cases": [],
    }
    new = copy.deepcopy(old)
    assert compare_reports(old, new)["comparable_data_model_suite"]
    new["suite_digest"] = "different"
    assert not compare_reports(old, new)["comparable_data_model_suite"]
    assert len(build_cases("装修", "旅行")) == 12
    assert len(build_cases("装修", None)) == 9
