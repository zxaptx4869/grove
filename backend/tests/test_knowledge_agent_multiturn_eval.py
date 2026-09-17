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
    regrade_saved_report,
    request,
    run_suite,
    save_report,
    summary,
    summary_markdown,
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


def test_dialogue_loop_aggregate_audit_does_not_replace_public_delivery():
    snapshot, run, observation = sample()
    run["entry_result"] = None
    run["answer"] = {"answer": "我不能回答这个问题"}
    observation["tool_calls"] = [
        {
            "tool_name": "aggregate_entries",
            "status": "completed",
            "params_summary": '{"params":{"operation":"count","entry_set":{"main_types":[]}}}',
            "result_summary": '{"operation":"count","value":2,"completeness":"complete"}',
        }
    ]
    result = evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)
    assert result["deterministic"]["status"] == "review"
    assert result["status"] == "review"
    assert "内部统计正确，但未确认公开回答已交付该结果" in result["review_reasons"]


def test_count_public_delivery_rejects_wrong_value_and_accepts_structured_result():
    snapshot, run, observation = sample()
    run["entry_result"] = None
    observation["tool_calls"] = [
        {
            "tool_name": "aggregate_entries",
            "status": "completed",
            "params_summary": '{"params":{"operation":"count","entry_set":{"main_types":[]}}}',
            "result_summary": '{"operation":"count","value":2,"completeness":"complete"}',
        }
    ]
    run["dialogue_blocks"] = [
        {
            "kind": "statistic",
            "result_type": "statistic",
            "value": 99,
            "completeness": "complete",
            "semantics": {
                "subject": "entries",
                "project_scope": "全部项目",
                "main_types": [],
                "completeness": "complete",
            },
        }
    ]
    result = evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)
    assert result["deterministic"]["status"] == "fail"
    assert "公开结构化统计与独立快照不一致" in result["errors"]
    run["dialogue_blocks"][0]["value"] = 2
    assert evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)[
        "deterministic"
    ]["status"] == "pass"


def test_count_public_delivery_rejects_matching_number_with_wrong_scope():
    snapshot, run, observation = sample()
    run["entry_result"] = None
    run["dialogue_blocks"] = [
        {
            "kind": "statistic",
            "result_type": "statistic",
            "value": 2,
            "completeness": "complete",
            "semantics": {
                "subject": "entries",
                "project_scope": "指定项目",
                "project_id": 1,
                "main_types": [],
                "completeness": "complete",
            },
        }
    ]
    result = evaluate_turn(Turn("总数"), run, {}, observation, snapshot, None)
    assert result["deterministic"]["status"] == "fail"
    assert "统计数字未绑定到预期项目范围，不能凭数值巧合判通过" in result["errors"]


def test_project_tool_result_requires_public_structured_enumeration():
    snapshot, run, observation = sample()
    run["entry_result"] = None
    run["answer"] = {"answer": "我不能回答这个问题"}
    observation["tool_calls"] = [
        {
            "tool_name": "list_projects",
            "status": "completed",
            "result_summary": '{"project_count":2}',
        }
    ]
    result = evaluate_turn(Turn("项目", "projects"), run, {}, observation, snapshot, None)
    assert result["deterministic"]["status"] == "review"
    run["dialogue_blocks"] = [
        {
            "kind": "list",
            "result_type": "projects",
            "items": [{"id": 1, "name": "有记录"}, {"id": 2, "name": "空项目"}],
            "completeness": "complete",
            "semantics": {"subject": "projects", "completeness": "complete"},
        }
    ]
    assert evaluate_turn(Turn("项目", "projects"), run, {}, observation, snapshot, None)[
        "deterministic"
    ]["status"] == "pass"


def test_group_tool_result_without_public_delivery_stays_pending_review():
    snapshot, run, observation = sample()
    run["entry_result"] = None
    run["answer"] = {"answer": "已完成分组"}
    observation["tool_calls"] = [
        {
            "tool_name": "aggregate_entries",
            "status": "completed",
            "params_summary": (
                '{"params":{"operation":"group_count","group_by":"project",'
                '"entry_set":{"main_types":[]}}}'
            ),
            "result_summary": (
                '{"operation":"group_count","group_by":"project","completeness":"complete",'
                '"buckets":[{"key":"1","count":2},{"key":"2","count":0}]}'
            ),
        }
    ]
    result = evaluate_turn(
        Turn("按项目分组", "group", group_by="project"),
        run,
        {},
        observation,
        snapshot,
        None,
    )
    assert result["deterministic"]["status"] == "review"
    assert "内部分组统计正确，但未确认公开回答已交付该结果" in result["review_reasons"]


def test_search_accepts_formal_search_tool_name_but_not_duplicate_searches():
    snapshot, run, observation = sample()
    run["entry_result"] = {"items": [{"entry_id": 10}]}
    observation["tool_calls"] = [
        {
            "tool_name": "search_knowledge",
            "status": "completed",
            "params_summary": '{"fingerprint":"one"}',
            "result_summary": '{"returned_count":1}',
        }
    ]
    turn = Turn("检索", "search", target_entry_id=10)
    assert evaluate_turn(turn, run, {}, observation, snapshot, None)["status"] == "pass"
    observation["tool_calls"].append(
        {
            "tool_name": "query_entries",
            "status": "completed",
            "params_summary": '{"fingerprint":"two"}',
            "result_summary": '{"returned_count":1}',
        }
    )
    result = evaluate_turn(turn, run, {}, observation, snapshot, None)
    assert "检索工具预期调用 1 次，实际 2 次" in result["errors"]


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


def test_report_comparison_detects_semantic_change_when_automatic_status_is_stable():
    old = {
        "baseline": {"domain_hashes": {"entries": "same"}},
        "provider": ["model"],
        "suite_digest": "same",
        "grader_sha256": "same",
        "domain_unchanged": True,
        "cases": [
            {
                "case_id": "case",
                "repeat": 1,
                "turns": [
                    {
                        "evaluation": {
                            "status": "review",
                            "execution": {"status": "completed"},
                            "deterministic": {"status": "pass"},
                            "semantic": {"status": "fail"},
                        }
                    }
                ],
            }
        ],
    }
    new = copy.deepcopy(old)
    new["cases"][0]["turns"][0]["evaluation"]["semantic"]["status"] = "pass"
    comparison = compare_reports(old, new)
    assert comparison["changes"] == [
        {
            "case": "case",
            "repeat": 1,
            "turn": 1,
            "layer": "semantic",
            "before": "fail",
            "after": "pass",
            "classification": "improved",
        }
    ]
    assert comparison["layer_classifications"]["execution"] == {
        "unchanged_pass": 1
    }
    assert comparison["layer_classifications"]["deterministic"] == {
        "unchanged_pass": 1
    }


def test_report_comparison_marks_missing_old_layer_unknown():
    old = {
        "baseline": {"domain_hashes": {}},
        "provider": [],
        "suite_digest": "same",
        "grader_sha256": "same",
        "domain_unchanged": True,
        "cases": [{"case_id": "case", "repeat": 1, "turns": [{"evaluation": {}}]}],
    }
    new = copy.deepcopy(old)
    new["cases"][0]["turns"][0]["evaluation"] = {
        "execution": {"status": "completed"},
        "deterministic": {"status": "pass"},
        "semantic": {"status": "pending"},
    }
    comparison = compare_reports(old, new)
    assert {item["layer"] for item in comparison["changes"]} == {
        "execution",
        "deterministic",
        "semantic",
    }
    assert all(item["before"] == "unknown" for item in comparison["changes"])


def test_report_comparison_classifies_unchanged_failures_and_pending_review():
    report = {
        "baseline": {"domain_hashes": {}},
        "provider": [],
        "suite_digest": "same",
        "grader_sha256": "same",
        "domain_unchanged": True,
        "cases": [
            {
                "case_id": "case",
                "repeat": 1,
                "turns": [
                    {
                        "evaluation": {
                            "execution": {"status": "partial"},
                            "deterministic": {"status": "fail"},
                            "semantic": {"status": "pending"},
                        }
                    }
                ],
            }
        ],
    }
    classifications = compare_reports(report, copy.deepcopy(report))[
        "layer_classifications"
    ]
    assert classifications == {
        "execution": {"still_failed": 1},
        "deterministic": {"still_failed": 1},
        "semantic": {"pending_review": 1},
    }


def test_summary_does_not_count_partial_or_pending_semantic_as_fully_passed():
    report = {
        "cases": [
            {
                "turns": [
                    {
                        "evaluation": {
                            "status": "pass",
                            "errors": [],
                            "execution": {"status": "partial"},
                            "deterministic": {"status": "pass"},
                            "semantic": {"status": "pass"},
                        }
                    }
                ]
            },
            {
                "turns": [
                    {
                        "evaluation": {
                            "status": "review",
                            "errors": [],
                            "execution": {"status": "completed"},
                            "deterministic": {"status": "pass"},
                            "semantic": {"status": "pending"},
                        }
                    }
                ]
            },
        ]
    }
    result = summary(report)
    assert result["fully_passed_cases"] == 0
    assert result["case_outcomes"] == {"fail": 1, "pending_review": 1}


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


def test_semantic_review_uses_repeat_and_rejects_ambiguous_legacy_locator(tmp_path):
    source = tmp_path / "report.json"
    base_turn = {
        "message": "第四轮",
        "evaluation": {
            "status": "review",
            "errors": [],
            "execution": {"status": "completed"},
            "deterministic": {"status": "pass", "errors": []},
            "semantic": {"status": "pending"},
        },
    }
    source.write_text(
        json.dumps(
            {
                "batch_id": "batch",
                "git_revision": "abc",
                "runtime_version": {},
                "status": "completed",
                "cases": [
                    {
                        "case_id": "case",
                        "title": "重复",
                        "repeat": repeat,
                        "turns": [copy.deepcopy(base_turn)],
                    }
                    for repeat in (1, 2)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review = tmp_path / "review.json"
    review.write_text(
        '{"batch_id":"batch","reviews":'
        '[{"case_id":"case","turn":1,"status":"fail"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="语义审阅定位存在多个 repeat"):
        apply_semantic_review(source, review)
    review.write_text(
        '{"batch_id":"batch","reviews":['
        '{"case_id":"case","repeat":1,"turn":1,"status":"fail","notes":["首次失败"]},'
        '{"case_id":"case","repeat":2,"turn":1,"status":"pass"}]}',
        encoding="utf-8",
    )
    reviewed = apply_semantic_review(source, review)
    payload = json.loads(reviewed.read_text(encoding="utf-8"))
    assert payload["cases"][0]["turns"][0]["evaluation"]["semantic"]["status"] == "fail"
    assert payload["cases"][1]["turns"][0]["evaluation"]["semantic"]["status"] == "pass"


def test_semantic_review_rejects_duplicate_and_missing_locator(tmp_path):
    source = tmp_path / "report.json"
    source.write_text(
        json.dumps(
            {
                "batch_id": "batch",
                "git_revision": "abc",
                "runtime_version": {},
                "status": "completed",
                "cases": [
                    {
                        "case_id": "case",
                        "title": "单次",
                        "repeat": 1,
                        "turns": [
                            {
                                "message": "问题",
                                "evaluation": {
                                    "status": "review",
                                    "errors": [],
                                    "execution": {"status": "completed"},
                                    "deterministic": {"status": "pass"},
                                    "semantic": {"status": "pending"},
                                },
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    review = tmp_path / "review.json"
    duplicate = {
        "batch_id": "batch",
        "reviews": [
            {"case_id": "case", "repeat": 1, "turn": 1, "status": "pass"},
            {"case_id": "case", "repeat": 1, "turn": 1, "status": "fail"},
        ],
    }
    review.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        apply_semantic_review(source, review)
    duplicate["reviews"] = [
        {"case_id": "missing", "repeat": 1, "turn": 1, "status": "pass"}
    ]
    review.write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(ValueError, match="不存在"):
        apply_semantic_review(source, review)


def test_semantic_review_does_not_silently_overwrite_existing_output(tmp_path):
    report = {
        "batch_id": "batch",
        "git_revision": "abc",
        "runtime_version": {},
        "status": "completed",
        "cases": [
            {
                "case_id": "case",
                "title": "单次",
                "repeat": 1,
                "turns": [
                    {
                        "message": "问题",
                        "evaluation": {
                            "status": "review",
                            "errors": [],
                            "execution": {"status": "completed"},
                            "deterministic": {"status": "pass"},
                            "semantic": {"status": "pending"},
                        },
                    }
                ],
            }
        ],
    }
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    review = tmp_path / "review.json"
    review.write_text(
        '{"batch_id":"batch","reviews":['
        '{"case_id":"case","turn":1,"status":"pass"}]}',
        encoding="utf-8",
    )
    first = apply_semantic_review(source, review)
    first_content = first.read_text(encoding="utf-8")
    second = apply_semantic_review(source, review)
    assert second != first
    assert first.read_text(encoding="utf-8") == first_content


def test_summary_lists_run_question_deterministic_and_semantic_gaps():
    report = {
        "batch_id": "batch",
        "git_revision": "abc",
        "runtime_version": {},
        "status": "completed",
        "limits": {"planned_user_messages": 2},
        "cases": [
            {
                "case_id": "case",
                "title": "场景",
                "repeat": 1,
                "turns": [
                    {
                        "message": "这一轮的问题",
                        "run": {"id": 88},
                        "evaluation": {
                            "status": "fail",
                            "errors": ["确定性缺口"],
                            "execution": {"status": "completed"},
                            "deterministic": {"status": "fail", "errors": ["确定性缺口"]},
                            "semantic": {
                                "status": "fail",
                                "notes": ["语义理由"],
                                "reviewed_by": "codex",
                            },
                        },
                    },
                    {
                        "message": "继续",
                        "evaluation": {
                            "status": "not_covered",
                            "errors": ["条件未触发"],
                            "execution": {"status": "not_executed"},
                            "deterministic": {"status": "not_covered"},
                            "semantic": {"status": "not_covered"},
                        },
                    },
                ],
            }
        ],
    }
    text = summary_markdown(report)
    assert "计划轮次：2；实际发送：1；条件未触发：1" in text
    assert "Run 88" in text and "这一轮的问题" in text
    assert "确定性缺口" in text and "语义理由" in text
    assert "审阅者：codex" in text
    assert "Codex 审阅不等于用户最终验收" in text


def test_regrade_preserves_conditional_turn_without_run(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "batch_id": "old",
                "source_batch_id": "root",
                "semantic_review": {"reviewed_turns": 1},
                "status": "completed",
                "domain_unchanged": True,
                "git_revision": "abc",
                "runtime_version": {"confidence": "test"},
                "baseline": {"domain_hashes": {}, "projects": [], "entries": []},
                "provider": [],
                "scopes": {"workspace": None},
                "suite": [
                    {
                        "id": "case",
                        "scope": "workspace",
                        "turns": [{"message": "继续", "kind": "continuation"}],
                    }
                ],
                "cases": [
                    {
                        "case_id": "case",
                        "title": "条件续接",
                        "category": "测试",
                        "repeat": 1,
                        "turns": [
                            {
                                "message": "继续",
                                "request": {"message": "继续", "kind": "continuation"},
                                "evaluation": {
                                    "status": "not_covered",
                                    "errors": ["无 continuation"],
                                    "execution": {"status": "not_executed"},
                                    "deterministic": {"status": "not_covered"},
                                    "semantic": {"status": "not_covered"},
                                },
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    directory = regrade_saved_report(source, tmp_path / "regraded")
    payload = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    assert payload["cases"][0]["turns"][0]["evaluation"]["status"] == "not_covered"
    assert payload["source_batch_id"] == "root"
    assert payload["regraded_from_batch_id"] == "old"
    assert "semantic_review" not in payload
