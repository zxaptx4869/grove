"""真实 HTTP 多轮基线：独立只读数据校验、完整诊断与可重复报告。

运行：在 backend 目录执行 .venv/bin/python -m evals.knowledge_agent_multiturn。
密码交互输入或使用 GROVE_EVAL_PASSWORD；仅内存保存认证 Token。
"""

import argparse
import asyncio
import getpass
import hashlib
import json
import os
import re
import sqlite3
import statistics
import time
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from evals.dialogue_loop.credentials import password_for_run
from evals.dialogue_loop.report import sanitize
from evals.knowledge_agent_cases import (
    Case,
    Turn,
    build_cases,
    build_core_baseline_cases,
    build_task_cases,
)

TERMINAL = {"completed", "partial", "failed", "cancelled"}
MAIN_TYPES = {"knowledge", "method", "parameter", "reminder"}
PREFIX = "/api/knowledge-agent"
MAX_USER_MESSAGES = 40
MAX_MODEL_INVOCATIONS = 192
DEFAULT_BATCH_TIMEOUT_SECONDS = 1800
DATA_TOOLS = {"search_knowledge", "query_entries", "read_entries"}
DIAGNOSTIC_FIELDS = (
    "history_message_ids_json",
    "context_meta_json",
    "structured_query_plan_json",
    "composite_answer_plan_json",
    "composite_answer_execution_json",
    "composite_answer_coverage_json",
    "shared_execution_graph_json",
    "shared_execution_state_json",
    "coverage_repair_json",
    "coverage_repair_plan_json",
    "coverage_repair_execution_json",
    "coverage_repair_graph_json",
    "coverage_repair_graph_state_json",
    "dialogue_loop_state_json",
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class Oracle:
    """独立 SQL 只读校验，不调用被测服务的筛选或聚合实现。"""

    def __init__(self, path: Path, username: str):
        self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        identity = self.rows(
            "SELECT u.id AS user_id, m.workspace_id FROM users u "
            "JOIN workspace_members m ON m.user_id=u.id WHERE u.username=? "
            "ORDER BY m.created_at LIMIT 1",
            (username,),
        )
        if not identity:
            raise ValueError("本地数据库中找不到指定账号及其默认 Workspace")
        self.user_id = identity[0]["user_id"]
        self.workspace_id = identity[0]["workspace_id"]

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(row) for row in self.db.execute(sql, params)]

    def snapshot(self) -> dict:
        # 同一个 SQLite 读事务固定核对口径，避免多次 SELECT 读到不同时间点。
        self.db.execute("BEGIN")
        try:
            projects = self.rows(
                "SELECT id,name,status FROM projects WHERE workspace_id=? ORDER BY id",
                (self.workspace_id,),
            )
            entries = self.rows(
                "SELECT e.id,e.project_id,e.main_type,e.updated_at,"
                "COALESCE(e.info_nature,'unspecified') AS info_nature FROM entries e "
                "JOIN projects p ON p.id=e.project_id WHERE p.workspace_id=? ORDER BY e.id",
                (self.workspace_id,),
            )
            hashes = {}
            sources = "SELECT id FROM sources WHERE workspace_id=?"
            project_ids = "SELECT id FROM projects WHERE workspace_id=?"
            entry_ids = f"SELECT id FROM entries WHERE project_id IN ({project_ids})"
            predicates = {
                "projects": "workspace_id=?",
                "entries": f"project_id IN ({project_ids})",
                "nodes": f"project_id IN ({project_ids})",
                "sources": "workspace_id=?",
                "attachments": f"source_id IN ({sources})",
                "extractions": f"source_id IN ({sources})",
                "candidates": f"source_id IN ({sources})",
                "entry_versions": f"entry_id IN ({entry_ids})",
                "entry_source_evidences": f"entry_id IN ({entry_ids})",
            }
            for table, predicate in predicates.items():
                values = self.rows(
                    f"SELECT * FROM {table} WHERE {predicate} ORDER BY id",
                    (self.workspace_id,),
                )
                hashes[table] = {"rows": len(values), "sha256": digest(values)}
            return {"projects": projects, "entries": entries, "domain_hashes": hashes}
        finally:
            self.db.rollback()

    def diagnostics(self, run_id: int, conversation_id: int) -> dict:
        fields = ",".join(DIAGNOSTIC_FIELDS)
        records = self.rows(
            f"SELECT {fields} FROM knowledge_agent_runs "
            "WHERE id=? AND conversation_id=? AND workspace_id=? AND owner_user_id=?",
            (run_id, conversation_id, self.workspace_id, self.user_id),
        )
        if not records:
            raise ValueError("接口 Run 与本地数据库不一致，停止使用该数据库核对")
        data = {
            key.removesuffix("_json"): json.loads(value) if value else None
            for key, value in records[0].items()
        }
        messages = self.rows(
            "SELECT content FROM knowledge_messages "
            "WHERE run_id=? AND conversation_id=? AND role='assistant'",
            (run_id, conversation_id),
        )
        data["assistant_text"] = messages[0]["content"] if messages else ""
        return data

    def baseline_targets(self, project_id: int, limit: int = 2) -> list[dict]:
        """只从当前授权 Workspace 的既有正式记录选可追溯目标。"""
        return self.rows(
            "SELECT e.id,e.title,e.project_id,p.name AS project_name,"
            "LENGTH(e.content) AS content_chars,COUNT(ev.id) AS evidence_count "
            "FROM entries e JOIN projects p ON p.id=e.project_id "
            "JOIN entry_source_evidences ev ON ev.entry_id=e.id "
            "WHERE p.workspace_id=? AND e.project_id=? AND LENGTH(e.content)>=40 "
            "GROUP BY e.id,e.title,e.project_id,p.name "
            "ORDER BY COUNT(ev.id) DESC,LENGTH(e.content) DESC,e.updated_at DESC,e.id DESC "
            "LIMIT ?",
            (self.workspace_id, project_id, limit),
        )

    def provider(self) -> list[dict]:
        return self.rows(
            "SELECT text_provider,text_model,text_available,embedding_provider,embedding_model,"
            "embedding_available FROM ai_provider_settings WHERE workspace_id=?",
            (self.workspace_id,),
        )


def expected_rows(snapshot: dict, project_id: int | None, turn: Turn) -> list[dict]:
    return [
        row
        for row in snapshot["entries"]
        if (project_id is None or row["project_id"] == project_id)
        and (not turn.main_types or row["main_type"] in turn.main_types)
    ]


def collect_facts(run: dict, diagnostic: dict, observability: dict | None = None) -> list[dict]:
    """分开收集公开交付与内部工具事实，避免以工具成功代替回答完成。"""
    facts = []
    snapshot = run.get("entry_result") or {}
    entry_set = snapshot.get("set_summary") or {}
    if snapshot.get("count") is not None:
        facts.append(
            {
                "kind": "count",
                **snapshot["count"],
                "entry_set": entry_set,
                "delivery": "public_structured",
            }
        )
    for group in snapshot.get("group_counts", []):
        facts.append(
            {
                "kind": "group",
                **group,
                "entry_set": entry_set,
                "delivery": "public_structured",
            }
        )
    for block in run.get("dialogue_blocks") or []:
        if block.get("kind") != "statistic" or block.get("result_type") != "statistic":
            continue
        semantics = block.get("semantics") or {}
        if semantics.get("subject") != "entries":
            continue
        block_set = {"main_types": semantics.get("main_types") or []}
        if semantics.get("project_id") is not None:
            block_set["project_id"] = semantics["project_id"]
        common = {
            "completeness": block.get("completeness") or semantics.get("completeness"),
            "entry_set": block_set,
            "delivery": "public_structured",
        }
        if block.get("group_by"):
            facts.append(
                {
                    "kind": "group",
                    "group_by": block["group_by"],
                    "buckets": block.get("buckets") or [],
                    **common,
                }
            )
        elif isinstance(block.get("value"), int):
            facts.append({"kind": "count", "value": block["value"], **common})
    plan = diagnostic.get("composite_answer_plan") or {}
    sets = {
        item["id"]: item["query_plan"]["entry_set"] for item in plan.get("structured_requests", [])
    }
    answer = run.get("answer") or {}
    text = "\n".join(
        [answer.get("answer", ""), *[point.get("text", "") for point in answer.get("points", [])]]
    )
    for name in ("composite_answer_execution", "coverage_repair_execution"):
        for fact in (diagnostic.get(name) or {}).get("tool_facts", []):
            if fact.get("text") and fact["text"] in text:
                facts.append(
                    {
                        "kind": "group" if fact["kind"] == "group_count" else fact["kind"],
                        **fact.get("summary", {}),
                        "completeness": fact["completeness"],
                        "entry_set": (
                            {**sets[fact["request_id"]], **fact.get("summary", {}).get("scope", {})}
                            if fact["request_id"] in sets
                            else None
                        ),
                        "delivery": "public_structured",
                    }
                )
    for call in (observability or {}).get("tool_calls", []):
        if call.get("tool_name") != "aggregate_entries" or call.get("status") != "completed":
            continue
        params = _json_object(call.get("params_summary")).get("params") or {}
        result = _json_object(call.get("result_summary"))
        operation = result.get("operation") or params.get("operation")
        entry_set = {**(params.get("entry_set") or {})}
        scope = result.get("scope") or {}
        if "project_id" in scope:
            entry_set["project_id"] = scope["project_id"]
        if operation == "count" and isinstance(result.get("value"), int):
            facts.append(
                {
                    "kind": "count",
                    "value": result["value"],
                    "completeness": result.get("completeness"),
                    "entry_set": entry_set,
                    "delivery": "internal_tool",
                }
            )
        elif operation == "group_count":
            facts.append(
                {
                    "kind": "group",
                    "group_by": result.get("group_by"),
                    "buckets": result.get("buckets") or [],
                    "completeness": result.get("completeness"),
                    "entry_set": entry_set,
                    "delivery": "internal_tool",
                }
            )
    public_counts = [
        fact
        for fact in facts
        if fact["kind"] == "count" and fact.get("delivery") == "public_structured"
    ]
    internal_counts = [
        fact
        for fact in facts
        if fact["kind"] == "count" and fact.get("delivery") == "internal_tool"
    ]
    answer_text = ((run.get("answer") or {}).get("answer") or "").strip()
    match = re.fullmatch(r"(?:总数\s*[:：]\s*|(?:共|合计)\s*)(\d+)\s*(?:条)?[.。]?", answer_text)
    if not public_counts and len(internal_counts) == 1 and match:
        fact = internal_counts[0]
        facts.append(
            {
                **fact,
                "value": int(match.group(1)),
                "delivery": "public_text_exact",
            }
        )
    return facts


def matches_set(entry_set: dict | None, turn: Turn) -> bool:
    if entry_set is None or entry_set.get("semantic_query") or entry_set.get("info_natures"):
        return False
    types = set(entry_set.get("main_types") or MAIN_TYPES)
    expected = set(turn.main_types or MAIN_TYPES)
    dates = entry_set.get("updated_at") or {}
    return types == expected and not any(
        [
            dates.get("from"),
            dates.get("to"),
            entry_set.get("updated_at_from"),
            entry_set.get("updated_at_to"),
        ]
    )


def matches_scope(run: dict, entry_set: dict | None, project_id: int | None) -> bool:
    """数值相同不能证明项目筛选生效，必须核对实际集合范围。"""
    actual = (entry_set or {}).get("project_id", run.get("project_id"))
    return actual == project_id and run.get("project_id") in {None, project_id}


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def displayed_entry_ids(run: dict) -> list[int]:
    """优先使用公开结构化结果，不从助手文本猜测对象。"""
    result = run.get("entry_result") or {}
    ids = [item.get("entry_id") for item in result.get("items", [])]
    if ids:
        return [item for item in ids if isinstance(item, int)]
    for block in run.get("dialogue_blocks") or []:
        if block.get("kind") != "list":
            continue
        ids.extend(item.get("entry_id") for item in block.get("items", []))
    return [item for item in ids if isinstance(item, int)]


def _tool_params(observability: dict, tool_name: str) -> list[dict]:
    return [
        _json_object(item.get("params_summary"))
        for item in observability.get("tool_calls", [])
        if item.get("tool_name") == tool_name
    ]


def evaluate_turn(
    turn: Turn,
    run: dict,
    diagnostic: dict,
    observability: dict,
    snapshot: dict,
    project_id: int | None,
    previous: dict | None = None,
) -> dict:
    errors = []
    review_reasons = []
    answer = run.get("answer") or {}
    clarification = (
        run.get("context_decision") == "clarify" or answer.get("status") == "clarification"
    )
    invocations = observability.get("model_invocations", [])
    live = [
        item
        for item in invocations
        if item.get("model")
        and item.get("provider") not in {"offline", "demo", "server"}
        and not item.get("is_fallback")
    ]
    if not live:
        errors.append("未证明本轮真实模型调用成功")
    fallback_stages = (run.get("fallback_summary") or {}).get("stages", [])
    if any(item.get("is_fallback") for item in invocations) or any(
        item.get("is_fallback") and not str(item.get("purpose", "")).startswith("tool:")
        for item in fallback_stages
    ):
        errors.append("存在显式降级，不能计作正常链路通过")
    if run["status"] not in turn.accepted_statuses:
        errors.append(f"Run 终态为 {run['status']}")
    if run["status"] == "partial" and not run.get("can_continue"):
        errors.append("部分完成但没有可用 continuation")
    if clarification != (turn.kind == "clarify"):
        errors.append("不必要澄清" if clarification else "缺少必要澄清")
    if turn.context_mode == "new_topic" and run.get("context_decision") != "new_topic":
        errors.append("未尊重显式新话题")
    snapshot_result = run.get("entry_result") or {}
    items = snapshot_result.get("items", [])
    citations = answer.get("citations", []) + [
        citation for point in answer.get("points", []) for citation in point.get("citations", [])
    ]
    allowed = {
        row["id"]
        for row in snapshot["entries"]
        if project_id is None or row["project_id"] == project_id
    }
    if any(item["entry_id"] not in allowed for item in [*items, *citations]):
        errors.append("返回对象超出预期 Workspace/项目范围")

    tool_names = [item.get("tool_name") for item in observability.get("tool_calls", [])]
    for required in turn.required_tools:
        if turn.kind == "search" and required in {"search_knowledge", "query_entries"}:
            # 两个名称是历史与正式适配层的同一读取能力，下方统一计数。
            continue
        count = tool_names.count(required)
        if count != 1:
            errors.append(f"工具 {required} 预期调用 1 次，实际 {count} 次")
    signatures = [
        (
            item.get("tool_name"),
            _json_object(item.get("params_summary")).get("fingerprint")
            or item.get("params_summary"),
        )
        for item in observability.get("tool_calls", [])
    ]
    repeated = sorted(
        {
            name
            for name, fingerprint in signatures
            if name and signatures.count((name, fingerprint)) > 1
        }
    )
    if repeated:
        errors.append(f"存在重复工具调用：{','.join(repeated)}")
    forbidden = sorted(set(tool_names) & set(turn.forbidden_tools))
    if forbidden:
        errors.append(f"调用了禁止的资料工具：{','.join(forbidden)}")
    rows = expected_rows(snapshot, project_id, turn)
    expected: object = None
    actual: object = None
    facts = collect_facts(run, diagnostic, observability)
    eligible = [
        fact
        for fact in facts
        if fact["kind"] == turn.kind
        and fact.get("completeness") == "complete"
        and matches_set(fact.get("entry_set"), turn)
        and matches_scope(run, fact.get("entry_set"), project_id)
    ]
    public = [
        fact
        for fact in facts
        if fact.get("delivery", "public_structured").startswith("public")
    ]
    eligible_public = [fact for fact in eligible if fact in public]
    if turn.kind in {"count", "group"} and any(fact["kind"] == turn.kind for fact in facts):
        if not any(
            fact["kind"] == turn.kind
            and matches_scope(
                run,
                fact.get("entry_set"),
                project_id,
            )
            for fact in facts
        ):
            errors.append("统计数字未绑定到预期项目范围，不能凭数值巧合判通过")
    if turn.kind == "count":
        expected = len(rows)
        actual = [fact.get("value") for fact in public if fact["kind"] == "count"]
        matching_internal = any(fact.get("value") == expected for fact in eligible)
        matching_public = any(fact.get("value") == expected for fact in eligible_public)
        public_counts = [fact for fact in public if fact["kind"] == "count"]
        if public_counts and not matching_public:
            errors.append("公开结构化统计与独立快照不一致")
        elif matching_internal and not matching_public:
            review_reasons.append("内部统计正确，但未确认公开回答已交付该结果")
        elif not matching_public:
            errors.append("缺少口径匹配且完整的精确总数")
    elif turn.kind == "group":
        key = "project_id" if turn.group_by == "project" else turn.group_by
        expected = dict(Counter(str(row[key]) for row in rows))
        if turn.group_by == "project":
            expected = {
                str(p["id"]): expected.get(str(p["id"]), 0)
                for p in snapshot["projects"]
                if project_id is None or p["id"] == project_id
            }
        actual = [fact for fact in public if fact["kind"] == "group"]
        matching_public = any(
            fact.get("group_by") == turn.group_by
            and {str(bucket["key"]): bucket["count"] for bucket in fact.get("buckets", [])}
            == expected
            for fact in eligible_public
        )
        matching_internal = any(
            fact.get("group_by") == turn.group_by
            and {str(bucket["key"]): bucket["count"] for bucket in fact.get("buckets", [])}
            == expected
            for fact in eligible
        )
        public_groups = [fact for fact in public if fact["kind"] == "group"]
        if public_groups and not matching_public:
            errors.append("公开结构化分组统计与独立快照不一致")
        elif matching_internal and not matching_public:
            review_reasons.append("内部分组统计正确，但未确认公开回答已交付该结果")
        elif not matching_public:
            errors.append("缺少口径匹配且完整的分组统计")
    elif turn.kind == "list":
        expected = [
            row["id"]
            for row in sorted(
                rows,
                key=lambda row: (row["updated_at"], row["id"]),
                reverse=True,
            )[:5]
        ]
        actual = [item["entry_id"] for item in items]
        if (
            actual != expected
            or not matches_set(snapshot_result.get("set_summary"), turn)
            or not matches_scope(run, snapshot_result.get("set_summary"), project_id)
        ):
            errors.append("最近五条对象或筛选口径不匹配")
    elif turn.kind == "reference":
        previous_items = ((previous or {}).get("run", {}).get("entry_result") or {}).get(
            "items", []
        )
        if len(previous_items) < 2:
            return {
                "status": "blocked",
                "errors": ["上一轮未返回至少两个对象"],
                "expected": None,
                "actual": None,
                "clarification": clarification,
            }
        expected = previous_items[1]["entry_id"]
        actual = sorted({item["entry_id"] for item in citations})
        if expected not in actual:
            errors.append("没有以本轮有效引用支撑上一轮第二个对象")
    elif turn.kind == "discussion":
        if not answer.get("answer", "").strip():
            errors.append("没有可见回答正文")
        if citations or any(
            item["tool_name"] != "working_set_seed" for item in observability.get("tool_calls", [])
        ):
            errors.append("违反用户明确的不查知识库要求")
    elif turn.kind == "projects":
        expected = len(snapshot["projects"])
        project_calls = [
            _json_object(item.get("result_summary"))
            for item in observability.get("tool_calls", [])
            if item.get("tool_name") == "list_projects"
        ]
        internal_counts = [item.get("project_count") for item in project_calls]
        expected_ids = {item["id"] for item in snapshot["projects"]}
        project_blocks = [
            block
            for block in run.get("dialogue_blocks") or []
            if block.get("kind") == "list"
            and block.get("result_type") == "projects"
            and (block.get("semantics") or {}).get("subject") == "projects"
        ]
        public_sets = [
            {item.get("id") for item in block.get("items", [])}
            for block in project_blocks
            if block.get("completeness") == "complete"
            and (block.get("semantics") or {}).get("completeness") == "complete"
        ]
        actual = [sorted(ids) for ids in public_sets]
        if public_sets and expected_ids not in public_sets:
            errors.append("公开项目枚举与独立快照不一致")
        elif expected_ids in public_sets:
            pass
        elif expected in internal_counts:
            review_reasons.append("内部项目数正确，但未确认公开回答已交付项目枚举")
        else:
            errors.append("项目枚举数量与只读快照不一致")
    elif turn.kind == "search":
        search_count = sum(tool_names.count(name) for name in ("search_knowledge", "query_entries"))
        if search_count != 1:
            errors.append(f"检索工具预期调用 1 次，实际 {search_count} 次")
        actual = displayed_entry_ids(run)
        expected = turn.target_entry_id
        if not actual:
            errors.append("没有结构化展示经筛选的 Entry")
        if expected is not None and expected not in actual:
            errors.append("运行前固定的目标 Entry 未出现在展示结果中")
        if any(
            (block.get("semantics") or {}).get("result_role") == "candidate"
            for block in run.get("dialogue_blocks") or []
            if block.get("kind") == "list"
        ):
            errors.append("未筛选候选被当作可展示列表")
    elif turn.kind == "read_reference":
        previous_ids = displayed_entry_ids((previous or {}).get("run", {}))
        if not previous_ids:
            errors.append("上轮没有可供“第一条”引用的结构化对象")
        else:
            expected = previous_ids[0]
            params = _tool_params(observability, "read_entries")
            requested_ids = {
                entry_id
                for item in params
                for entry_id in (item.get("params") or item).get("entry_ids", [])
            }
            actual = sorted(requested_ids)
            if expected not in requested_ids:
                errors.append("首次 read_entries 未读取上轮实际展示的第一条")
            read_calls = [
                _json_object(item.get("result_summary"))
                for item in observability.get("tool_calls", [])
                if item.get("tool_name") == "read_entries"
            ]
            if any(
                item.get("denied_count", 0) or item.get("unavailable_count", 0)
                for item in read_calls
            ):
                errors.append("跨轮读取出现拒绝或失效 Entry")
    elif turn.kind in {"anchored_discussion", "candidate", "tone_revision", "continuation"}:
        if not (diagnostic.get("assistant_text") or "").strip():
            errors.append("没有可见回答正文")
        if turn.kind == "continuation":
            dialogue_calls = [
                item for item in invocations if item.get("purpose") == "dialogue_agent"
            ]
            if len(dialogue_calls) != 1:
                errors.append(f"续接预期一次 finalizer，实际模型调用 {len(dialogue_calls)} 次")
            previous_text = ((previous or {}).get("diagnostic") or {}).get("assistant_text", "")
            current_text = diagnostic.get("assistant_text", "")
            if previous_text.strip() and previous_text.strip() == current_text.strip():
                errors.append("续接只重放上一轮回答，没有实际进展")
    status = "fail" if errors else "review" if turn.review or review_reasons else "pass"
    deterministic_status = "fail" if errors else "review" if review_reasons else "pass"
    return {
        "status": status,
        "errors": errors,
        "review_reasons": review_reasons,
        "expected": expected,
        "actual": actual,
        "clarification": clarification,
        "real_model_calls": len(live),
        "execution": {
            "status": run.get("status", "not_executed"),
            "error": run.get("error"),
        },
        "deterministic": {
            "status": deterministic_status,
            "errors": errors,
            "review_reasons": review_reasons,
        },
        "semantic": {
            "status": "pending" if turn.review or review_reasons else "not_applicable",
            "criteria": list(turn.semantic_criteria),
        },
    }


async def request(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


async def wait_run(client: httpx.AsyncClient, run_id: int, seconds: float) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        run = await request(client, "GET", f"{PREFIX}/runs/{run_id}")
        if run["status"] in TERMINAL:
            return run
        await asyncio.sleep(1)
    await request(client, "POST", f"{PREFIX}/runs/{run_id}/cancel")
    # 不在尚有评测 Run 运行时提交同会话下一轮。
    for _ in range(30):
        run = await request(client, "GET", f"{PREFIX}/runs/{run_id}")
        if run["status"] in TERMINAL:
            return run
        await asyncio.sleep(1)
    raise TimeoutError(f"Run {run_id} 超时且尚未确认取消，停止后续评测")


def summary(report: dict) -> dict:
    turns = [turn for case in report["cases"] for turn in case["turns"]]
    counts = Counter(turn["evaluation"]["status"] for turn in turns)
    elapsed = [turn["elapsed_seconds"] for turn in turns if "elapsed_seconds" in turn]
    invocations = [
        item
        for turn in turns
        for item in turn.get("observability", {}).get("model_invocations", [])
    ]
    dispatched_invocations = [
        item for item in invocations if item.get("outcome") != "not_dispatched"
    ]
    execution_counts = Counter(
        turn.get("evaluation", {}).get("execution", {}).get("status", "not_executed")
        for turn in turns
    )
    deterministic_counts = Counter(
        turn.get("evaluation", {}).get("deterministic", {}).get("status", "unknown")
        for turn in turns
    )
    semantic_counts = Counter(
        turn.get("evaluation", {}).get("semantic", {}).get("status", "unknown") for turn in turns
    )
    case_outcomes = Counter(_case_outcome(case) for case in report["cases"])
    conditional_not_triggered = sum(
        turn.get("evaluation", {}).get("status") == "not_covered"
        and not turn.get("run", {}).get("id")
        for turn in turns
    )
    token_keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    known_usage = {key: 0 for key in token_keys}
    usage_missing = 0
    for item in dispatched_invocations:
        usage = item.get("usage")
        if not isinstance(usage, dict):
            usage_missing += 1
            continue
        for key in token_keys:
            value = usage.get(key)
            if isinstance(value, int):
                known_usage[key] += value
    return {
        "cases": len(report["cases"]),
        "turns": len(turns),
        "statuses": dict(counts),
        "execution_statuses": dict(execution_counts),
        "deterministic_statuses": dict(deterministic_counts),
        "semantic_statuses": dict(semantic_counts),
        "case_outcomes": dict(case_outcomes),
        "conditional_not_triggered": conditional_not_triggered,
        "fully_passed_cases": sum(
            bool(case["turns"]) and _case_passed(case) for case in report["cases"]
        ),
        "unnecessary_clarifications": sum(
            "不必要澄清" in turn["evaluation"]["errors"] for turn in turns
        ),
        "model_audit_records": len(invocations),
        "dispatched_model_invocations": len(dispatched_invocations),
        # 保留旧键，但明确它代表审计记录数，不是硬派发计数。
        "model_invocations": len(invocations),
        "fallback_invocations": sum(bool(item.get("is_fallback")) for item in invocations),
        "invocations_with_usage": sum(bool(item.get("usage")) for item in dispatched_invocations),
        "models": sorted(
            {f"{item['provider']}/{item['model']}" for item in invocations if item.get("model")}
        ),
        "known_model_usage": known_usage,
        "invocations_without_usage": usage_missing,
        "median_seconds": round(statistics.median(elapsed), 2) if elapsed else None,
        "max_seconds": round(max(elapsed), 2) if elapsed else None,
    }


def _case_passed(case: dict) -> bool:
    return _case_outcome(case) == "pass"


def _case_outcome(case: dict) -> str:
    if not case["turns"]:
        return "not_covered"
    states = [turn.get("evaluation") or {} for turn in case["turns"]]
    if any(
        (item.get("execution") or {}).get("status")
        in {"partial", "failed", "cancelled"}
        or (item.get("deterministic") or {}).get("status") in {"fail", "blocked"}
        or (item.get("semantic") or {}).get("status") == "fail"
        for item in states
    ):
        return "fail"
    if any(
        (item.get("execution") or {}).get("status") == "not_executed"
        or (item.get("deterministic") or {}).get("status") == "not_covered"
        or (item.get("semantic") or {}).get("status") == "not_covered"
        for item in states
    ):
        return "not_covered"
    if any(
        (item.get("execution") or {}).get("status") != "completed"
        or (item.get("deterministic") or {}).get("status") != "pass"
        or (item.get("semantic") or {}).get("status")
        not in {"pass", "not_applicable"}
        for item in states
    ):
        return "pending_review"
    return "pass"


def summary_markdown(report: dict) -> str:
    """面向 Codex 和人工审阅的短摘要；详细证据留在 report.json。"""
    stats = summary(report)
    sent_turns = sum(
        bool(turn.get("run", {}).get("id"))
        for case in report["cases"]
        for turn in case["turns"]
    )
    reviewers = sorted(
        {
            reviewer
            for case in report["cases"]
            for turn in case["turns"]
            if (reviewer := (turn.get("evaluation", {}).get("semantic") or {}).get("reviewed_by"))
        }
    )
    lines = [
        "# 知识 Agent 评测摘要",
        "",
        f"- 批次：{report['batch_id']}",
        f"- 代码 commit：`{report['git_revision']}`",
        f"- 运行版本：{report.get('runtime_version', {}).get('confidence', '未确认')}",
        f"- 批次状态：{report['status']}",
        f"- 场景 / 记录轮次：{stats['cases']} / {stats['turns']}",
        f"- 计划轮次：{report.get('limits', {}).get('planned_user_messages', stats['turns'])}；"
        f"实际发送：{sent_turns}；"
        f"条件未触发：{stats['conditional_not_triggered']}",
        f"- 执行层：{stats['execution_statuses']}",
        f"- 确定性层：{stats['deterministic_statuses']}",
        f"- 语义层：{stats['semantic_statuses']}",
        f"- 整段结论：{stats['case_outcomes']}",
        f"- 语义审阅者：{'、'.join(reviewers) if reviewers else '尚未语义审阅'}",
        f"- 模型审计记录：{stats['model_audit_records']}；"
        f"已派发：{stats['dispatched_model_invocations']}；"
        f"无 usage 记录：{stats['invocations_without_usage']}",
        f"- 已知 usage：{stats['known_model_usage']}",
        "",
        "## 逐场景",
        "",
    ]
    for case in report["cases"]:
        turns = case["turns"]
        execution = Counter(
            item.get("evaluation", {}).get("execution", {}).get("status", "not_executed")
            for item in turns
        )
        deterministic = Counter(
            item.get("evaluation", {}).get("deterministic", {}).get("status", "unknown")
            for item in turns
        )
        semantic = Counter(
            item.get("evaluation", {}).get("semantic", {}).get("status", "unknown")
            for item in turns
        )
        lines.extend(
            [
                f"### {case['case_id']}：{case['title']}",
                "",
                f"- 执行：{dict(execution)}",
                f"- 确定性：{dict(deterministic)}",
                f"- 语义：{dict(semantic)}",
                f"- 整段结论：{_case_outcome(case)}",
                "",
            ]
        )
        for index, item in enumerate(turns, 1):
            evaluation = item.get("evaluation") or {}
            deterministic = evaluation.get("deterministic") or {}
            semantic_result = evaluation.get("semantic") or {}
            if deterministic.get("status") == "pass" and semantic_result.get("status") in {
                "pass",
                "not_applicable",
            }:
                continue
            run_id = (item.get("run") or {}).get("id")
            question = " ".join(str(item.get("message") or "未记录问题").split())[:80]
            deterministic_notes = (
                deterministic.get("errors")
                or deterministic.get("review_reasons")
                or evaluation.get("errors")
                or [deterministic.get("status", "unknown")]
            )
            semantic_notes = semantic_result.get("notes") or [
                semantic_result.get("status", "unknown")
            ]
            reviewer = semantic_result.get("reviewed_by", "未审阅")
            lines.extend(
                [
                    f"- Run {run_id if run_id is not None else '未发送'} / 第 {index} 轮 / "
                    f"问题：{question}；确定性：{'；'.join(deterministic_notes)}；"
                    f"语义：{'；'.join(semantic_notes)}；审阅者：{reviewer}"
                ]
            )
        lines.append("")
    if report.get("comparison"):
        lines.extend(
            [
                "## 相对基线",
                "",
                json.dumps(report["comparison"], ensure_ascii=False, indent=2),
                "",
            ]
        )
    lines.extend(
        [
            "详细的问题、回答、工具审计、模型调用、continuation 和预算见 `report.json`。",
            "语义状态为 pending 时不计作场景通过。",
            "Codex 审阅不等于用户最终验收。",
        ]
    )
    return "\n".join(lines)


def markdown_report(report: dict) -> str:
    stats = summary(report)
    lines = [
        "# 知识 Agent 真实多轮评测",
        "",
        f"- 批次：{report['batch_id']}",
        f"- 代码：`{report['git_revision']}`",
        f"- 状态：{report['status']}",
        f"- 场景 / 轮数：{stats['cases']} / {stats['turns']}",
        f"- 自动结果：{stats['statuses']}；整段自动通过 {stats['fully_passed_cases']} 段",
        f"- 不必要澄清：{stats['unnecessary_clarifications']} 次",
        f"- 模型审计记录 / 已派发：{stats['model_audit_records']} / "
        f"{stats['dispatched_model_invocations']}；降级 {stats['fallback_invocations']}",
        f"- 模型：{', '.join(stats['models'])}",
        f"- 单轮耗时中位数 / 最大值：{stats['median_seconds']} / {stats['max_seconds']} 秒",
        "",
        "通过仅表示列出的确定性检查通过；表达、理解与解释质量仍需人工复核。",
        "usage 缺失的调用不能估算费用。数据库发生变化时，本批不能作为稳定基线。",
        "",
    ]
    if report.get("error"):
        lines.extend([f"运行错误：{report['error']}", ""])
    for case in report["cases"]:
        lines.extend(
            [
                f"## {case['case_id']} / 第 {case['repeat']} 次：{case['title']}",
                "",
                f"Conversation：{case.get('conversation_id')}；类别：{case['category']}",
                "",
            ]
        )
        for index, turn in enumerate(case["turns"], 1):
            result = turn["evaluation"]
            run = turn.get("run", {})
            lines.extend(
                [
                    f"### 第 {index} 轮：{result['status']}",
                    "",
                    f"用户：{turn['message']}",
                    "",
                    f"助手：{turn.get('diagnostic', {}).get('assistant_text', '未发送')}",
                    "",
                    f"Run：{run.get('id')}；上下文：{run.get('context_decision')}；"
                    f"耗时：{turn.get('elapsed_seconds')} 秒",
                    f"独立问题：{run.get('standalone_query')}",
                    f"检查：{'；'.join(result['errors']) or '确定性检查通过'}",
                    "",
                ]
            )
            if result.get("expected") is not None:
                lines.extend(
                    [
                        "```json",
                        json.dumps(
                            {"expected": result["expected"], "actual": result["actual"]},
                            ensure_ascii=False,
                            indent=2,
                        ),
                        "```",
                        "",
                    ]
                )
    if report.get("comparison"):
        lines.extend(
            [
                "## 基线比较",
                "",
                "```json",
                json.dumps(report["comparison"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def save_report(report: dict, directory: Path) -> None:
    report["summary"] = summary(report)
    safe_report = sanitize(report)
    for name, value in (
        ("report.json", json.dumps(safe_report, ensure_ascii=False, indent=2)),
        ("report.md", markdown_report(safe_report)),
        ("summary.md", summary_markdown(safe_report)),
    ):
        temporary = directory / f"{name}.tmp"
        temporary.write_text(value, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(directory / name)


def compare_reports(old: dict, new: dict) -> dict:
    def keyed(report):
        return {
            (case["case_id"], case["repeat"], index): turn
            for case in report["cases"]
            for index, turn in enumerate(case["turns"])
        }

    before, after = keyed(old), keyed(new)
    common = before.keys() & after.keys()

    def layer_status(turn: dict, layer: str) -> str:
        value = (turn.get("evaluation") or {}).get(layer)
        return value.get("status", "unknown") if isinstance(value, dict) else "unknown"

    def classify(layer: str, previous: str, current: str) -> str:
        if "unknown" in {previous, current}:
            return "unknown"
        failed = {
            "execution": {"partial", "failed", "cancelled"},
            "deterministic": {"fail", "blocked"},
            "semantic": {"fail"},
        }[layer]
        passed = {"completed"} if layer == "execution" else {"pass"}
        if previous == current:
            if current in failed:
                return "still_failed"
            if current in {"pending", "review"}:
                return "pending_review"
            if current in {"not_covered", "not_executed"}:
                return "not_covered"
            if current in passed or current == "not_applicable":
                return "unchanged_pass"
            return "unchanged"
        if current in passed:
            return "improved"
        if previous in passed or current in failed:
            return "regressed"
        if previous in failed and current in {"pending", "review"}:
            return "improved_pending_review"
        if current in {"pending", "review"}:
            return "pending_review"
        if current in {"not_covered", "not_executed"}:
            return "not_covered"
        return "changed"

    changes = []
    layer_counts = {}
    for layer in ("execution", "deterministic", "semantic"):
        counts = Counter()
        for key in sorted(common):
            previous = layer_status(before[key], layer)
            current = layer_status(after[key], layer)
            classification = classify(layer, previous, current)
            counts[classification] += 1
            if previous != current:
                changes.append(
                    {
                        "case": key[0],
                        "repeat": key[1],
                        "turn": key[2] + 1,
                        "layer": layer,
                        "before": previous,
                        "after": current,
                        "classification": classification,
                    }
                )
        layer_counts[layer] = dict(counts)
    comparable = (
        old["baseline"]["domain_hashes"] == new["baseline"]["domain_hashes"]
        and old["provider"] == new["provider"]
        and old.get("suite_digest") == new.get("suite_digest")
        and old.get("grader_sha256", old.get("runner_sha256"))
        == new.get(
            "grader_sha256",
            new.get("runner_sha256"),
        )
        and old.get("domain_unchanged") is True
        and new.get("domain_unchanged") is True
    )
    return {
        "comparable_data_model_suite": comparable,
        "matched_turns": len(common),
        "note": "运行中配置未由服务端完整公开；即使可比，也需核对特性开关。",
        "layer_classifications": layer_counts,
        "changes": changes,
    }


def scope_payload(project_id: int | None) -> dict:
    return {
        "scope_type": "workspace" if project_id is None else "project",
        "project_id": project_id,
    }


def blocked_reason(turn: Turn, previous: dict | None) -> str | None:
    previous = previous or {}
    if turn.only_if_continuation and not (
        previous.get("run", {}).get("can_continue") and previous.get("run", {}).get("continuation")
    ):
        return "上轮未产生合法 continuation，本轮按预定标准记为未覆盖"
    items = (previous.get("run", {}).get("entry_result") or {}).get("items", [])
    if turn.kind == "reference" and turn.reference_previous and len(items) < 2:
        return "上一轮没有返回两个对象，未发送无锚点指代"
    if (
        turn.kind == "read_reference"
        and turn.reference_previous
        and not displayed_entry_ids(previous.get("run", {}))
    ):
        return "上一轮没有展示 Entry，未发送无锚点读取"
    if turn.requires_previous_answer and previous.get("evaluation", {}).get("status") not in {
        "pass",
        "review",
    }:
        return "上一轮回答未通过前置检查，后续解释追问留待修复后验证"
    return None


async def run_case(
    client,
    oracle,
    snapshot,
    scopes,
    case: Case,
    repeat: int,
    report,
    directory,
    seconds,
    batch_deadline,
):
    scope = case.scope
    conversation = await request(
        client, "POST", f"{PREFIX}/conversations", json=scope_payload(scopes[scope])
    )
    record = {
        "case_id": case.id,
        "title": case.title,
        "category": case.category,
        "repeat": repeat,
        "conversation_id": conversation["id"],
        "turns": [],
    }
    report["cases"].append(record)
    save_report(report, directory)
    for index, turn in enumerate(case.turns, 1):
        previous = record["turns"][-1] if record["turns"] else None
        blocked = blocked_reason(turn, previous)
        if blocked:
            not_covered = turn.only_if_continuation
            record["turns"].append(
                {
                    "message": turn.message,
                    "request": asdict(turn),
                    "evaluation": {
                        "status": "not_covered" if not_covered else "blocked",
                        "errors": [blocked],
                        "execution": {"status": "not_executed", "error": None},
                        "deterministic": {
                            "status": "not_covered" if not_covered else "blocked",
                            "errors": [blocked],
                        },
                        "semantic": {
                            "status": "not_covered" if not_covered else "not_applicable",
                            "criteria": list(turn.semantic_criteria),
                        },
                    },
                }
            )
            save_report(report, directory)
            continue
        remaining = batch_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("整批评测达到预先固定的时间上限")
        sent = sum(
            bool(item.get("run", {}).get("id"))
            for item_case in report["cases"]
            for item in item_case["turns"]
        )
        if sent >= report["limits"]["user_messages"]:
            raise RuntimeError("整批评测达到用户消息上限")
        model_audit_count = sum(
            len(item.get("observability", {}).get("model_invocations", []))
            for item_case in report["cases"]
            for item in item_case["turns"]
        )
        audit_threshold = report["limits"].get(
            "model_audit_stop_threshold",
            report["limits"].get("model_invocations", MAX_MODEL_INVOCATIONS),
        )
        if model_audit_count >= audit_threshold:
            raise RuntimeError("整批评测已达到模型审计记录的轮后停止阈值")
        if turn.change_scope:
            scope = turn.change_scope
            await request(
                client,
                "PATCH",
                f"{PREFIX}/conversations/{conversation['id']}/scope",
                json=scope_payload(scopes[scope]),
            )
        if oracle.snapshot()["domain_hashes"] != snapshot["domain_hashes"]:
            raise ValueError("评测期间 demo 业务数据发生变化，停止沿用旧预期")
        started = time.monotonic()
        print(f"{case.id}[{repeat}] {index}/{len(case.turns)}：提交", flush=True)
        submitted = await request(
            client,
            "POST",
            f"{PREFIX}/conversations/{conversation['id']}/messages",
            json={
                "client_message_id": uuid.uuid4().hex,
                "message": turn.message,
                "context_mode": turn.context_mode,
                "basis_mode": "auto",
                "result_mode": "auto",
                "answer_mode": "auto",
            },
        )
        run_id = submitted["run"]["id"]
        pending = {
            "message": turn.message,
            "request": asdict(turn),
            "run": submitted["run"],
            "evaluation": {"status": "pending", "errors": []},
        }
        record["turns"].append(pending)
        save_report(report, directory)
        try:
            run = await wait_run(client, run_id, min(seconds, remaining))
        except BaseException:
            await request(client, "POST", f"{PREFIX}/runs/{run_id}/cancel")
            raise
        observation = await request(client, "GET", f"{PREFIX}/runs/{run_id}/observability")
        diagnostic = oracle.diagnostics(run_id, conversation["id"])
        evaluation = evaluate_turn(
            turn,
            run,
            diagnostic,
            observation,
            snapshot,
            scopes[turn.oracle_scope or scope],
            previous,
        )
        if run["project_id"] != scopes[scope]:
            evaluation["errors"].append("Run 固化范围与接口选择不一致")
            evaluation["status"] = "fail"
        pending.update(
            run=run,
            diagnostic=diagnostic,
            observability=observation,
            elapsed_seconds=round(time.monotonic() - started, 2),
            evaluation=evaluation,
        )
        save_report(report, directory)
        print(
            f"{case.id}[{repeat}] 第 {index} 轮 Run {run_id}：{evaluation['status']} "
            f"{'；'.join(evaluation['errors'])}",
            flush=True,
        )


async def _git_output(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode:
        raise ValueError(f"无法记录 Git 信息：git {' '.join(args)}")
    return stdout.decode().strip()


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "backend/evals/knowledge_agent_multiturn.py",
        "backend/evals/knowledge_agent_cases.py",
        "backend/app/services/knowledge_agent/production_adapter.py",
        "backend/evals/dialogue_loop/loop.py",
    )
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


async def run_suite(args, password: str) -> int:
    # 比较文件先读取，避免跑完整批后才因临时文件失效丢失收尾报告。
    comparison_source = (
        json.loads(args.compare.read_text(encoding="utf-8")) if args.compare else None
    )
    oracle = Oracle(args.database, args.username)
    baseline = oracle.snapshot()
    counts = Counter(row["project_id"] for row in baseline["entries"])
    projects = baseline["projects"]
    if not counts:
        raise ValueError("账号没有正式记录，无法运行本套统计/列表基线")
    project = max(projects, key=lambda item: counts[item["id"]])
    empty = next((item for item in projects if counts[item["id"]] == 0), None)
    scopes = {"workspace": None, "project": project["id"], "empty": empty["id"] if empty else None}
    cases = build_cases(project["name"], empty["name"] if empty else None)
    if args.suite == "core":
        cases = build_core_baseline_cases(oracle.baseline_targets(project["id"]))
    elif args.suite == "task" or getattr(args, "task_suite", False):
        other = next(
            (p for p in projects if p["id"] != project["id"] and counts[p["id"]] > 0),
            None,
        )
        if other is None:
            raise ValueError("任务对照需要另一个非空项目，以免相同计数掩盖错误")
        scopes["other"] = other["id"]
        cases = build_task_cases(project["name"], other["name"])
    if args.cases:
        selected = set(args.cases.split(","))
        if selected - {case.id for case in cases}:
            raise ValueError("指定场景不存在，或其所需空项目不存在")
        cases = [case for case in cases if case.id in selected]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    directory = args.output / stamp
    directory.mkdir(parents=True, mode=0o700)
    maximum_messages = sum(len(case.turns) for case in cases) * args.repeat
    if maximum_messages > MAX_USER_MESSAGES:
        raise ValueError(
            f"评测计划最多 {maximum_messages} 条用户消息，超过 {MAX_USER_MESSAGES} 条上限"
        )
    revision = await _git_output("rev-parse", "HEAD")
    status = await _git_output("status", "--short")
    report = {
        "schema_version": 2,
        "batch_id": stamp,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "git_revision": revision,
        "git_status": status.splitlines(),
        "source_hashes": _source_hashes(),
        "runtime_version": {
            "confidence": (
                "本机 API 未暴露 commit；已确认认证身份与同一本地数据库，代码哈希供手工核对"
            ),
            "api_commit": None,
        },
        "username": args.username,
        "workspace_id": oracle.workspace_id,
        "baseline": baseline,
        "provider": oracle.provider(),
        "scopes": scopes,
        "cases": [],
        "suite_digest": digest([asdict(case) for case in cases]),
        "suite": [asdict(case) for case in cases],
        "repeat": args.repeat,
        "limits": {
            "user_messages": MAX_USER_MESSAGES,
            "planned_user_messages": maximum_messages,
            "model_audit_stop_threshold": MAX_MODEL_INVOCATIONS,
            "batch_seconds": args.batch_timeout,
            "turn_seconds": args.turn_timeout,
            "agent_per_turn_budgets": "未修改，沿用正式服务当前配置",
        },
        "runner_sha256": hashlib.sha256(
            await asyncio.to_thread(Path(__file__).read_bytes)
        ).hexdigest(),
    }
    authenticated = False
    batch_deadline = time.monotonic() + args.batch_timeout
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, trust_env=False) as client:
        try:
            login = await request(
                client,
                "POST",
                "/api/auth/mobile/login",
                json={"username": args.username, "password": password},
            )
            client.headers["Authorization"] = f"Bearer {login['token']}"
            authenticated = True
            identity = await request(client, "GET", "/api/me")
            if (identity["user"]["id"], identity["workspace"]["id"]) != (
                oracle.user_id,
                oracle.workspace_id,
            ):
                raise ValueError("认证身份与核对数据库不一致")
            print(f"评测输出：{directory}；{len(cases)} 段 x {args.repeat} 次", flush=True)
            save_report(report, directory)
            for repeat in range(1, args.repeat + 1):
                for case in cases:
                    await run_case(
                        client,
                        oracle,
                        baseline,
                        scopes,
                        case,
                        repeat,
                        report,
                        directory,
                        args.turn_timeout,
                        batch_deadline,
                    )
            report["status"] = "completed"
        except Exception as exc:
            # 不记录请求体、认证头或原始响应，避免凭据进入错误报告。
            report["status"] = "error"
            report["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if authenticated:
                try:
                    await request(client, "POST", "/api/auth/mobile/logout")
                except httpx.HTTPError:
                    report["logout_warning"] = "评测会话注销失败"
            report["domain_unchanged"] = (
                oracle.snapshot()["domain_hashes"] == baseline["domain_hashes"]
            )
            if not report["domain_unchanged"] and report["status"] == "completed":
                report["status"] = "invalidated"
            report["finished_at"] = datetime.now(UTC).isoformat()
            save_report(report, directory)
            oracle.db.close()
            if comparison_source is not None:
                report["comparison"] = compare_reports(comparison_source, report)
                save_report(report, directory)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    if report.get("error"):
        print(f"运行错误：{report['error']}", flush=True)
    print(f"报告：{directory / 'report.md'}", flush=True)
    return (
        0
        if (
            report["status"] == "completed"
            and report["domain_unchanged"]
            and not report["summary"]["statuses"].get("fail")
            and not report["summary"]["statuses"].get("blocked")
        )
        else 1
    )


def regrade_saved_report(source: Path, output: Path) -> Path:
    """只重评已有响应；不登录、不请求接口、不重新调用模型。"""
    report = json.loads(source.read_text(encoding="utf-8"))
    if report.get("status") != "completed" or not report.get("domain_unchanged"):
        raise ValueError("只允许重评已完成且数据未变化的批次")
    case_specs = {case["id"]: case for case in report["suite"]}
    for case in report["cases"]:
        scope = case_specs[case["case_id"]]["scope"]
        previous = None
        for turn in case["turns"]:
            if "request" not in turn or "run" not in turn:
                # 条件续接未触发时没有 Run，保留原 not_covered 证据。
                if "run" in turn:
                    previous = turn
                continue
            if not turn.get("observability"):
                previous = turn
                continue
            spec = Turn(**turn["request"])
            scope = spec.change_scope or scope
            turn["evaluation"] = evaluate_turn(
                spec,
                turn["run"],
                turn["diagnostic"],
                turn["observability"],
                report["baseline"],
                report["scopes"][spec.oracle_scope or scope],
                previous,
            )
            if turn["run"]["project_id"] != report["scopes"][scope]:
                turn["evaluation"]["errors"].append("Run 固化范围与接口选择不一致")
                turn["evaluation"]["status"] = "fail"
            previous = turn
    report["source_report"] = str(source.resolve())
    report["regraded_from_batch_id"] = report["batch_id"]
    report["source_batch_id"] = report.get("source_batch_id", report["batch_id"])
    report["regraded_at"] = datetime.now(UTC).isoformat()
    report["grader_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["batch_id"] = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-regraded-" + uuid.uuid4().hex[:6]
    )
    report.pop("comparison", None)
    report.pop("semantic_review", None)
    directory = output / report["batch_id"]
    directory.mkdir(parents=True, mode=0o700)
    save_report(report, directory)
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    print(f"报告：{directory / 'report.md'}", flush=True)
    return directory


def apply_semantic_review(source: Path, review_path: Path) -> Path:
    """将人工语义结论写入新报告，不改写原始运行证据。"""
    report = json.loads(source.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("batch_id") not in {report.get("batch_id"), report.get("source_batch_id")}:
        raise ValueError("语义审阅批次与原始报告不匹配")
    turns = {
        (case["case_id"], case.get("repeat", 1), index): turn
        for case in report["cases"]
        for index, turn in enumerate(case["turns"], 1)
    }
    seen = set()
    for item in review.get("reviews", []):
        if item.get("repeat") is None:
            matches = [
                key
                for key in turns
                if key[0] == item.get("case_id") and key[2] == item.get("turn")
            ]
            if len(matches) > 1:
                raise ValueError(
                    f"语义审阅定位存在多个 repeat："
                    f"{(item.get('case_id'), item.get('turn'))}"
                )
            if not matches:
                raise ValueError(
                    f"语义审阅定位不存在："
                    f"{(item.get('case_id'), item.get('turn'))}"
                )
            key = matches[0]
        else:
            key = (item.get("case_id"), item.get("repeat"), item.get("turn"))
        if key in seen:
            raise ValueError(f"语义审阅定位重复：{key}")
        if key not in turns:
            raise ValueError(f"语义审阅定位不存在：{key}")
        if item.get("status") not in {"pass", "fail", "not_covered"}:
            raise ValueError(f"语义审阅状态无效：{key}")
        semantic = turns[key].setdefault("evaluation", {}).setdefault("semantic", {})
        semantic.update(
            status=item["status"],
            notes=list(item.get("notes") or []),
            reviewed_by=review.get("reviewed_by", "manual"),
        )
        seen.add(key)
    report["semantic_review"] = {
        "source": str(review_path.resolve()),
        "reviewed_at": review.get("reviewed_at") or datetime.now(UTC).isoformat(),
        "reviewed_turns": len(seen),
    }
    report["summary"] = summary(report)
    suffix = ""
    output = source.with_name("reviewed-report.json")
    if output.exists():
        suffix = "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:6]
        output = source.with_name(f"reviewed-report{suffix}.json")
    summary_output = source.with_name(f"reviewed-summary{suffix}.md")
    for path, content in (
        (output, json.dumps(sanitize(report), ensure_ascii=False, indent=2)),
        (summary_output, summary_markdown(sanitize(report))),
    ):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
    return output


async def run_preflight(args, password: str) -> int:
    """只校验本机正式 API、身份、数据库和 Provider 可用性，不创建 Run。"""
    oracle = Oracle(args.database, args.username)
    authenticated = False
    result = {
        "status": "failed",
        "model_requests": 0,
        "base_url": args.base_url,
        "workspace_id": oracle.workspace_id,
        "provider": oracle.provider(),
        "checks": [],
    }
    async with httpx.AsyncClient(base_url=args.base_url, timeout=30, trust_env=False) as client:
        try:
            login = await request(
                client,
                "POST",
                "/api/auth/mobile/login",
                json={"username": args.username, "password": password},
            )
            client.headers["Authorization"] = f"Bearer {login['token']}"
            authenticated = True
            identity = await request(client, "GET", "/api/me")
            if (identity["user"]["id"], identity["workspace"]["id"]) != (
                oracle.user_id,
                oracle.workspace_id,
            ):
                raise ValueError("认证身份与只读核对数据库不一致")
            await request(client, "GET", f"{PREFIX}/conversations")
            result["checks"].extend(
                ["本机 API 可访问", "demo 认证成功", "Workspace 身份一致", "对话列表可读"]
            )
            if not any(item.get("text_available") for item in result["provider"]):
                raise ValueError("当前 Workspace 没有可用文本模型配置")
            result["checks"].append("文本模型配置可用")
            result["status"] = "passed"
        finally:
            if authenticated:
                try:
                    await request(client, "POST", "/api/auth/mobile/logout")
                except httpx.HTTPError:
                    result["logout_warning"] = "评测会话注销失败"
            oracle.db.close()
    print(json.dumps(sanitize(result), ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database", type=Path, default=Path("grove.db"))
    parser.add_argument("--username", default="demo")
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/grove-agent-eval"))
    parser.add_argument("--cases", help="仅运行指定场景，英文逗号分隔")
    parser.add_argument(
        "--suite",
        choices=("legacy", "core", "task"),
        default="legacy",
        help="评测集；core 为轻量正式链路基线",
    )
    parser.add_argument("--task-suite", action="store_true", help="运行固定的任务状态调试与保留集")
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--turn-timeout", type=float, default=240)
    parser.add_argument(
        "--batch-timeout",
        type=float,
        default=DEFAULT_BATCH_TIMEOUT_SECONDS,
        help="整批时间上限（秒）",
    )
    parser.add_argument("--preflight", action="store_true", help="只执行零模型本机链路预检")
    parser.add_argument("--compare", type=Path, help="上一批 report.json")
    parser.add_argument("--regrade", type=Path, help="只重评已有 report.json，不调用模型")
    parser.add_argument("--review-report", type=Path, help="需要附加人工语义审阅的 report.json")
    parser.add_argument("--review-file", type=Path, help="结构化人工语义审阅 JSON")
    args = parser.parse_args()
    endpoint = urlparse(args.base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("本工具仅用于本机开发服务，禁止向远程地址发送账号凭据")
    if args.turn_timeout <= 0 or args.batch_timeout <= 0:
        parser.error("单轮和整批超时必须大于零")
    if args.regrade:
        directory = regrade_saved_report(args.regrade, args.output)
        results = json.loads((directory / "report.json").read_text(encoding="utf-8"))["summary"]
        return 1 if any(results["statuses"].get(key) for key in ("fail", "blocked")) else 0
    if bool(args.review_report) != bool(args.review_file):
        parser.error("--review-report 和 --review-file 必须同时使用")
    if args.review_report:
        output = apply_semantic_review(args.review_report, args.review_file)
        print(f"审阅后报告：{output}")
        return 0
    oracle = Oracle(args.database, args.username)
    workspace_id = oracle.workspace_id
    oracle.db.close()
    password = os.environ.get("GROVE_EVAL_PASSWORD")
    if not password:
        try:
            password, _, warning = password_for_run(workspace_id, prompt=getpass.getpass)
        except EOFError:
            parser.error(
                "非交互环境中未找到 demo 凭据；请先使用 "
                "evals.dialogue_loop --save-demo-password 保存当前 Workspace 钥匙串项"
            )
        if warning:
            print(warning)
    if args.preflight:
        return asyncio.run(run_preflight(args, password))
    return asyncio.run(run_suite(args, password))


if __name__ == "__main__":
    raise SystemExit(main())
