"""固定对照的确定性评价、脱敏与 Markdown 报告。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path

from evals.dialogue_loop.core import (
    ALL_SCENARIOS,
    EXPERIMENT_VERSION,
    PROMPT_VERSION,
    SCENARIOS,
    VARIANT_SCENARIOS,
    frozen_budget,
)

SENSITIVE_KEYS = {"password", "secret", "api_key", "token", "authorization"}
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
)


def _sanitize_text(value: str) -> str:
    for pattern in SENSITIVE_TEXT_PATTERNS:
        value = pattern.sub("<redacted>", value)
    return value


def sanitize(value):
    """同时完成敏感字段脱敏和 JSON 值规范化。"""
    if is_dataclass(value) and not isinstance(value, type):
        return sanitize(asdict(value))
    if hasattr(value, "model_dump"):
        return sanitize(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if key.lower() in SENSITIVE_KEYS else sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((sanitize(item) for item in value), key=str)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return sanitize(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def cases_digest(scenarios=SCENARIOS) -> str:
    raw = json.dumps(
        [{"id": item.id, "turns": item.turns} for item in scenarios],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def evaluation_plan() -> dict:
    """冻结待批准的第二版真实评测输入，不发送给 Agent。"""
    all_cases = (*SCENARIOS, *VARIANT_SCENARIOS)
    return {
        "base_scenarios": [item.id for item in SCENARIOS],
        "variant_scenarios": [
            {"id": item.id, "title": item.title, "turns": list(item.turns)}
            for item in VARIANT_SCENARIOS
        ],
        "scenario_count": len(all_cases),
        "turns_per_scenario": 4,
        "arms": 2,
        "maximum_user_messages": len(all_cases) * 4 * 2,
        "text_requests_per_batch": 192,
        "embedding_requests_per_batch": 64,
        "status": "awaiting_user_approval",
    }


def _new_list_ids(turn: dict) -> list[int]:
    for block in turn.get("blocks", []):
        if block.get("kind") == "list":
            return [item.get("entry_id") for item in block.get("items", [])]
    return []


def _old_list_ids(turn: dict) -> list[int]:
    snapshot = (turn.get("public_run") or {}).get("entry_result") or {}
    return [item.get("entry_id") for item in snapshot.get("items", [])]


def _has_current_evidence(turn: dict, arm: str) -> bool:
    if arm == "new":
        return any(block.get("kind") == "evidence" for block in turn.get("blocks", []))
    answer = (turn.get("public_run") or {}).get("answer") or {}
    return bool(answer.get("citations")) or any(
        point.get("citations") for point in answer.get("points", [])
    )


def _old_entry_result(turn: dict) -> dict:
    return (turn.get("public_run") or {}).get("entry_result") or {}


def _old_has_visible_result(turn: dict) -> bool:
    result = _old_entry_result(turn)
    return bool(result.get("items") or result.get("count") or result.get("group_counts"))


def _old_count(turn: dict) -> int | None:
    count = _old_entry_result(turn).get("count") or {}
    return count.get("value")


def _new_count(turn: dict) -> int | None:
    for block in turn.get("blocks", []):
        if block.get("kind") != "statistic":
            continue
        if block.get("value") is not None:
            return int(block["value"])
        match = re.fullmatch(r".*[：:]\s*(\d+)\s*", block.get("text", ""), re.DOTALL)
        if match:
            return int(match.group(1))
    return None


def _old_project_buckets(turn: dict) -> dict[str, int]:
    groups = _old_entry_result(turn).get("group_counts") or []
    project = next((item for item in groups if item.get("group_by") == "project"), None)
    return {
        item.get("label"): item.get("count")
        for item in (project or {}).get("buckets", [])
        if item.get("label") is not None
    }


def _new_project_buckets(turn: dict, projects: list[dict]) -> dict[str, int]:
    for block in turn.get("blocks", []):
        if block.get("kind") != "statistic":
            continue
        if block.get("group_by") == "project" and "buckets" in block:
            return {
                item.get("label"): item.get("count")
                for item in block.get("buckets", [])
                if item.get("label") is not None
            }
    answer = turn.get("answer", "")
    return {
        item["name"]: int(match.group(1))
        for item in projects
        if (
            match := re.search(
                rf"{re.escape(item['name'])}\s*[：:]\s*(\d+)", answer
            )
        )
    }


def _visible_answer(turn: dict, arm: str) -> str:
    answer = turn.get("answer") or ""
    if answer:
        return answer
    if arm == "old" and _old_has_visible_result(turn):
        return "公开结构化结果：\n\n```json\n" + json.dumps(
            _old_entry_result(turn), ensure_ascii=False, indent=2
        ) + "\n```"
    return f"未产生回答：{turn.get('error') or '未知原因'}"


def evaluate(results: list[dict], oracle: dict) -> dict:
    """只评价程序可证明边界；自然语言内容保持 review。"""
    projects = {item["name"]: item for item in oracle["projects"]}
    total = sum(item["entry_count"] for item in oracle["projects"])
    room = projects.get("房子装修")
    recent_room = [
        item["id"] for item in oracle["entries"] if room and item["project_id"] == room["id"]
    ][:5]
    xinjiang = projects.get("新疆旅行")
    xinjiang_method_count = sum(
        1
        for item in oracle["entries"]
        if xinjiang
        and item["project_id"] == xinjiang["id"]
        and item.get("main_type") == "method"
    )
    evaluations = []
    for result in results:
        arm = result["arm"]
        scenario = result["scenario"]
        turns = result["turns"]
        for index, turn in enumerate(turns, 1):
            reasons = []
            if turn["status"] in {"not_executed", "failed", "blocked", "cancelled"}:
                status = "blocked" if turn["status"] == "blocked" else "fail"
                reasons.append(turn.get("error") or turn["status"])
            else:
                status = "review"
                answer = turn.get("answer", "")
                if scenario == "A":
                    expected = room["entry_count"] if index == 3 and room else total
                    if index in {1, 3}:
                        matched = (
                            _old_count(turn) == expected
                            if arm == "old"
                            else _new_count(turn) == expected
                        )
                        if not matched:
                            status = "fail"
                            reasons.append(f"公开结果未展示期望精确值 {expected}")
                        else:
                            status = "pass"
                    elif index in {2, 4}:
                        if arm == "old":
                            buckets = _old_project_buckets(turn)
                            missing = [
                                item["name"]
                                for item in oracle["projects"]
                                if buckets.get(item["name"]) != item["entry_count"]
                            ]
                        else:
                            buckets = _new_project_buckets(turn, oracle["projects"])
                            missing = [
                                item["name"]
                                for item in oracle["projects"]
                                if buckets.get(item["name"]) != item["entry_count"]
                            ]
                        if missing:
                            status = "fail"
                            reasons.append(f"分项目桶缺失或数值不符：{missing}")
                        else:
                            status = "pass"
                elif scenario == "B":
                    if index == 4 and not _has_current_evidence(turn, arm):
                        status = "fail"
                        reasons.append("要求只依据知识库的回答没有当前轮 Evidence")
                    elif not answer.strip() and not (
                        arm == "old" and _old_has_visible_result(turn)
                    ):
                        status = "fail"
                        reasons.append("公开文字和结构化结果均为空")
                elif scenario == "C":
                    if index == 1:
                        actual = _new_list_ids(turn) if arm == "new" else _old_list_ids(turn)
                        if actual != recent_room:
                            status = "fail"
                            reasons.append(f"最近五条顺序不符：{actual}")
                        else:
                            status = "pass"
                    elif index == 2:
                        shown = (
                            _new_list_ids(turns[0])
                            if arm == "new"
                            else _old_list_ids(turns[0])
                        )
                        expected_id = shown[2] if len(shown) >= 3 else None
                        if expected_id is None or str(expected_id) not in json.dumps(
                            turn, ensure_ascii=False
                        ):
                            status = "fail"
                            reasons.append("未证明按实际列表第三项复验")
                    elif index == 3:
                        if turn.get("tool_calls"):
                            status = "fail"
                            reasons.append("明确不查知识库时仍发生工具调用")
                    elif index == 4:
                        shown = (
                            _new_list_ids(turns[0])
                            if arm == "new"
                            else _old_list_ids(turns[0])
                        )
                        expected_id = shown[2] if len(shown) >= 3 else None
                        if not _has_current_evidence(turn, arm) or str(
                            expected_id
                        ) not in json.dumps(turn, ensure_ascii=False):
                            status = "fail"
                            reasons.append("未对原列表第三项形成当前轮来源 Evidence")
                elif scenario == "D":
                    expected = {
                        1: room["entry_count"] if room else None,
                        2: xinjiang["entry_count"] if xinjiang else None,
                        3: xinjiang_method_count if xinjiang else None,
                        4: xinjiang["entry_count"] if xinjiang else None,
                    }[index]
                    actual = _old_count(turn) if arm == "old" else _new_count(turn)
                    if expected is None or actual != expected:
                        status = "fail"
                        reasons.append(f"项目／类型切换后的精确总数不符：期望 {expected}")
                    else:
                        status = "pass"
                elif scenario == "E":
                    if index == 1:
                        actual = _new_list_ids(turn) if arm == "new" else _old_list_ids(turn)
                        if actual != recent_room:
                            status = "fail"
                            reasons.append(f"最近五条顺序不符：{actual}")
                        else:
                            status = "pass"
                    elif index == 2:
                        shown = _new_list_ids(turns[0]) if arm == "new" else _old_list_ids(turns[0])
                        expected_id = shown[1] if len(shown) >= 2 else None
                        if expected_id is None or str(expected_id) not in json.dumps(
                            turn, ensure_ascii=False
                        ):
                            status = "fail"
                            reasons.append("未证明按实际列表第二项复验")
                    elif index == 3 and turn.get("tool_calls"):
                        status = "fail"
                        reasons.append("明确不查知识库时仍发生工具调用")
                    elif index == 4:
                        shown = _new_list_ids(turns[0]) if arm == "new" else _old_list_ids(turns[0])
                        expected_id = shown[1] if len(shown) >= 2 else None
                        if not _has_current_evidence(turn, arm) or str(
                            expected_id
                        ) not in json.dumps(turn, ensure_ascii=False):
                            status = "fail"
                            reasons.append("未对原列表第二项形成当前轮来源 Evidence")
            evaluations.append(
                {
                    "arm": arm,
                    "scenario": scenario,
                    "turn": index,
                    "status": status,
                    "reasons": reasons,
                }
            )
    dialogues = []
    for result in results:
        matching = [
            item
            for item in evaluations
            if item["arm"] == result["arm"] and item["scenario"] == result["scenario"]
        ]
        statuses = {item["status"] for item in matching}
        completed_turns = len(result.get("turns", []))
        if completed_turns < 4:
            status = "blocked"
        elif "fail" in statuses:
            status = "fail"
        elif "blocked" in statuses:
            status = "blocked"
        elif "review" in statuses:
            status = "review"
        elif matching:
            status = "pass"
        else:
            status = "pending"
        dialogues.append(
            {
                "arm": result["arm"],
                "scenario": result["scenario"],
                "status": status,
                "completed_turns": completed_turns,
                "required_turns": 4,
                "failed_turns": [
                    item["turn"] for item in matching if item["status"] in {"fail", "blocked"}
                ],
            }
        )
    return {"turns": evaluations, "dialogues": dialogues}


def write_report(report_dir: Path, payload: dict) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_dir.chmod(0o700)
    clean = sanitize(payload)
    json_path = report_dir / "report.json"
    md_path = report_dir / "report.md"
    json_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.chmod(0o600)
    by_eval = {
        (item["arm"], item["scenario"], item["turn"]): item
        for item in clean.get("evaluation", {}).get("turns", [])
    }
    usage = clean["resource_usage"]
    expected_messages = clean.get("budget", {}).get("messages_per_batch", 24)
    if usage.get("complete", True):
        text_usage = f"{usage['text_requests']} / 192"
        embedding_usage = f"{usage['embedding_requests']} / 64"
    else:
        text_usage = f"未知（已记录下界 {usage['recorded_text_requests']} / 192）"
        embedding_usage = (
            f"未知（已记录下界 {usage['recorded_embedding_requests']} / 64）"
        )
    lines = [
        (
            f"# 知识 Agent 统一对话循环 {clean.get('experiment_version', 'v1')} 全链路彩排"
            if clean.get("mode") == "rehearsal"
            else f"# 知识 Agent 统一对话循环 {clean.get('experiment_version', 'v1')} 固定真实对照"
        ),
        "",
        f"- 批次：`{clean['batch_id']}`",
        f"- 时间：{clean['created_at']}",
        f"- 代码提交：`{clean['code']['commit']}`",
        f"- 运行模式：`{clean.get('mode', 'live')}`",
        f"- 实验版本：`{clean.get('experiment_version', 'unknown')}`",
        f"- Prompt 版本：`{clean.get('prompt_version', 'unknown')}`",
        f"- 固定用例摘要：`{clean['cases_sha256']}`",
        f"- 原业务库保持不变：{clean['isolation']['original_unchanged']}",
        f"- 已完整记录的用户消息：{usage['user_messages']} / {expected_messages}",
        f"- 文本请求：{text_usage}",
        f"- 向量请求：{embedding_usage}",
        "- token：逐调用记录；缺失即为未知，不折算为零",
        "",
        "## 冻结配置与预检",
        "",
        "```json",
        json.dumps(
            {"budget": clean.get("budget", frozen_budget()), "preflight": clean["preflight"]},
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## 新旧路径资源汇总",
        "",
        "```json",
        json.dumps(usage.get("by_arm", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## 逐组逐轮结果",
        "",
    ]
    result_scenarios = {item["scenario"] for item in clean["results"]}
    for scenario in (item for item in ALL_SCENARIOS if item.id in result_scenarios):
        lines.extend([f"### {scenario.id}：{scenario.title}", ""])
        for arm in ("old", "new"):
            result = next(
                (
                    item
                    for item in clean["results"]
                    if item["scenario"] == scenario.id and item["arm"] == arm
                ),
                None,
            )
            lines.extend([f"#### {'旧流程' if arm == 'old' else '新循环'}", ""])
            if result is None:
                lines.extend(["未执行（整批停止）。", ""])
                continue
            for index, turn in enumerate(result["turns"], 1):
                ev = by_eval.get((arm, scenario.id, index), {"status": "pending", "reasons": []})
                lines.extend(
                    [
                        f"**第 {index} 轮 · {ev['status']} · {turn['duration_ms']} ms**",
                        "",
                        f"> 用户：{turn['message']}",
                        "",
                        _visible_answer(turn, arm),
                        "",
                    ]
                )
                if ev.get("reasons"):
                    lines.append("检查：" + "；".join(ev["reasons"]))
                    lines.append("")
                lines.extend(
                    [
                        "<details><summary>工具、模型、usage 与原始错误</summary>",
                        "",
                        "```json",
                        json.dumps(
                            {
                                "status": turn["status"],
                                "error": turn.get("error"),
                                "error_details": turn.get("error_details"),
                                "solve_error": turn.get("solve_error"),
                                "solve_failure": turn.get("solve_failure"),
                                "finalization": turn.get("finalization"),
                                "usage": turn.get("usage"),
                                "budget": turn.get("budget"),
                                "context": turn.get("context"),
                                "tool_calls": turn.get("tool_calls", []),
                                "model_calls": turn.get("model_calls", []),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        "```",
                        "",
                        "</details>",
                        "",
                    ]
                )
    human_review = clean.get("human_review")
    if human_review:
        lines.extend(["## 人工语义审阅", ""])
        for key, label in (("A", "A：统计和范围"), ("B", "B：混合问答"), ("C", "C：列表与话题")):
            lines.extend([f"### {label}", "", human_review[key], ""])
        lines.extend(["### 总体判断", "", human_review["overall"], ""])
    if clean.get("evaluation", {}).get("dialogues"):
        lines.extend(
            [
                "## 整段任务完成状态",
                "",
                "```json",
                json.dumps(clean["evaluation"]["dialogues"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    if clean.get("evaluation_plan"):
        lines.extend(
            [
                "## 待批准的下一批评测计划",
                "",
                "```json",
                json.dumps(clean["evaluation_plan"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## 分层结论",
            "",
            "### 架构效果",
            "",
            clean["conclusion"]["architecture"],
            "",
            "### 共享工具缺陷",
            "",
            clean["conclusion"]["shared_tools"],
            "",
            "### 旧流程已有数据库问题",
            "",
            clean["conclusion"]["old_database"],
            "",
            "### 是否值得正式接入",
            "",
            clean["conclusion"]["recommendation"],
            "",
            "### 局限",
            "",
            (
                "本报告只覆盖同一 demo 快照、同一模型配置和三组固定四轮的单批实验；"
                "自动边界通过不等于自然语言语义已通过人工审阅，也不证明 App、"
                "旧工作集生命周期、生产恢复或总体成功率。"
            ),
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    md_path.chmod(0o600)
    return md_path, json_path


def initial_payload(batch_id: str, scenarios=SCENARIOS) -> dict:
    return {
        "batch_id": batch_id,
        "experiment_version": EXPERIMENT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "cases_sha256": cases_digest(scenarios),
        "evaluation_plan": evaluation_plan(),
    }
