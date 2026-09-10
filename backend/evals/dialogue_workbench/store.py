"""实验工作台公开记录的本地持久化。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from evals.dialogue_loop.report import sanitize

SCHEMA_VERSION = 1


class WorkbenchStore:
    """以 700/600 权限原子保存脱敏公开记录。"""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.path = self.root / "workbench.json"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": SCHEMA_VERSION, "sessions": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("工作台记录版本不受支持")
        for session in value.get("sessions", []):
            session["active"] = False
            for conversation in session.get("conversations", []):
                conversation["read_only"] = True
                conversation["recovery_notice"] = "服务已重启，模型运行上下文不可恢复。"
                for turn in conversation.get("turns", []):
                    turn.setdefault("completion", None)
                    if turn.get("completion"):
                        turn["completion"]["can_continue"] = False
                        turn["completion"]["continuation"] = None
                    if turn.get("status") in {"queued", "running"}:
                        turn["status"] = "interrupted"
                        turn["stage"] = "interrupted"
                        turn["error"] = "服务已重启，上一轮运行状态不可恢复。"
                        turn["completion"] = {
                            "status": "interrupted",
                            "reason_code": "service_restarted",
                            "reason": "服务重启后运行上下文不可恢复",
                            "incomplete_steps": ["上一轮执行被中断"],
                            "can_continue": False,
                            "continuation": None,
                        }
        return value

    def save(self, value: dict[str, Any]) -> None:
        safe = sanitize(value)
        temporary = self.root / ".workbench.json.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(safe, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            temporary.chmod(0o600)
            temporary.replace(self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)
