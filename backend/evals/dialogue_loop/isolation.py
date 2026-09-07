"""SQLite 一致快照、身份前提和不可变材料指纹。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path
from urllib.parse import unquote, urlparse

BUSINESS_TABLES = (
    "projects",
    "nodes",
    "sources",
    "attachments",
    "extractions",
    "candidates",
    "entries",
    "entry_versions",
    "entry_source_evidences",
)


def sqlite_path(database_url: str, *, backend_dir: Path) -> Path:
    """只接受本实验能安全复制的 SQLite 配置。"""
    normalized = database_url.replace("sqlite+aiosqlite:", "sqlite:", 1)
    parsed = urlparse(normalized)
    if parsed.scheme != "sqlite":
        raise ValueError("实验只支持 SQLite 开发库一致快照")
    raw = unquote(parsed.path)
    if normalized.startswith("sqlite:///./"):
        return (backend_dir / raw.removeprefix("/./")).resolve()
    if normalized.startswith("sqlite:////"):
        return Path(raw).resolve()
    raise ValueError("无法安全解析 SQLite 数据库路径")


def secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def secure_file(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def backup_database(source: Path, target: Path) -> None:
    """使用 SQLite backup API 获取一致快照。"""
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise ValueError("执行数据库不能等于原业务库")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    target_db = sqlite3.connect(target)
    try:
        source_db.backup(target_db)
    finally:
        target_db.close()
        source_db.close()
    secure_file(target)


def assert_isolated(execution: Path, original: Path) -> None:
    if execution.resolve() == original.resolve():
        raise ValueError("执行数据库不能等于原业务库")
    for key in (
        "PROCESSING_WORKER_ENABLED",
        "CONTEXT_WORKER_ENABLED",
        "DIRECTORY_DRAFT_WORKER_ENABLED",
        "EMBEDDING_WORKER_ENABLED",
        "KNOWLEDGE_AGENT_WORKER_ENABLED",
    ):
        if os.environ.get(key, "").lower() != "false":
            raise ValueError(f"后台任务未隔离：{key}")


def identity_snapshot(path: Path, username: str = "demo") -> dict:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT u.id AS user_id,m.workspace_id,m.role "
            "FROM users u JOIN workspace_members m ON m.user_id=u.id "
            "WHERE u.username=? ORDER BY m.created_at,m.workspace_id",
            (username,),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("demo 账号必须恰好属于一个可验证 Workspace")
        return dict(rows[0])


def provider_snapshot(path: Path, workspace_id: int) -> dict:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT text_provider,text_model,text_available,embedding_provider,"
            "embedding_model,embedding_available FROM ai_provider_settings "
            "WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise ValueError("demo Workspace 缺少模型配置")
        return dict(row)


def domain_fingerprint(
    path: Path, workspace_id: int, *, attachment_root: Path | None = None
) -> dict:
    """业务表与实际附件文件内容均纳入只读指纹。"""
    result: dict[str, object] = {}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        project_sql = "SELECT id FROM projects WHERE workspace_id=?"
        source_sql = "SELECT id FROM sources WHERE workspace_id=?"
        predicates = {
            "projects": ("workspace_id=?", (workspace_id,)),
            "nodes": (f"project_id IN ({project_sql})", (workspace_id,)),
            "sources": ("workspace_id=?", (workspace_id,)),
            "attachments": (f"source_id IN ({source_sql})", (workspace_id,)),
            "extractions": (f"source_id IN ({source_sql})", (workspace_id,)),
            "candidates": (f"source_id IN ({source_sql})", (workspace_id,)),
            "entries": (f"project_id IN ({project_sql})", (workspace_id,)),
            "entry_versions": (
                f"entry_id IN (SELECT id FROM entries WHERE project_id IN ({project_sql}))",
                (workspace_id,),
            ),
            "entry_source_evidences": (
                f"entry_id IN (SELECT id FROM entries WHERE project_id IN ({project_sql}))",
                (workspace_id,),
            ),
        }
        for table in BUSINESS_TABLES:
            predicate, params = predicates[table]
            rows = [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM {table} WHERE {predicate} ORDER BY id", params
                )
            ]
            raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
            result[table] = {"rows": len(rows), "sha256": hashlib.sha256(raw.encode()).hexdigest()}
        files = []
        attachment_rows = db.execute(
            f"SELECT a.id,a.file_path FROM attachments a WHERE a.source_id IN ({source_sql}) "
            "AND a.file_path IS NOT NULL ORDER BY a.id",
            (workspace_id,),
        ).fetchall()
        for row in attachment_rows:
            file_path = Path(row["file_path"])
            if not file_path.is_absolute():
                file_path = (attachment_root or path.parent) / file_path
            if file_path.is_file():
                files.append(
                    {"id": row["id"], "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest()}
                )
            else:
                files.append({"id": row["id"], "missing": True})
        result["attachment_files"] = files
    return result


def oracle_snapshot(path: Path, workspace_id: int) -> dict:
    """独立 SQL 真值，不调用被测聚合或来源服务。"""
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        projects = [
            dict(row)
            for row in db.execute(
                "SELECT p.id,p.name,p.status,COUNT(e.id) AS entry_count "
                "FROM projects p LEFT JOIN entries e ON e.project_id=p.id "
                "WHERE p.workspace_id=? GROUP BY p.id ORDER BY p.id",
                (workspace_id,),
            )
        ]
        entries = [
            dict(row)
            for row in db.execute(
                "SELECT e.id,e.project_id,e.title,e.content,e.updated_at "
                "FROM entries e JOIN projects p ON p.id=e.project_id "
                "WHERE p.workspace_id=? ORDER BY e.updated_at DESC,e.id DESC",
                (workspace_id,),
            )
        ]
        evidence = [
            dict(row)
            for row in db.execute(
                "SELECT ese.entry_id,s.id AS source_id,s.title AS source_title,ese.quote "
                "FROM entry_source_evidences ese JOIN sources s ON s.id=ese.source_id "
                "WHERE s.workspace_id=? ORDER BY ese.entry_id,s.id",
                (workspace_id,),
            )
        ]
    return {"projects": projects, "entries": entries, "evidence": evidence}
