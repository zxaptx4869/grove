"""评测器自身的反例测试，确保错误结果不会被算作通过。"""

import copy
import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

from evals.knowledge_agent_cases import Turn, build_cases, build_core_baseline_cases
from evals.knowledge_agent_multiturn import (
    Oracle,
    apply_semantic_review,
    blocked_reason,
    collect_facts,
    compare_reports,
    evaluate_turn,
    request,
    run_suite,
    save_report,
    wait_run,
)


@pytest.mark.asyncio
async def test_missing_comparison_file_fails_before_authentication_or_model_calls(tmp_path):
    with pytest.raises(FileNotFoundError):
        await run_suite(SimpleNamespace(compare=tmp_path / "missing.json"), "unused")


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
        "project_id": None,
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
    run["project_id"] = 1
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


def test_matching_workspace_total_does_not_prove_named_project_was_filtered():
    snapshot, run, observation = sample()
    turn = Turn("只统计有记录项目", oracle_scope="project")
    # 数据恰好都在项目 1，Workspace 总数也为 2，但执行范围没有收敛。
    result = evaluate_turn(turn, run, {}, observation, snapshot, 1)
    assert result["expected"] == result["actual"][0] == 2
    assert result["status"] == "fail"
    run["project_id"] = 1
    assert evaluate_turn(turn, run, {}, observation, snapshot, 1)["status"] == "pass"


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


def test_core_suite_is_fixed_small_and_uses_dynamic_targets():
    targets = [
        {"id": 501, "title": "动态标题甲", "project_name": "项目甲"},
        {"id": 502, "title": "动态标题乙", "project_name": "项目甲"},
    ]
    cases = build_core_baseline_cases(targets)
    assert len(cases) == 4
    assert sum(len(case.turns) for case in cases) == 19
    serialized = str(cases)
    assert "动态标题甲" in serialized and "动态标题乙" in serialized
    continuation = cases[1].turns[-2]
    assert continuation.only_if_continuation
    assert blocked_reason(continuation, {"run": {}}) == (
        "上轮未产生合法 continuation，本轮按预定标准记为未覆盖"
    )


def test_completed_but_irrelevant_candidate_stays_pending_semantic_review():
    snapshot, run, observation = sample()
    run["answer"] = {"answer": "项目共 2 个"}
    result = evaluate_turn(
        Turn(
            "按分析生成候选",
            "candidate",
            review=True,
            semantic_criteria=("承接分析",),
        ),
        run,
        {"assistant_text": "这是一段与候选任务无关的回答"},
        observation,
        snapshot,
        None,
    )
    assert result["deterministic"]["status"] == "pass"
    assert result["semantic"]["status"] == "pending"
    assert result["status"] == "review"


def test_successful_model_call_does_not_hide_continuation_without_progress():
    snapshot, run, observation = sample()
    observation["model_invocations"][0]["purpose"] = "dialogue_agent"
    previous = {"diagnostic": {"assistant_text": "完全相同的旧稿"}}
    result = evaluate_turn(
        Turn("继续", "continuation", review=True),
        run,
        {"assistant_text": "完全相同的旧稿"},
        observation,
        snapshot,
        None,
        previous,
    )
    assert result["deterministic"]["status"] == "fail"
    assert "续接只重放上一轮回答，没有实际进展" in result["errors"]


def test_candidate_search_result_cannot_bypass_selection_boundary():
    snapshot, run, observation = sample()
    run["entry_result"] = {"items": [{"entry_id": 10}]}
    run["dialogue_blocks"] = [
        {
            "kind": "list",
            "items": [{"entry_id": 10}],
            "semantics": {"result_role": "candidate"},
        }
    ]
    observation["tool_calls"] = [
        {"tool_name": "query_entries", "params_summary": "{}", "result_summary": "{}"}
    ]
    result = evaluate_turn(
        Turn(
            "检索",
            "search",
            target_entry_id=10,
            required_tools=("query_entries",),
        ),
        run,
        {"assistant_text": "候选"},
        observation,
        snapshot,
        None,
    )
    assert result["deterministic"]["status"] == "fail"
    assert "未筛选候选被当作可展示列表" in result["errors"]


@pytest.mark.asyncio
async def test_mock_api_login_submit_and_poll_are_sequential():
    calls = []

    def handler(http_request):
        calls.append((http_request.method, http_request.url.path))
        if http_request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"run": {"id": 9, "status": "waiting"}})
        return httpx.Response(200, json={"id": 9, "status": "completed"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        submitted = await request(
            client,
            "POST",
            "/api/knowledge-agent/conversations/3/messages",
            json={"message": "问题", "client_message_id": "fixed"},
        )
        completed = await wait_run(client, submitted["run"]["id"], 1)
    assert completed["status"] == "completed"
    assert calls == [
        ("POST", "/api/knowledge-agent/conversations/3/messages"),
        ("GET", "/api/knowledge-agent/runs/9"),
    ]


def test_report_is_atomic_sanitized_and_semantic_review_preserves_source(tmp_path):
    report = {
        "batch_id": "batch-1",
        "git_revision": "abc",
        "runtime_version": {"confidence": "test"},
        "status": "completed",
        "cases": [
            {
                "case_id": "case",
                "title": "场景",
                "category": "测试",
                "repeat": 1,
                "turns": [
                    {
                        "message": "问题",
                        "diagnostic": {"assistant_text": "回答", "password": "never-write"},
                        "evaluation": {
                            "status": "review",
                            "errors": [],
                            "execution": {"status": "completed", "error": None},
                            "deterministic": {"status": "pass", "errors": []},
                            "semantic": {"status": "pending", "criteria": ["是否答题"]},
                        },
                    }
                ],
            }
        ],
    }
    save_report(report, tmp_path)
    raw = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert "never-write" not in raw
    assert "<redacted>" in raw
    assert (tmp_path / "summary.md").stat().st_mode & 0o777 == 0o600
    original = raw
    review = tmp_path / "semantic-review.json"
    review.write_text(
        '{"batch_id":"batch-1","reviewed_by":"test","reviews":'
        '[{"case_id":"case","turn":1,"status":"fail","notes":["答非所问"]}]}',
        encoding="utf-8",
    )
    reviewed = apply_semantic_review(tmp_path / "report.json", review)
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == original
    payload = json.loads(reviewed.read_text(encoding="utf-8"))
    assert payload["cases"][0]["turns"][0]["evaluation"]["semantic"]["status"] == "fail"
