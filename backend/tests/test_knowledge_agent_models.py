"""知识 Agent 数据模型、枚举与迁移约束测试。"""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeMessage,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    RUN_ACTIVE_STATUSES,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)


async def _user_and_workspace(db, prefix: str = "模型") -> tuple[User, Workspace]:
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
        title="模型测试对话",
    )
    db.add(conversation)
    await db.flush()
    return conversation


def test_run_status_contract() -> None:
    """Run 状态集合与合法路径关系保持稳定。"""
    assert RUN_ACTIVE_STATUSES == {RUN_WAITING, RUN_PROCESSING}
    assert RUN_TERMINAL_STATUSES == {RUN_COMPLETED, RUN_FAILED, "partial", "cancelled"}
    assert RUN_ACTIVE_STATUSES.isdisjoint(RUN_TERMINAL_STATUSES)


@pytest.mark.asyncio
async def test_message_client_id_idempotency_key() -> None:
    """同一对话重复 client_message_id 触发唯一约束，不同对话互不影响。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)

        for conversation in (first, second):
            db.add(
                KnowledgeMessage(
                    conversation_id=conversation.id,
                    role="user",
                    message_type="user",
                    content="问题",
                    client_message_id="client-1",
                    scope_type=SCOPE_WORKSPACE,
                )
            )
        await db.flush()

        db.add(
            KnowledgeMessage(
                conversation_id=first.id,
                role="user",
                message_type="user",
                content="重试问题",
                client_message_id="client-1",
                scope_type=SCOPE_WORKSPACE,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_active_slot_unique_and_terminal_null() -> None:
    """同一对话只有一个活动槽；终态 active_slot 置空后允许多个终态 Run。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)

        def _run(status: str, active_slot: str | None) -> KnowledgeAgentRun:
            return KnowledgeAgentRun(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                status=status,
                active_slot=active_slot,
                max_retries=1,
            )

        db.add(_run(RUN_WAITING, ACTIVE_SLOT))
        await db.flush()
        db.add(_run(RUN_WAITING, ACTIVE_SLOT))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 冲突 flush 已回滚；终态置空后允许同一对话出现多个终态 Run
        db.add(_run(RUN_COMPLETED, None))
        await db.flush()
        db.add(_run(RUN_FAILED, None))
        await db.flush()
        rows = (
            await db.execute(
                select(KnowledgeAgentRun).where(
                    KnowledgeAgentRun.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(row.active_slot is None for row in rows)


@pytest.mark.asyncio
async def test_evidence_handle_unique() -> None:
    """Evidence 句柄全局唯一，防止句柄复用。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot=ACTIVE_SLOT,
            max_retries=1,
        )
        db.add(run)
        await db.flush()

        def _evidence(handle: str) -> KnowledgeAgentEvidence:
            return KnowledgeAgentEvidence(
                run_id=run.id,
                handle=handle,
                quote="原文",
                content_fingerprint="fp",
                purpose="answer",
            )

        db.add(_evidence("ev_abc"))
        await db.flush()
        db.add(_evidence("ev_abc"))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


def test_migration_upgrade_and_constraints(tmp_path: Path) -> None:
    """迁移链可完整升级，且唯一约束在迁移后的库上生效。"""
    db_path = tmp_path / "migration_test.db"
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
        assert {"knowledge_conversations", "knowledge_messages", "knowledge_agent_runs"} <= tables
        assert {"knowledge_agent_tool_calls", "knowledge_agent_model_invocations"} <= tables
        assert "knowledge_agent_evidences" in tables

        now = "2026-08-28 00:00:00"
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
            "INSERT INTO knowledge_conversations "
            "(id, workspace_id, owner_user_id, scope_type, project_id, title) "
            "VALUES (1, 1, 1, 'workspace', NULL, '迁移对话')"
        )

        def _insert_run(run_id: int, status: str, active_slot: str | None) -> None:
            conn.execute(
                "INSERT INTO knowledge_agent_runs "
                "(id, conversation_id, workspace_id, owner_user_id, scope_type, status, "
                " active_slot, retry_count, max_retries) "
                "VALUES (?, 1, 1, 1, 'workspace', ?, ?, 0, 1)",
                (run_id, status, active_slot),
            )

        _insert_run(1, "waiting", "active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(2, "waiting", "active")
        conn.execute(
            "UPDATE knowledge_agent_runs SET status='completed', active_slot=NULL WHERE id=1"
        )
        _insert_run(2, "completed", None)
        _insert_run(3, "failed", None)

        conn.execute(
            "INSERT INTO knowledge_messages "
            "(id, conversation_id, role, message_type, content, client_message_id, scope_type) "
            "VALUES (1, 1, 'user', 'user', '问题', 'client-1', 'workspace')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_messages "
                "(id, conversation_id, role, message_type, content, client_message_id, scope_type) "
                "VALUES (2, 1, 'user', 'user', '重试', 'client-1', 'workspace')"
            )
        conn.commit()
    finally:
        conn.close()
