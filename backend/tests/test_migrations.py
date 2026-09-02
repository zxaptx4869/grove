"""当前结构化查询 change 的迁移往返与双方言列类型验证。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.models import KnowledgeAgentRun


def test_structured_query_plan_migration_upgrade_downgrade_upgrade(
    tmp_path: Path,
) -> None:
    """SQLite 全新库往返迁移，可空计划列只由当前 revision 增删。"""
    db_path = tmp_path / "structured-query-roundtrip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]

    def _alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def _plan_column() -> tuple | None:
        with sqlite3.connect(db_path) as connection:
            return next(
                (
                    row
                    for row in connection.execute(
                        "PRAGMA table_info(knowledge_agent_runs)"
                    )
                    if row[1] == "structured_query_plan_json"
                ),
                None,
            )

    _alembic("upgrade", "head")
    first = _plan_column()
    assert first is not None
    assert first[2].upper() == "TEXT"
    assert first[3] == 0

    _alembic("downgrade", "d8e9f0a1b2c3")
    assert _plan_column() is None

    _alembic("upgrade", "head")
    restored = _plan_column()
    assert restored is not None
    assert restored[2].upper() == "TEXT"
    assert restored[3] == 0


def test_structured_query_plan_migration_mysql8_uses_nullable_text() -> None:
    """MySQL 8 ORM DDL 保持普通可空 TEXT，不依赖 SQLite 专属类型。"""
    ddl = str(CreateTable(KnowledgeAgentRun.__table__).compile(dialect=mysql.dialect()))
    normalized = " ".join(ddl.lower().split())

    assert "structured_query_plan_json text" in normalized
    assert "structured_query_plan_json text not null" not in normalized
