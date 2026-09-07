"""父进程编排：一次快照、交替两臂、硬停止与本地报告。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from evals.dialogue_loop.core import (
    ALL_SCENARIOS,
    EXPERIMENT_VERSION,
    SCENARIOS,
    VARIANT_SCENARIOS,
    frozen_budget,
)
from evals.dialogue_loop.credentials import (
    delete_demo_password,
    password_for_run,
    save_demo_password,
)
from evals.dialogue_loop.isolation import (
    backup_database,
    domain_fingerprint,
    identity_snapshot,
    oracle_snapshot,
    secure_dir,
    secure_file,
    sqlite_path,
)
from evals.dialogue_loop.report import evaluate, initial_payload, write_report


class InfrastructureFailure(RuntimeError):
    """保留子进程完整错误，并用末行而非公共 traceback 前缀判断同类。"""

    def __init__(self, detail: str, returncode: int, partial: dict | None = None):
        self.detail = detail
        self.returncode = returncode
        self.partial = partial
        lines = [line.strip() for line in detail.splitlines() if line.strip()]
        exception_lines = [
            line for line in lines if re.match(r"^[\w.]+(?:Error|Exception):", line)
        ]
        signature_line = exception_lines[-1] if exception_lines else (lines[-1] if lines else "")
        self.signature = signature_line[:300] if signature_line else f"exit:{returncode}"
        super().__init__(f"隔离子进程失败（{returncode}）：{self.signature}")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="知识 Agent 统一对话循环隔离实验")
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="只执行无模型预检（默认）")
    mode.add_argument(
        "--rehearsal", action="store_true", help="无模型走完两臂编排、检查点与报告"
    )
    mode.add_argument("--compare", action="store_true", help="执行固定两臂对照")
    mode.add_argument(
        "--save-demo-password",
        action="store_true",
        help="隐藏读取并校验后保存 demo 密码到系统钥匙串",
    )
    mode.add_argument(
        "--forget-demo-password",
        action="store_true",
        help="删除当前 demo Workspace 的实验密码钥匙串项",
    )
    mode.add_argument(
        "--regrade", type=Path, metavar="REPORT_JSON", help="只重评已保存报告，不调用模型"
    )
    value.add_argument("--live", action="store_true", help="显式允许真实模型请求")
    value.add_argument(
        "--suite",
        choices=("base", "v2"),
        default="base",
        help="base 为原三组；v2 另含两组未写入提示词的表达变体",
    )
    value.add_argument("--internal-preflight", action="store_true", help=argparse.SUPPRESS)
    value.add_argument("--internal-arm", choices=("old", "new"), help=argparse.SUPPRESS)
    value.add_argument(
        "--scenario", choices=tuple(item.id for item in ALL_SCENARIOS), help=argparse.SUPPRESS
    )
    value.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    value.add_argument("--original", type=Path, help=argparse.SUPPRESS)
    value.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    value.add_argument("--text-used", type=int, default=0, help=argparse.SUPPRESS)
    value.add_argument("--embedding-used", type=int, default=0, help=argparse.SUPPRESS)
    return value


def _child_env(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.resolve()}",
            "PROCESSING_WORKER_ENABLED": "false",
            "CONTEXT_WORKER_ENABLED": "false",
            "DIRECTORY_DRAFT_WORKER_ENABLED": "false",
            "EMBEDDING_WORKER_ENABLED": "false",
            "KNOWLEDGE_AGENT_WORKER_ENABLED": "false",
        }
    )
    return env


def _child(args: list[str], db_path: Path, password: str, result_path: Path) -> dict:
    command = [
        sys.executable,
        "-m",
        "evals.dialogue_loop",
        *args,
        "--db",
        str(db_path),
        "--result",
        str(result_path),
    ]
    completed = subprocess.run(
        command,
        input=password + "\n",
        text=True,
        capture_output=True,
        env=_child_env(db_path),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "子进程无错误输出"
        partial = None
        if result_path.is_file():
            try:
                partial = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                partial = None
        raise InfrastructureFailure(detail[-8_000:], completed.returncode, partial)
    data = json.loads(result_path.read_text(encoding="utf-8"))
    result_path.unlink(missing_ok=True)
    return data


def _source_database(backend_dir: Path) -> Path:
    from app.core.config import get_settings

    path = sqlite_path(get_settings().database_url, backend_dir=backend_dir)
    if not path.is_file():
        raise ValueError(f"开发数据库不存在：{path}")
    return path


def _git_state(repo_root: Path) -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=True
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return {"commit": commit, "branch": branch}


def _conclusion(results: list[dict], evaluation: dict, stopped: str | None) -> dict:
    statuses = Counter(item["status"] for item in evaluation["turns"])
    new_failures = [
        item
        for item in evaluation["turns"]
        if item["arm"] == "new" and item["status"] in {"fail", "blocked"}
    ]
    comparable = [
        item for item in evaluation["turns"] if item["status"] not in {"blocked", "pending"}
    ]
    tool_errors = []
    boundary_rejections = []
    old_db_errors = []
    for result in results:
        for turn in result["turns"]:
            for call in turn.get("tool_calls", []):
                if call.get("status") == "denied":
                    boundary_rejections.append(
                        f"{result['arm']}/{result['scenario']}：{call.get('tool')} "
                        f"{call.get('error') or 'denied'}"
                    )
                elif call.get("status") in {"error", "partial"}:
                    tool_errors.append(
                        f"{result['arm']}/{result['scenario']}：{call.get('tool')} "
                        f"{call.get('error') or call.get('status')}"
                    )
            error = turn.get("error") or ""
            if result["arm"] == "old" and any(
                word in error
                for word in ("IntegrityError", "OperationalError", "database", "UNIQUE")
            ):
                old_db_errors.append(f"{result['scenario']}：{error}")
    if stopped or not comparable or new_failures:
        recommendation = "证据不足，不建议据此进入正式接入；应先审阅失败证据，且不得付费补跑本批。"
    else:
        recommendation = (
            "自动确定性边界未见新循环失败；仍须完成逐轮人工语义审阅，"
            "并确认可比轮次有具体改善且无新增退化后，才值得提出正式接入方案。"
        )
    return {
        "architecture": (
            f"自动评价汇总：{dict(statuses)}。"
            "旧流程与新循环的差异必须只在两臂均完成的可比轮次解释。"
            + (
                f"程序边界拒绝 {len(boundary_rejections)} 次非法或越权工具请求；"
                "这反映 Agent 请求行为，不归类为共享工具故障。"
                if boundary_rejections
                else ""
            )
        ),
        "shared_tools": "；".join(tool_errors)
        if tool_errors
        else "本批未识别到可归因于共享只读工具的确定性错误；语义漏答仍需人工审阅。",
        "old_database": "；".join(old_db_errors)
        if old_db_errors
        else "本批未观察到可明确归类的旧流程数据库错误。",
        "recommendation": recommendation,
    }


def _resource_by_arm(results: list[dict]) -> dict:
    summary = {}
    for arm in ("old", "new"):
        turns = [
            turn for result in results if result["arm"] == arm for turn in result["turns"]
        ]
        model_calls = [
            call
            for turn in turns
            for call in turn.get("model_calls", [])
        ]
        text_calls = [call for call in model_calls if call.get("kind") == "text"]
        usages = [call["usage"] for call in text_calls if call.get("usage") is not None]
        summary[arm] = {
            "user_messages": len(turns),
            "text_requests": sum(
                (turn.get("budget") or {}).get("turn", {}).get("text_requests", 0)
                for turn in turns
            ),
            "embedding_requests": sum(
                (turn.get("budget") or {}).get("turn", {}).get("embedding_requests", 0)
                for turn in turns
            ),
            "duration_ms": sum(turn.get("duration_ms", 0) for turn in turns),
            "input_tokens": sum(item.get("input_tokens", 0) for item in usages),
            "output_tokens": sum(item.get("output_tokens", 0) for item in usages),
            "cache_read_tokens": sum(item.get("cache_read_tokens", 0) for item in usages),
            "token_usage_complete": len(usages) == len(text_calls),
            "cost_available": bool(usages) and all(item.get("cost") is not None for item in usages),
            "input_estimation": _input_estimation_by_scope(model_calls),
        }
    return summary


def _input_estimation_by_scope(model_calls: list[dict]) -> dict:
    """汇总已派发误差，并明确保留未派发请求的真实 token 未知。"""
    scopes: dict[str, dict] = {}
    for call in model_calls:
        estimate = call.get("estimated_input_tokens")
        if estimate is None or call.get("kind") not in {"text", "text_not_dispatched"}:
            continue
        scope = call.get("request_scope") or "unknown"
        row = scopes.setdefault(
            scope,
            {
                "dispatched_with_usage": 0,
                "actual_unknown": 0,
                "not_dispatched": 0,
                "estimated_tokens": 0,
                "estimated_tokens_with_usage": 0,
                "actual_tokens": 0,
                "min_ratio": None,
                "max_ratio": None,
            },
        )
        row["estimated_tokens"] += estimate
        actual = call.get("actual_input_tokens")
        if actual is None:
            usage = call.get("usage") or {}
            actual = usage.get("input_tokens")
        if call.get("kind") == "text_not_dispatched":
            row["not_dispatched"] += 1
            row["actual_unknown"] += 1
            continue
        if not isinstance(actual, int | float) or actual <= 0:
            row["actual_unknown"] += 1
            continue
        row["dispatched_with_usage"] += 1
        row["estimated_tokens_with_usage"] += estimate
        row["actual_tokens"] += actual
        ratio = estimate / actual
        row["min_ratio"] = ratio if row["min_ratio"] is None else min(row["min_ratio"], ratio)
        row["max_ratio"] = ratio if row["max_ratio"] is None else max(row["max_ratio"], ratio)
    for row in scopes.values():
        row["aggregate_ratio"] = (
            round(row["estimated_tokens_with_usage"] / row["actual_tokens"], 6)
            if row["actual_tokens"]
            else None
        )
        if row["min_ratio"] is not None:
            row["min_ratio"] = round(row["min_ratio"], 6)
            row["max_ratio"] = round(row["max_ratio"], 6)
    return scopes


def regrade_report(path: Path) -> int:
    """仅使用已保存的原始结果重评，不登录或调用模型。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evaluation"] = evaluate(payload["results"], payload["oracle"])
    payload["conclusion"] = _conclusion(
        payload["results"], payload["evaluation"], payload.get("stop_reason")
    )
    payload["resource_usage"]["by_arm"] = _resource_by_arm(payload["results"])
    payload["regraded_at"] = datetime.now().astimezone().isoformat()
    md_path, json_path = write_report(path.parent, payload)
    print(f"已离线重评：{md_path}")
    print(f"原始记录：{json_path}")
    failed = any(
        item["status"] in {"fail", "blocked"} for item in payload["evaluation"]["turns"]
    )
    return 1 if failed else 0


def run_parent(args: argparse.Namespace) -> int:
    if args.compare and not args.live:
        raise ValueError("真实对照必须同时显式传入 --compare --live")
    if args.live and not args.compare:
        raise ValueError("--live 只能与 --compare 一起使用")
    repo_root = Path(__file__).resolve().parents[3]
    backend_dir = repo_root / "backend"
    original = _source_database(backend_dir)
    identity = identity_snapshot(original)
    workspace_id = identity["workspace_id"]
    if args.forget_demo_password:
        try:
            delete_demo_password(workspace_id)
        except Exception as exc:
            raise RuntimeError(f"系统钥匙串删除失败（{type(exc).__name__}）") from None
        print("已删除当前 demo Workspace 的实验密码钥匙串项。")
        return 0
    if args.save_demo_password:
        password = getpass.getpass("demo 密码（验证后保存到系统钥匙串）：")
        with tempfile.TemporaryDirectory(prefix="grove-dialogue-loop-credential-") as temp_name:
            temp_dir = Path(temp_name)
            temp_dir.chmod(0o700)
            copy_db = temp_dir / "credential-check.db"
            result_path = temp_dir / "credential-check.json"
            backup_database(original, copy_db)
            verified = _child(
                ["--internal-preflight", "--original", str(original)],
                copy_db,
                password,
                result_path,
            )
        if verified["identity"] != identity:
            raise RuntimeError("隔离身份校验结果与原库身份快照不一致")
        try:
            save_demo_password(workspace_id, password)
        except Exception as exc:
            raise RuntimeError(f"系统钥匙串保存失败（{type(exc).__name__}）") from None
        print("demo 密码已验证并保存到当前 Workspace 的系统钥匙串。")
        return 0
    original_before = domain_fingerprint(original, identity["workspace_id"])
    password, from_keychain, keychain_error = password_for_run(
        workspace_id, prompt=getpass.getpass
    )
    if keychain_error:
        print(f"{keychain_error}，已回退到隐藏输入。", file=sys.stderr)
    elif from_keychain:
        print("已从系统钥匙串读取 demo 密码。")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_id = f"{EXPERIMENT_VERSION}-{timestamp}"
    if args.rehearsal:
        batch_id = f"{EXPERIMENT_VERSION}-rehearsal-{timestamp}"
    report_dir = backend_dir / "data" / "knowledge-agent-evals" / "dialogue-loop" / batch_id
    secure_dir(report_dir)
    with tempfile.TemporaryDirectory(prefix="grove-dialogue-loop-") as temp_name:
        temp_dir = Path(temp_name)
        temp_dir.chmod(0o700)
        seed = temp_dir / "seed.db"
        old_db = temp_dir / "old.db"
        new_db = temp_dir / "new.db"
        backup_database(original, seed)
        shutil.copy2(seed, old_db)
        shutil.copy2(seed, new_db)
        secure_file(old_db)
        secure_file(new_db)
        # 父进程只制作快照、不导入数据库引擎或执行 Run；Worker 环境门禁在每个
        # 真正连接副本的子进程内执行，避免把父进程环境误判为执行环境。
        preflights = []
        for arm, db_path in (("old", old_db), ("new", new_db)):
            child_result = temp_dir / f"preflight-{arm}.json"
            preflight = _child(
                ["--internal-preflight", "--original", str(original)],
                db_path,
                password,
                child_result,
            )
            preflight["arm"] = arm
            preflights.append(preflight)
        blockers = [message for item in preflights for message in item["blockers"]]
        provider_equal = preflights[0]["provider"] == preflights[1]["provider"]
        if not provider_equal:
            blockers.append("两臂模型配置不一致")
        oracle = oracle_snapshot(seed, identity["workspace_id"])
        selected_scenarios = SCENARIOS if args.suite == "base" else ALL_SCENARIOS
        required_projects = {"房子装修"}
        if args.suite == "v2":
            required_projects.add("新疆旅行")
        if not required_projects <= {item["name"] for item in oracle["projects"]}:
            missing_projects = sorted(
                required_projects - {item["name"] for item in oracle["projects"]}
            )
            blockers.append(f"固定用例所需项目不存在：{missing_projects}")
        if (
            len(
                [
                    item
                    for item in oracle["entries"]
                    if item["project_id"]
                    == next((p["id"] for p in oracle["projects"] if p["name"] == "房子装修"), None)
                ]
            )
            < 5
        ):
            blockers.append("房子装修项目不足五条正式记录")
        payload = initial_payload(batch_id, selected_scenarios)
        payload.update(
            {
                "code": _git_state(repo_root),
                "mode": "rehearsal" if args.rehearsal else "live" if args.compare else "preflight",
                "budget": frozen_budget(len(selected_scenarios) * 4 * 2),
                "preflight": {
                    "ok": not blockers,
                    "blockers": blockers,
                    "arms": preflights,
                    "provider_equal": provider_equal,
                },
                "oracle": oracle,
                "results": [],
            }
        )
        stopped = None
        text_used = 0
        embedding_used = 0
        messages = 0
        infrastructure = Counter()
        infrastructure_errors = []
        if (args.rehearsal or (args.compare and args.live)) and not blockers:
            order = [
                ("A", "new"),
                ("A", "old"),
                ("B", "old"),
                ("B", "new"),
                ("C", "new"),
                ("C", "old"),
            ]
            if args.suite == "v2":
                order.extend(
                    [
                        (VARIANT_SCENARIOS[0].id, "old"),
                        (VARIANT_SCENARIOS[0].id, "new"),
                        (VARIANT_SCENARIOS[1].id, "new"),
                        (VARIANT_SCENARIOS[1].id, "old"),
                    ]
                )
            for scenario, arm in order:
                result_path = temp_dir / f"{scenario}-{arm}.json"
                try:
                    child_args = [
                            "--internal-arm",
                            arm,
                            "--scenario",
                            scenario,
                            "--original",
                            str(original),
                            "--text-used",
                            str(text_used),
                            "--embedding-used",
                            str(embedding_used),
                        ]
                    if args.rehearsal:
                        child_args.append("--rehearsal")
                    result = _child(
                        child_args,
                        old_db if arm == "old" else new_db,
                        password,
                        result_path,
                    )
                except InfrastructureFailure as exc:
                    signature = exc.signature
                    infrastructure[signature] += 1
                    infrastructure_errors.append(
                        {
                            "arm": arm,
                            "scenario": scenario,
                            "signature": signature,
                            "error": exc.detail,
                        }
                    )
                    payload["results"].append(
                        exc.partial
                        or {
                            "arm": arm,
                            "scenario": scenario,
                            "title": "基础设施异常",
                            "turns": [],
                        }
                    )
                    if exc.partial:
                        text_used = max(
                            text_used,
                            int(exc.partial.get("batch_text_requests", text_used)),
                        )
                        embedding_used = max(
                            embedding_used,
                            int(exc.partial.get("batch_embedding_requests", embedding_used)),
                        )
                        messages += len(exc.partial.get("turns", []))
                    if infrastructure[signature] >= 2:
                        stopped = f"相同基础设施异常第二次发生：{signature}"
                        break
                    continue
                payload["results"].append(result)
                text_used = result["batch_text_requests"]
                embedding_used = result["batch_embedding_requests"]
                messages += sum(1 for turn in result["turns"] if turn["status"] != "blocked")
                if not result["business_data_unchanged"]:
                    stopped = f"{arm}/{scenario} 业务表或附件指纹变化"
                    break
        elif (args.compare or args.rehearsal) and blockers:
            stopped = "预检失败，未启动彩排或真实评测"
        original_after = domain_fingerprint(original, identity["workspace_id"])
        if original_after != original_before:
            stopped = "原业务库业务表或附件指纹发生变化"
        if args.rehearsal:
            payload["evaluation"] = {
                "turns": [
                    {
                        "arm": item["arm"],
                        "scenario": item["scenario"],
                        "turn": index,
                        "status": "pass",
                        "reasons": ["仅验证基础设施全链路，不评价语义"],
                    }
                    for item in payload["results"]
                    for index, _turn in enumerate(item["turns"], 1)
                ]
            }
        else:
            payload["evaluation"] = evaluate(payload["results"], oracle)
        payload["isolation"] = {
            "original_unchanged": original_before == original_after,
            "old_copy_business_unchanged": all(
                item.get("business_data_unchanged", True)
                for item in payload["results"]
                if item["arm"] == "old"
            ),
            "new_copy_business_unchanged": all(
                item.get("business_data_unchanged", True)
                for item in payload["results"]
                if item["arm"] == "new"
            ),
        }
        payload["resource_usage"] = {
            "user_messages": messages,
            "text_requests": text_used if not infrastructure_errors else None,
            "embedding_requests": embedding_used if not infrastructure_errors else None,
            "recorded_text_requests": text_used,
            "recorded_embedding_requests": embedding_used,
            "complete": not infrastructure_errors,
            "tokens_complete": not infrastructure_errors
            and all(
                call.get("usage") is not None
                for item in payload["results"]
                for turn in item["turns"]
                for call in turn.get("model_calls", [])
                if call.get("kind") == "text"
            ),
            "by_arm": _resource_by_arm(payload["results"]),
        }
        payload["stop_reason"] = stopped
        payload["infrastructure_errors"] = infrastructure_errors
        if args.rehearsal:
            payload["conclusion"] = {
                "architecture": "彩排不调用模型，不产生架构效果结论。",
                "shared_tools": "彩排使用本地代表值，不验收共享工具语义。",
                "old_database": "仅校验隔离副本和指纹，不执行旧流程业务链。",
                "recommendation": (
                    "六个子进程、二十四个检查点和最终报告全部完成时，"
                    "只证明基础设施可进入真实实验决策。"
                ),
            }
        else:
            payload["conclusion"] = _conclusion(
                payload["results"], payload["evaluation"], stopped
            )
        md_path, json_path = write_report(report_dir, payload)
    print(f"预检：{'通过' if not blockers else '失败'}")
    for blocker in blockers:
        print(f"- {blocker}")
    print(f"报告：{md_path}")
    print(f"原始记录：{json_path}")
    if args.compare or args.rehearsal:
        qualifier = "已记录下界" if infrastructure_errors else "实际"
        print(
            f"已记录消息：{messages}/{len(selected_scenarios) * 4 * 2}，"
            f"{qualifier}文本请求：{text_used}/192，"
            f"{qualifier}向量请求：{embedding_used}/64"
        )
    evaluation_failed = args.compare and any(
        item["status"] in {"fail", "blocked"} for item in payload["evaluation"]["turns"]
    )
    return 1 if blockers or stopped or evaluation_failed else 0
