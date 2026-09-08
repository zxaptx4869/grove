"""隔离子进程入口；环境绑定完成后才导入应用数据库模块。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import uvicorn


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(add_help=False)
    value.add_argument("--db", type=Path, required=True)
    value.add_argument("--original", type=Path, required=True)
    value.add_argument("--storage", type=Path, required=True)
    value.add_argument("--static", type=Path, required=True)
    value.add_argument("--port", type=int, required=True)
    value.add_argument("--offline", action="store_true")
    return value


async def build_runtime(args, password: str):
    from evals.dialogue_loop.execution import (
        _registry_preflight,
        _v2_control_preflight,
        authenticate_demo,
        secret_preflight,
    )
    from evals.dialogue_loop.isolation import assert_isolated, domain_fingerprint
    from evals.dialogue_workbench.engine import UnifiedLoopEngine
    from evals.dialogue_workbench.runtime import OfflineFixtureEngine, WorkbenchRuntime
    from evals.dialogue_workbench.store import WorkbenchStore

    assert_isolated(args.db, args.original)
    identity = await authenticate_demo(password)
    secrets = await secret_preflight(identity["workspace_id"])
    registry = _registry_preflight()
    controls = _v2_control_preflight()
    if not args.offline and (
        not secrets["text_secret_available"] or not registry["ok"] or not all(controls.values())
    ):
        raise RuntimeError("真实 Provider、只读工具或统一循环控制预检失败")
    original_before = domain_fingerprint(args.original, identity["workspace_id"])
    snapshot = domain_fingerprint(args.db, identity["workspace_id"])
    snapshot_raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    engine = OfflineFixtureEngine() if args.offline else await UnifiedLoopEngine.create(identity)

    async def isolation_unchanged() -> bool:
        """在线程中执行同步 SQLite 指纹，避免锁等待阻塞异步连接清理。"""

        original_after, snapshot_after = await asyncio.gather(
            asyncio.to_thread(_fingerprint_with_retry, args.original, identity["workspace_id"]),
            asyncio.to_thread(_fingerprint_with_retry, args.db, identity["workspace_id"]),
        )
        return original_after == original_before and snapshot_after == snapshot

    return WorkbenchRuntime(
        engine=engine,
        store=WorkbenchStore(args.storage),
        snapshot_at=datetime.now(UTC).isoformat(),
        snapshot_fingerprint=hashlib.sha256(snapshot_raw).hexdigest()[:12],
        isolation_unchanged=isolation_unchanged,
    )


def _fingerprint_with_retry(path: Path, workspace_id: int) -> dict:
    """隔离检查遇到短暂 SQLite 锁时重试，其他异常继续上抛。"""

    from evals.dialogue_loop.isolation import domain_fingerprint

    for attempt in range(4):
        try:
            return domain_fingerprint(path, workspace_id)
        except sqlite3.OperationalError as exc:
            message = str(exc).casefold()
            if (
                "database is locked" not in message
                and "database table is locked" not in message
            ) or attempt >= 3:
                raise
            time_to_wait = 0.08 * (2**attempt)
            time.sleep(time_to_wait)
    raise RuntimeError("隔离指纹重试未返回")


def main() -> int:
    args = parser().parse_args()
    password = sys.stdin.readline().rstrip("\n")
    if not password:
        raise RuntimeError("隔离服务没有收到 demo 密码")
    runtime = asyncio.run(build_runtime(args, password))
    from evals.dialogue_workbench.server import create_app

    app = create_app(runtime, args.static)
    print(f"记录：{runtime.store.path}", flush=True)
    print(f"地址：http://127.0.0.1:{args.port}/workbench", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
