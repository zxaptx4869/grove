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

from evals.knowledge_agent_cases import Case, Turn, build_cases

TERMINAL = {"completed", "partial", "failed", "cancelled"}
MAIN_TYPES = {"knowledge", "method", "parameter", "reminder"}
PREFIX = "/api/knowledge-agent"
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
                "SELECT e.id,e.project_id,e.main_type,e.updated_at FROM entries e "
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
        data["assistant_text"] = self.rows(
            "SELECT content FROM knowledge_messages "
            "WHERE run_id=? AND conversation_id=? AND role='assistant'",
            (run_id, conversation_id),
        )[0]["content"]
        return data

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


def collect_facts(run: dict, diagnostic: dict) -> list[dict]:
    """只从结构化结果读取数字，综合回答还必须实际展示对应服务端事实。"""
    facts = []
    snapshot = run.get("entry_result") or {}
    entry_set = snapshot.get("set_summary") or {}
    if snapshot.get("count") is not None:
        facts.append({"kind": "count", **snapshot["count"], "entry_set": entry_set})
    for group in snapshot.get("group_counts", []):
        facts.append({"kind": "group", **group, "entry_set": entry_set})
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
                        "entry_set": sets.get(fact["request_id"]),
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
    if any(item.get("is_fallback") for item in invocations) or (
        run.get("fallback_summary") or {}
    ).get("has_fallback"):
        errors.append("存在显式降级，不能计作正常链路通过")
    if run["status"] != "completed":
        errors.append(f"Run 终态为 {run['status']}")
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
    rows = expected_rows(snapshot, project_id, turn)
    expected: object = None
    actual: object = None
    facts = collect_facts(run, diagnostic)
    eligible = [
        fact
        for fact in facts
        if fact["kind"] == turn.kind
        and fact.get("completeness") == "complete"
        and matches_set(fact.get("entry_set"), turn)
    ]
    if turn.kind == "count":
        expected = len(rows)
        actual = [fact.get("value") for fact in facts if fact["kind"] == "count"]
        if not any(fact.get("value") == expected for fact in eligible):
            errors.append("缺少口径匹配且完整的精确总数")
    elif turn.kind == "group":
        key = "project_id" if turn.group_by == "project" else "main_type"
        expected = dict(Counter(str(row[key]) for row in rows))
        if turn.group_by == "project":
            expected = {
                str(p["id"]): expected.get(str(p["id"]), 0)
                for p in snapshot["projects"]
                if project_id is None or p["id"] == project_id
            }
        actual = [fact for fact in facts if fact["kind"] == "group"]
        if not any(
            fact.get("group_by") == turn.group_by
            and {str(bucket["key"]): bucket["count"] for bucket in fact.get("buckets", [])}
            == expected
            for fact in eligible
        ):
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
        if actual != expected or not matches_set(snapshot_result.get("set_summary"), turn):
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
    status = "fail" if errors else "review" if turn.review else "pass"
    return {
        "status": status,
        "errors": errors,
        "expected": expected,
        "actual": actual,
        "clarification": clarification,
        "real_model_calls": len(live),
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
    return {
        "cases": len(report["cases"]),
        "turns": len(turns),
        "statuses": dict(counts),
        "fully_passed_cases": sum(
            bool(case["turns"])
            and all(turn["evaluation"]["status"] == "pass" for turn in case["turns"])
            for case in report["cases"]
        ),
        "unnecessary_clarifications": sum(
            "不必要澄清" in turn["evaluation"]["errors"] for turn in turns
        ),
        "model_invocations": len(invocations),
        "fallback_invocations": sum(bool(item["is_fallback"]) for item in invocations),
        "invocations_with_usage": sum(bool(item.get("usage")) for item in invocations),
        "models": sorted(
            {f"{item['provider']}/{item['model']}" for item in invocations if item.get("model")}
        ),
        "median_seconds": round(statistics.median(elapsed), 2) if elapsed else None,
        "max_seconds": round(max(elapsed), 2) if elapsed else None,
    }


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
        f"- 模型阶段记录：{stats['model_invocations']}；降级 {stats['fallback_invocations']}",
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
    for name, value in (
        ("report.json", json.dumps(report, ensure_ascii=False, indent=2)),
        ("report.md", markdown_report(report)),
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
    comparable = (
        old["baseline"]["domain_hashes"] == new["baseline"]["domain_hashes"]
        and old["provider"] == new["provider"]
        and old.get("suite_digest") == new.get("suite_digest")
        and old.get("domain_unchanged") is True
        and new.get("domain_unchanged") is True
    )
    return {
        "comparable_data_model_suite": comparable,
        "matched_turns": len(common),
        "note": "运行中配置未由服务端完整公开；即使可比，也需核对特性开关。",
        "changes": [
            {
                "case": key[0],
                "repeat": key[1],
                "turn": key[2] + 1,
                "before": before[key]["evaluation"]["status"],
                "after": after[key]["evaluation"]["status"],
            }
            for key in sorted(common)
            if before[key]["evaluation"]["status"] != after[key]["evaluation"]["status"]
        ],
    }


def scope_payload(project_id: int | None) -> dict:
    return {
        "scope_type": "workspace" if project_id is None else "project",
        "project_id": project_id,
    }


def blocked_reason(turn: Turn, previous: dict | None) -> str | None:
    previous = previous or {}
    items = (previous.get("run", {}).get("entry_result") or {}).get("items", [])
    if turn.reference_previous and len(items) < 2:
        return "上一轮没有返回两个对象，未发送无锚点指代"
    if turn.requires_previous_answer and previous.get("evaluation", {}).get("status") not in {
        "pass",
        "review",
    }:
        return "上一轮回答未通过前置检查，后续解释追问留待修复后验证"
    return None


async def run_case(
    client, oracle, snapshot, scopes, case: Case, repeat: int, report, directory, seconds
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
            record["turns"].append(
                {
                    "message": turn.message,
                    "evaluation": {
                        "status": "blocked",
                        "errors": [blocked],
                    },
                }
            )
            save_report(report, directory)
            continue
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
            run = await wait_run(client, run_id, seconds)
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


async def run_suite(args, password: str) -> int:
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
    if args.cases:
        selected = set(args.cases.split(","))
        if selected - {case.id for case in cases}:
            raise ValueError("指定场景不存在，或其所需空项目不存在")
        cases = [case for case in cases if case.id in selected]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    directory = args.output / stamp
    directory.mkdir(parents=True, mode=0o700)
    process = await asyncio.create_subprocess_exec(
        "git",
        "rev-parse",
        "HEAD",
        stdout=asyncio.subprocess.PIPE,
    )
    revision, _ = await process.communicate()
    if process.returncode:
        raise ValueError("无法记录本次评测的 Git 版本")
    report = {
        "schema_version": 1,
        "batch_id": stamp,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "git_revision": revision.decode().strip(),
        "username": args.username,
        "workspace_id": oracle.workspace_id,
        "baseline": baseline,
        "provider": oracle.provider(),
        "scopes": scopes,
        "cases": [],
        "suite_digest": digest([asdict(case) for case in cases]),
        "suite": [asdict(case) for case in cases],
        "repeat": args.repeat,
        "runner_sha256": hashlib.sha256(
            await asyncio.to_thread(Path(__file__).read_bytes)
        ).hexdigest(),
    }
    authenticated = False
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
            if args.compare:
                report["comparison"] = compare_reports(
                    json.loads(args.compare.read_text(encoding="utf-8")),
                    report,
                )
            save_report(report, directory)
            oracle.db.close()
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database", type=Path, default=Path("grove.db"))
    parser.add_argument("--username", default="demo")
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/grove-agent-eval"))
    parser.add_argument("--cases", help="仅运行指定场景，英文逗号分隔")
    parser.add_argument("--repeat", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--turn-timeout", type=float, default=240)
    parser.add_argument("--compare", type=Path, help="上一批 report.json")
    args = parser.parse_args()
    endpoint = urlparse(args.base_url)
    if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("本工具仅用于本机开发服务，禁止向远程地址发送账号凭据")
    if args.turn_timeout <= 0:
        parser.error("单轮超时必须大于零")
    password = os.environ.get("GROVE_EVAL_PASSWORD") or getpass.getpass("demo 登录密码：")
    return asyncio.run(run_suite(args, password))


if __name__ == "__main__":
    raise SystemExit(main())
