"""父进程启动器：创建隔离副本并托管本地工作台子进程。"""

from __future__ import annotations

import argparse
import atexit
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from evals.dialogue_loop.cli import _source_database
from evals.dialogue_loop.credentials import password_for_run
from evals.dialogue_loop.isolation import backup_database, domain_fingerprint, identity_snapshot


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Grove 知识 Agent 本地实验工作台")
    value.add_argument("--port", type=int, default=8765)
    value.add_argument("--offline", action="store_true", help="仅用于自动化的明确离线桩")
    value.add_argument("--pid-file", type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError("端口必须位于 1024 到 65535")
    if args.pid_file is not None:
        args.pid_file.write_text(str(os.getpid()), encoding="ascii")
        args.pid_file.chmod(0o600)
        atexit.register(args.pid_file.unlink, missing_ok=True)
    repo_root = Path(__file__).resolve().parents[3]
    backend_dir = repo_root / "backend"
    static_dir = repo_root / "frontend" / "dist"
    if not (static_dir / "workbench.html").is_file():
        raise RuntimeError("缺少前端构建产物，请先运行工作台启动脚本")
    original = _source_database(backend_dir)
    identity = identity_snapshot(original)
    password, from_keychain, error = password_for_run(
        identity["workspace_id"], prompt=__import__("getpass").getpass
    )
    if error:
        print(f"{error}，已回退到隐藏输入。", file=sys.stderr)
    elif from_keychain:
        print("已从系统钥匙串读取 demo 密码。")
    before = domain_fingerprint(original, identity["workspace_id"])
    storage = backend_dir / "data" / "knowledge-agent-evals" / "dialogue-workbench"
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="grove-dialogue-workbench-") as temp_name:
        copy_db = Path(temp_name) / "workbench.db"
        backup_database(original, copy_db)
        command = [
            sys.executable,
            "-m",
            "evals.dialogue_workbench._serve",
            "--db",
            str(copy_db),
            "--original",
            str(original),
            "--storage",
            str(storage),
            "--static",
            str(static_dir),
            "--port",
            str(args.port),
        ]
        if args.offline:
            command.append("--offline")
        env = __import__("os").environ.copy()
        env.update(
            {
                "DATABASE_URL": f"sqlite+aiosqlite:///{copy_db.resolve()}",
                "PROCESSING_WORKER_ENABLED": "false",
                "CONTEXT_WORKER_ENABLED": "false",
                "DIRECTORY_DRAFT_WORKER_ENABLED": "false",
                "EMBEDDING_WORKER_ENABLED": "false",
                "KNOWLEDGE_AGENT_WORKER_ENABLED": "false",
            }
        )
        process = subprocess.Popen(
            command, cwd=backend_dir, env=env, stdin=subprocess.PIPE, text=True
        )
        assert process.stdin is not None
        process.stdin.write(password + "\n")
        process.stdin.close()
        previous_handler = signal.getsignal(signal.SIGTERM)

        def terminate_child(_signum, _frame) -> None:
            if process.poll() is None:
                process.terminate()

        signal.signal(signal.SIGTERM, terminate_child)
        try:
            return_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            return_code = process.wait(timeout=10)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
    after = domain_fingerprint(original, identity["workspace_id"])
    if before != after:
        raise RuntimeError("原业务库指纹发生变化")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
