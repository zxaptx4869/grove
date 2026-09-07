"""固定对照的确定性评价、脱敏与 Markdown 报告。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path

from evals.dialogue_loop.core import SCENARIOS, frozen_budget

SENSITIVE_KEYS = {"password", "secret", "api_key", "token", "authorization"}


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
    return value


def cases_digest() -> str:
    raw = json.dumps(
        [{"id": item.id, "turns": item.turns} for item in SCENARIOS],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


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


def evaluate(results: list[dict], oracle: dict) -> dict:
    """只评价程序可证明边界；自然语言内容保持 review。"""
    projects = {item["name"]: item for item in oracle["projects"]}
    total = sum(item["entry_count"] for item in oracle["projects"])
    room = projects.get("房子装修")
    recent_room = [
        item["id"] for item in oracle["entries"] if room and item["project_id"] == room["id"]
    ][:5]
    evaluations = []
    for result in results:
        arm = result["arm"]
        scenario = result["scenario"]
        turns = result["turns"]
        for index, turn in enumerate(turns, 1):
            reasons = []
            if turn["status"] in {"failed", "blocked", "cancelled"}:
                status = "blocked" if turn["status"] == "blocked" else "fail"
                reasons.append(turn.get("error") or turn["status"])
            else:
                status = "review"
                answer = turn.get("answer", "")
                if scenario == "A":
                    expected = room["entry_count"] if index == 3 and room else total
                    if index in {1, 3} and str(expected) not in answer:
                        status = "fail"
                        reasons.append(f"公开回答未展示期望精确值 {expected}")
                    elif index in {2, 4}:
                        missing = [
                            item["name"]
                            for item in oracle["projects"]
                            if item["name"] not in answer or str(item["entry_count"]) not in answer
                        ]
                        if missing:
                            status = "fail"
                            reasons.append(f"分项目桶缺失或数值不符：{missing}")
                        else:
                            status = "pass"
                    else:
                        status = "pass"
                elif scenario == "B":
                    if index in {3, 4} and not _has_current_evidence(turn, arm):
                        status = "fail"
                        reasons.append("要求只依据知识库的回答没有当前轮 Evidence")
                    elif not answer.strip():
                        status = "fail"
                        reasons.append("回答为空")
                elif scenario == "C":
                    if index == 1:
                        actual = _new_list_ids(turn) if arm == "new" else _old_list_ids(turn)
                        if actual != recent_room:
                            status = "fail"
                            reasons.append(f"最近五条顺序不符：{actual}")
                        else:
                            status = "pass"
                    elif index == 2:
                        expected_id = recent_room[2] if len(recent_room) >= 3 else None
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
                        expected_id = recent_room[2] if len(recent_room) >= 3 else None
                        if not _has_current_evidence(turn, arm) or str(
                            expected_id
                        ) not in json.dumps(turn, ensure_ascii=False):
                            status = "fail"
                            reasons.append("未对原列表第三项形成当前轮来源 Evidence")
            evaluations.append(
                {
                    "arm": arm,
                    "scenario": scenario,
                    "turn": index,
                    "status": status,
                    "reasons": reasons,
                }
            )
    return {"turns": evaluations}


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
            "# 知识 Agent 统一对话循环全链路彩排"
            if clean.get("mode") == "rehearsal"
            else "# 知识 Agent 统一对话循环首批真实对照"
        ),
        "",
        f"- 批次：`{clean['batch_id']}`",
        f"- 时间：{clean['created_at']}",
        f"- 代码提交：`{clean['code']['commit']}`",
        f"- 运行模式：`{clean.get('mode', 'live')}`",
        f"- 固定用例摘要：`{clean['cases_sha256']}`",
        f"- 原业务库保持不变：{clean['isolation']['original_unchanged']}",
        f"- 已完整记录的用户消息：{usage['user_messages']} / 24",
        f"- 文本请求：{text_usage}",
        f"- 向量请求：{embedding_usage}",
        "- token：逐调用记录；缺失即为未知，不折算为零",
        "",
        "## 冻结配置与预检",
        "",
        "```json",
        json.dumps(
            {"budget": frozen_budget(), "preflight": clean["preflight"]},
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "## 逐组逐轮结果",
        "",
    ]
    for scenario in SCENARIOS:
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
                        turn.get("answer") or f"未产生回答：{turn.get('error') or '未知原因'}",
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
                                "usage": turn.get("usage"),
                                "budget": turn.get("budget"),
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


def initial_payload(batch_id: str) -> dict:
    return {
        "batch_id": batch_id,
        "created_at": datetime.now(UTC).isoformat(),
        "cases_sha256": cases_digest(),
    }
