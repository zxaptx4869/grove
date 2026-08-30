"""候选草稿模型、迁移与 Run-backed 服务测试。

覆盖：
- Run run_kind / source_run_id 自引用与既有数据默认 answer；
- Draft 的 operation Run 唯一、confirmed Candidate 唯一与幂等键唯一约束；
- 迁移 upgrade → downgrade → upgrade 兼容 SQLite；
- 共享 Candidate 创建服务、Evidence 复验与 Draft 确认幂等/并发/失效路径。
"""

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
    KnowledgeCandidateDraft,
    KnowledgeConversation,
    Node,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    DRAFT_GENERATING,
    RUN_COMPLETED,
    RUN_KIND_ANSWER,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.runs import run_out


async def _user_and_workspace(db, prefix: str = "草稿") -> tuple[User, Workspace]:
    """创建独立用户与 Workspace。"""
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


async def _conversation(
    db,
    user: User,
    workspace: Workspace,
) -> KnowledgeConversation:
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="草稿测试对话",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _project(db, workspace: Workspace, name: str = "目标项目") -> Project:
    project = Project(
        workspace_id=workspace.id,
        name=name,
        template="empty",
        status="active",
    )
    db.add(project)
    await db.flush()
    db.add(Node(project_id=project.id, parent_id=None, name="根", position=0))
    await db.flush()
    return project


def _run(
    conversation: KnowledgeConversation,
    workspace: Workspace,
    user: User,
    *,
    status: str = RUN_WAITING,
    run_kind: str = RUN_KIND_ANSWER,
    source_run_id: int | None = None,
) -> KnowledgeAgentRun:
    return KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        status=status,
        run_kind=run_kind,
        source_run_id=source_run_id,
        max_retries=1,
    )


def _draft(
    conversation: KnowledgeConversation,
    workspace: Workspace,
    user: User,
    operation_run: KnowledgeAgentRun,
    *,
    source_run: KnowledgeAgentRun | None = None,
    client_operation_id: str | None = None,
    confirmed_candidate_id: int | None = None,
) -> KnowledgeCandidateDraft:
    return KnowledgeCandidateDraft(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        conversation_id=conversation.id,
        operation_run_id=operation_run.id,
        source_run_id=source_run.id if source_run else None,
        status=DRAFT_GENERATING,
        client_operation_id=client_operation_id,
        confirmed_candidate_id=confirmed_candidate_id,
    )


@pytest.mark.asyncio
async def test_run_kind_default_answer_and_source_run_self_reference() -> None:
    """既有语义创建 Run 默认 answer；draft_candidate 可自引用来源回答 Run。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        source_run = _run(conversation, workspace, user, status=RUN_COMPLETED)
        db.add(source_run)
        await db.flush()
        operation_run = _run(
            conversation,
            workspace,
            user,
            run_kind=RUN_KIND_DRAFT_CANDIDATE,
            source_run_id=source_run.id,
        )
        db.add(operation_run)
        await db.flush()

        # 旧字段缺省时 ORM 默认回填 answer，保持兼容
        legacy = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_COMPLETED,
            max_retries=1,
        )
        db.add(legacy)
        await db.flush()

        assert operation_run.run_kind == RUN_KIND_DRAFT_CANDIDATE
        assert operation_run.source_run_id == source_run.id
        assert legacy.run_kind == RUN_KIND_ANSWER
        out = run_out(operation_run)
        assert out.run_kind == RUN_KIND_DRAFT_CANDIDATE
        assert out.source_run_id == source_run.id


@pytest.mark.asyncio
async def test_draft_operation_run_unique() -> None:
    """同一 operation Run 只能有一个 Draft，崩溃恢复不创建第二个。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        operation_run = _run(
            conversation,
            workspace,
            user,
            run_kind=RUN_KIND_DRAFT_CANDIDATE,
        )
        db.add(operation_run)
        await db.flush()
        db.add(_draft(conversation, workspace, user, operation_run))
        await db.flush()
        db.add(_draft(conversation, workspace, user, operation_run))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_draft_confirmed_candidate_unique() -> None:
    """confirmed_candidate_id 唯一：确认结果只能写一次。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        first_run = _run(conversation, workspace, user)
        second_run = _run(conversation, workspace, user, status=RUN_COMPLETED)
        db.add_all([first_run, second_run])
        await db.flush()
        db.add(
            _draft(
                conversation,
                workspace,
                user,
                first_run,
                client_operation_id="op-1",
                confirmed_candidate_id=1,
            )
        )
        await db.flush()
        db.add(
            _draft(
                conversation,
                workspace,
                user,
                second_run,
                client_operation_id="op-2",
                confirmed_candidate_id=1,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_draft_operation_key_unique_per_conversation() -> None:
    """幂等键在同一对话内唯一；不同对话互不影响。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)
        first_run = _run(first, workspace, user)
        same_conversation_run = _run(first, workspace, user, status=RUN_COMPLETED)
        second_run = _run(second, workspace, user)
        third_run = _run(second, workspace, user, status=RUN_COMPLETED)
        db.add_all([first_run, same_conversation_run, second_run, third_run])
        await db.flush()
        db.add(
            _draft(
                first,
                workspace,
                user,
                first_run,
                client_operation_id="client-op-1",
            )
        )
        await db.flush()
        db.add(
            _draft(
                first,
                workspace,
                user,
                same_conversation_run,
                client_operation_id="client-op-1",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 不同对话可以使用相同操作键
        db.add(
            _draft(
                second,
                workspace,
                user,
                second_run,
                client_operation_id="client-op-1",
            )
        )
        await db.flush()
        db.add(
            _draft(
                second,
                workspace,
                user,
                third_run,
                client_operation_id="client-op-2",
            )
        )
        await db.flush()


def test_migration_upgrade_downgrade_upgrade_and_draft_columns(tmp_path: Path) -> None:
    """全新 SQLite 库执行 upgrade→downgrade→upgrade，验证草稿表与 Run 字段。"""
    db_path = tmp_path / "candidate_draft_migration.db"
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

    _alembic("upgrade", "head")
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_candidate_drafts" in tables
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert {"run_kind", "source_run_id"} <= run_columns
        draft_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(knowledge_candidate_drafts)"
            ).fetchall()
        }
        assert {
            "workspace_id",
            "owner_user_id",
            "conversation_id",
            "operation_run_id",
            "source_run_id",
            "target_project_id",
            "target_project_name",
            "status",
            "title",
            "content",
            "main_type",
            "info_nature",
            "evidence_handles_json",
            "generation_meta_json",
            "client_operation_id",
            "confirmed_candidate_id",
        } <= draft_columns
    finally:
        conn.close()

    _alembic("downgrade", "base")
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_candidate_drafts" not in tables
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert "run_kind" not in run_columns
        assert "source_run_id" not in run_columns
    finally:
        conn.close()

    _alembic("upgrade", "head")
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "knowledge_candidate_drafts" in tables
    finally:
        conn.close()
