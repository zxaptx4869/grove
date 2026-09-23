"""当前结构化查询 change 的迁移往返与双方言列类型验证。"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models import KnowledgeAgentRun, Source


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
                    for row in connection.execute("PRAGMA table_info(knowledge_agent_runs)")
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


def test_composite_answer_migration_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    """SQLite 全新库往返迁移，三个复合快照列均为可空 TEXT。"""
    db_path = tmp_path / "composite-answer-roundtrip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]
    column_names = {
        "composite_answer_plan_json",
        "composite_answer_execution_json",
        "composite_answer_coverage_json",
    }

    def _alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def _columns() -> dict[str, tuple]:
        with sqlite3.connect(db_path) as connection:
            return {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(knowledge_agent_runs)")
                if row[1] in column_names
            }

    _alembic("upgrade", "head")
    first = _columns()
    assert set(first) == column_names
    assert all(row[2].upper() == "TEXT" and row[3] == 0 for row in first.values())

    _alembic("downgrade", "e9f0a1b2c3d4")
    assert _columns() == {}

    _alembic("upgrade", "head")
    restored = _columns()
    assert set(restored) == column_names
    assert all(row[2].upper() == "TEXT" and row[3] == 0 for row in restored.values())


def test_composite_answer_migration_mysql8_uses_nullable_text() -> None:
    """MySQL 8 ORM DDL 使用普通可空 TEXT，不依赖 SQLite 专属类型。"""
    ddl = str(CreateTable(KnowledgeAgentRun.__table__).compile(dialect=mysql.dialect()))
    normalized = " ".join(ddl.lower().split())

    for column in (
        "composite_answer_plan_json",
        "composite_answer_execution_json",
        "composite_answer_coverage_json",
    ):
        assert f"{column} text" in normalized
        assert f"{column} text not null" not in normalized


def test_shared_execution_graph_migration_upgrade_downgrade_upgrade(
    tmp_path: Path,
) -> None:
    """图与检查点列仅追加到新 Run，SQLite 往返不回填历史数据。"""
    db_path = tmp_path / "shared-execution-graph-roundtrip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]
    column_names = {"shared_execution_graph_json", "shared_execution_state_json"}

    def _alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def _columns() -> dict[str, tuple]:
        with sqlite3.connect(db_path) as connection:
            return {
                row[1]: row
                for row in connection.execute("PRAGMA table_info(knowledge_agent_runs)")
                if row[1] in column_names
            }

    _alembic("upgrade", "head")
    assert set(_columns()) == column_names
    _alembic("downgrade", "fa1b2c3d4e5f")
    assert _columns() == {}
    _alembic("upgrade", "head")
    assert set(_columns()) == column_names


def test_shared_execution_graph_migration_mysql8_uses_nullable_text() -> None:
    """MySQL 8 DDL 保持普通可空 TEXT，避免方言专属 JSON 类型。"""
    ddl = str(CreateTable(KnowledgeAgentRun.__table__).compile(dialect=mysql.dialect()))
    normalized = " ".join(ddl.lower().split())

    for column in ("shared_execution_graph_json", "shared_execution_state_json"):
        assert f"{column} text" in normalized
        assert f"{column} text not null" not in normalized


def test_capture_key_migration_roundtrip_and_unique_index(tmp_path: Path) -> None:
    """SQLite 全新库往返迁移，新增可空列与 Workspace 内唯一索引。"""
    db_path = tmp_path / "capture-key-roundtrip.db"
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

    def _capture_key_column() -> tuple | None:
        with sqlite3.connect(db_path) as connection:
            return next(
                (
                    row
                    for row in connection.execute("PRAGMA table_info(sources)")
                    if row[1] == "capture_key"
                ),
                None,
            )

    def _unique_index() -> tuple | None:
        with sqlite3.connect(db_path) as connection:
            return next(
                (
                    row
                    for row in connection.execute("PRAGMA index_list(sources)")
                    if row[1] == "uq_sources_workspace_capture_key"
                ),
                None,
            )

    _alembic("upgrade", "head")
    column = _capture_key_column()
    assert column is not None
    assert column[2].upper() == "VARCHAR(128)"
    assert column[3] == 0
    index = _unique_index()
    assert index is not None
    assert index[2] == 1

    _alembic("downgrade", "fe5f6a7b8c9d")
    assert _capture_key_column() is None
    assert _unique_index() is None

    _alembic("upgrade", "head")
    assert _capture_key_column() is not None
    assert _unique_index() is not None


def test_capture_key_mysql8_ddl_keeps_nullable_column_and_unique_index() -> None:
    """MySQL 8 DDL 保持可空 VARCHAR(128) 与唯一索引，不依赖方言专属类型。"""
    ddl = str(CreateTable(Source.__table__).compile(dialect=mysql.dialect()))
    normalized = " ".join(ddl.lower().split())
    assert "capture_key varchar(128)" in normalized
    assert "capture_key varchar(128) not null" not in normalized

    index = next(
        item
        for item in Source.__table__.indexes
        if item.name == "uq_sources_workspace_capture_key"
    )
    index_ddl = " ".join(
        str(CreateIndex(index).compile(dialect=mysql.dialect())).lower().split()
    )
    assert index_ddl.startswith("create unique index")
    assert "(workspace_id, capture_key)" in index_ddl
