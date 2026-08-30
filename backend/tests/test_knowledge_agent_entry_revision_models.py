"""知识 Agent 单 Entry 修订模型与迁移约束测试。"""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeEntryRevisionDraft,
    KnowledgeEntryRevisionExecution,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    REVISION_DRAFT_APPLIED,
    REVISION_DRAFT_DRAFT,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_GENERATING,
    REVISION_DRAFT_STATUSES,
    REVISION_DRAFT_TERMINAL_STATUSES,
    REVISION_EXECUTION_APPLIED,
    RUN_COMPLETED,
    RUN_KIND_ENTRY_REVISION,
    RUN_PROCESSING,
    SCOPE_WORKSPACE,
)


async def _user_and_workspace(db, prefix: str = "修订模型") -> tuple[User, Workspace]:
    """创建独立用户与 Workspace，避免测试间数据干扰。"""
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    user = User(username=username, password_hash="x")
    db.add(user)
    await db.flush()
    workspace = Workspace(name=f"{username} 的空间")
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await db.flush()
    return user, workspace


async def _conversation(db, user: User, workspace: Workspace) -> KnowledgeConversation:
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="修订测试对话",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _run(
    db,
    conversation: KnowledgeConversation,
    *,
    run_kind: str = RUN_KIND_ENTRY_REVISION,
    status: str = RUN_PROCESSING,
    target_entry_id: int | None = None,
) -> KnowledgeAgentRun:
    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        run_kind=run_kind,
        scope_type=SCOPE_WORKSPACE,
        status=status,
        active_slot=None if status == RUN_COMPLETED else "active",
        max_retries=1,
        target_entry_id=target_entry_id,
    )
    db.add(run)
    await db.flush()
    return run


def _draft(
    *,
    workspace_id: int,
    owner_user_id: int,
    conversation_id: int,
    operation_run: KnowledgeAgentRun,
    client_operation_id: str | None = None,
    status: str = REVISION_DRAFT_GENERATING,
    target_entry_id: int | None = None,
) -> KnowledgeEntryRevisionDraft:
    return KnowledgeEntryRevisionDraft(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        operation_run_id=operation_run.id,
        source_run_id=None,
        target_entry_id=target_entry_id,
        target_project_id=None,
        instruction="补充闭水试验适用条件",
        base_entry_json='{"title":"旧标题"}',
        base_entry_fingerprint="fp-base",
        status=status,
        client_operation_id=client_operation_id,
    )


def _execution(
    *,
    workspace_id: int,
    owner_user_id: int,
    conversation_id: int,
    draft_id: int,
    client_operation_id: str,
    undo_client_operation_id: str | None = None,
    status: str = REVISION_EXECUTION_APPLIED,
) -> KnowledgeEntryRevisionExecution:
    return KnowledgeEntryRevisionExecution(
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation_id,
        draft_id=draft_id,
        entry_id=None,
        client_operation_id=client_operation_id,
        before_entry_json='{"title":"旧标题"}',
        after_entry_json='{"title":"新标题"}',
        before_fingerprint="fp-before",
        after_fingerprint="fp-after",
        status=status,
        undo_client_operation_id=undo_client_operation_id,
    )


def test_revision_draft_status_contract() -> None:
    """修订草稿状态枚举与终态集合稳定。"""
    assert REVISION_DRAFT_STATUSES == (
        REVISION_DRAFT_GENERATING,
        "draft",
        "confirming",
        REVISION_DRAFT_APPLIED,
        "cancelled",
        REVISION_DRAFT_FAILED,
        "undone",
    )
    assert REVISION_DRAFT_TERMINAL_STATUSES == {
        REVISION_DRAFT_APPLIED,
        "cancelled",
        REVISION_DRAFT_FAILED,
        "undone",
    }
    assert REVISION_DRAFT_DRAFT not in REVISION_DRAFT_TERMINAL_STATUSES


def test_run_kind_contract() -> None:
    """entry_revision Run 类型已注册且与既有类型兼容。"""
    assert RUN_KIND_ENTRY_REVISION == "entry_revision"
    assert KnowledgeAgentRun.__table__.c.run_kind.default.arg == "answer"


@pytest.mark.asyncio
async def test_revision_draft_operation_run_unique() -> None:
    """一个操作 Run 至多一个修订草稿。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = await _run(db, conversation)

        db.add(
            _draft(
                workspace_id=conversation.workspace_id,
                owner_user_id=conversation.owner_user_id,
                conversation_id=conversation.id,
                operation_run=run,
            )
        )
        await db.flush()
        db.add(
            _draft(
                workspace_id=conversation.workspace_id,
                owner_user_id=conversation.owner_user_id,
                conversation_id=conversation.id,
                operation_run=run,
                client_operation_id="op-2",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_revision_draft_operation_key_unique_per_conversation() -> None:
    """同一对话内确认幂等键唯一；不同对话互不影响。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)
        run_a = await _run(db, first)
        run_b = await _run(db, second)

        db.add(
            _draft(
                workspace_id=first.workspace_id,
                owner_user_id=first.owner_user_id,
                conversation_id=first.id,
                operation_run=run_a,
                client_operation_id="confirm-1",
            )
        )
        await db.flush()
        db.add(
            _draft(
                workspace_id=first.workspace_id,
                owner_user_id=first.owner_user_id,
                conversation_id=first.id,
                operation_run=run_b,
                client_operation_id="confirm-1",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        db.add(
            _draft(
                workspace_id=second.workspace_id,
                owner_user_id=second.owner_user_id,
                conversation_id=second.id,
                operation_run=run_b,
                client_operation_id="confirm-1",
            )
        )
        await db.flush()


@pytest.mark.asyncio
async def test_execution_draft_unique_and_idempotency_keys() -> None:
    """Execution 的 draft、确认键与撤销键唯一约束生效。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = await _run(db, conversation)
        workspace_id = conversation.workspace_id
        owner_user_id = conversation.owner_user_id
        conversation_id = conversation.id
        draft_id: int | None = None
        other_draft_id: int | None = None
        draft = _draft(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            operation_run=run,
            client_operation_id="confirm-1",
        )
        db.add(draft)
        await db.flush()
        draft_id = draft.id
        await db.commit()

        db.add(
            _execution(
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                draft_id=draft_id,
                client_operation_id="confirm-1",
                undo_client_operation_id="undo-1",
            )
        )
        await db.flush()
        await db.commit()

        # 同一 draft 不能有第二条 Execution
        run.status = RUN_COMPLETED
        run.active_slot = None
        await db.flush()
        await db.commit()
        other_run = await _run(db, conversation)
        other_draft = _draft(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            operation_run=other_run,
            client_operation_id="confirm-2",
            status=REVISION_DRAFT_DRAFT,
        )
        db.add(other_draft)
        await db.flush()
        other_draft_id = other_draft.id
        await db.commit()
        db.add(
            _execution(
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                draft_id=other_draft_id,
                client_operation_id="confirm-2",
            )
        )
        await db.flush()
        await db.commit()
        # 同一 draft 第二条 Execution（唯一约束）
        db.add(
            _execution(
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                draft_id=draft_id,
                client_operation_id="confirm-1",
                undo_client_operation_id="undo-2",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 同一对话重复确认键
        db.add(
            _execution(
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                draft_id=other_draft_id,
                client_operation_id="confirm-1",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 同一对话重复撤销键
        db.add(
            _execution(
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                draft_id=other_draft_id,
                client_operation_id="confirm-3",
                undo_client_operation_id="undo-1",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_run_target_entry_id_and_kind_compatible() -> None:
    """entry_revision Run 固化 target_entry_id；既有 Run 默认 answer 且无目标。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        revision_run = await _run(db, conversation, target_entry_id=1)
        answer_run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_COMPLETED,
            active_slot=None,
            max_retries=1,
        )
        db.add(answer_run)
        await db.flush()
        assert revision_run.run_kind == RUN_KIND_ENTRY_REVISION
        assert revision_run.target_entry_id == 1
        assert answer_run.run_kind == "answer"
        assert answer_run.target_entry_id is None


def test_migration_upgrade_creates_revision_tables(tmp_path: Path) -> None:
    """迁移链创建修订表、约束，并保留既有 Run 数据。"""
    db_path = tmp_path / "revision_migration.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_entry_revision_drafts" in tables
        assert "knowledge_entry_revision_executions" in tables
        # 外键定义存在（SQLite 默认不强制，MySQL 8 默认强制；schema 语义一致）
        draft_fks = {
            row[2]
            for row in conn.execute(
                "PRAGMA foreign_key_list(knowledge_entry_revision_drafts)"
            ).fetchall()
        }
        assert "knowledge_agent_runs" in draft_fks
        assert "entries" in draft_fks
        assert "knowledge_entry_revision_executions" in draft_fks
        execution_fks = {
            row[2]
            for row in conn.execute(
                "PRAGMA foreign_key_list(knowledge_entry_revision_executions)"
            ).fetchall()
        }
        assert "knowledge_entry_revision_drafts" in execution_fks
        assert "entries" in execution_fks

        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(knowledge_agent_runs)"
            ).fetchall()
        }
        assert "target_entry_id" in columns
        assert "run_kind" in columns

        now = "2026-08-30 00:00:00"
        conn.execute(
            "INSERT INTO workspaces (id, name, created_at) VALUES (1, '迁移空间', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at) "
            "VALUES (1, 'migration_user', 'x', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO projects (id, workspace_id, name, template, status, created_at) "
            "VALUES (1, 1, '迁移项目', 'empty', 'active', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO nodes (id, project_id, name, position, created_at) "
            "VALUES (1, 1, '施工', 0, ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO entries "
            "(id, project_id, node_id, title, content, main_type, created_at) "
            "VALUES (1, 1, 1, '闭水试验', '内容', 'method', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO knowledge_conversations "
            "(id, workspace_id, owner_user_id, scope_type, project_id, title) "
            "VALUES (1, 1, 1, 'project', 1, '迁移对话')"
        )
        # 既有 Run 保留默认 answer 语义，target_entry_id 为 NULL
        conn.execute(
            "INSERT INTO knowledge_agent_runs "
            "(id, conversation_id, workspace_id, owner_user_id, run_kind, scope_type, "
            " project_id, status, active_slot, retry_count, max_retries, target_entry_id) "
            "VALUES (1, 1, 1, 1, 'answer', 'project', 1, 'completed', NULL, 0, 1, NULL)"
        )

        conn.execute(
            "INSERT INTO knowledge_entry_revision_drafts "
            "(id, workspace_id, owner_user_id, conversation_id, operation_run_id, "
            " source_run_id, target_entry_id, target_project_id, instruction, "
            " base_entry_json, base_entry_fingerprint, status, client_operation_id) "
            "VALUES (1, 1, 1, 1, 1, 1, 1, 1, '补充适用条件', "
            " '{\"title\":\"闭水试验\"}', 'fp', 'generating', NULL)"
        )
        conn.execute(
            "INSERT INTO knowledge_entry_revision_executions "
            "(id, workspace_id, owner_user_id, conversation_id, draft_id, entry_id, "
            " client_operation_id, before_entry_json, after_entry_json, "
            " before_fingerprint, after_fingerprint, status) "
            "VALUES (1, 1, 1, 1, 1, 1, 'confirm-1', "
            " '{\"title\":\"闭水试验\"}', '{\"title\":\"闭水试验新\"}', "
            " 'fp-before', 'fp-after', 'applied')"
        )

        # 唯一约束在迁移后的库上生效
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_entry_revision_executions "
                "(id, workspace_id, owner_user_id, conversation_id, draft_id, entry_id, "
                " client_operation_id, before_entry_json, after_entry_json, "
                " before_fingerprint, after_fingerprint, status) "
                "VALUES (2, 1, 1, 1, 1, 1, 'confirm-2', "
                " '{\"title\":\"闭水试验\"}', '{\"title\":\"闭水试验新\"}', "
                " 'fp-before', 'fp-after', 'applied')"
            )
        conn.commit()
    finally:
        conn.close()


def test_migration_downgrade_then_upgrade(tmp_path: Path) -> None:
    """downgrade→upgrade 往返不丢既有表，修订表可重建。"""
    db_path = tmp_path / "revision_roundtrip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr
    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "-1"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    re_upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
    )
    assert re_upgrade.returncode == 0, re_upgrade.stdout + re_upgrade.stderr

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_entry_revision_drafts" in tables
        assert "knowledge_entry_revision_executions" in tables
        assert "entries" in tables
        assert "knowledge_agent_runs" in tables
    finally:
        conn.close()
