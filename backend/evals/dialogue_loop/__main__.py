"""模块入口；内部子进程先绑定副本数据库，再导入应用模块。"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

from evals.dialogue_loop.cli import parser, run_parent
from evals.dialogue_loop.report import sanitize


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(sanitize(value), ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def main() -> int:
    args = parser().parse_args()
    if args.internal_preflight or args.internal_arm:
        if not args.db or not args.original or not args.result:
            raise ValueError("内部隔离进程缺少路径参数")
        # 必须发生在任何 app 数据库模块导入之前。
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{args.db.resolve()}"
        for key in (
            "PROCESSING_WORKER_ENABLED",
            "CONTEXT_WORKER_ENABLED",
            "DIRECTORY_DRAFT_WORKER_ENABLED",
            "EMBEDDING_WORKER_ENABLED",
            "KNOWLEDGE_AGENT_WORKER_ENABLED",
        ):
            os.environ[key] = "false"
        password = (
            getpass.getpass("demo 密码：")
            if sys.stdin.isatty()
            else sys.stdin.readline().rstrip("\n")
        )
        from evals.dialogue_loop.execution import child_preflight, child_rehearsal, child_run

        if args.internal_preflight:
            value = asyncio.run(child_preflight(args.db, args.original, password))
        elif args.rehearsal:
            value = asyncio.run(
                child_rehearsal(
                    args.db,
                    args.original,
                    password,
                    args.internal_arm,
                    args.scenario,
                    args.text_used,
                    args.embedding_used,
                    args.result,
                )
            )
        else:
            value = asyncio.run(
                child_run(
                    args.db,
                    args.original,
                    password,
                    args.internal_arm,
                    args.scenario,
                    args.text_used,
                    args.embedding_used,
                    args.result,
                )
            )
        _write(args.result, value)
        return 0
    if not args.preflight and not args.rehearsal and not args.compare:
        args.preflight = True
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
