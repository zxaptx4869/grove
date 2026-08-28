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
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeWorkingSetItem,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    CONTEXT_CLOSE_REASON_NEW_TOPIC,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_CLOSED,
    RUN_ACTIVE_STATUSES,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitRequest,
)
from app.services.knowledge_agent.runs import run_out


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


@pytest.mark.asyncio
async def test_context_version_active_slot_unique_and_terminal_null() -> None:
    """同一对话最多一个活动上下文版本；终态置空后允许多个历史版本。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)

        def _version(
            status: str,
            active_slot: str | None,
            version_number: int = 1,
        ) -> KnowledgeContextVersion:
            return KnowledgeContextVersion(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                version_number=version_number,
                scope_type=SCOPE_WORKSPACE,
                topic_label="闭水试验",
                status=status,
                active_slot=active_slot,
            )

        db.add(_version(CONTEXT_STATUS_ACTIVE, ACTIVE_SLOT))
        await db.flush()
        db.add(_version(CONTEXT_STATUS_ACTIVE, ACTIVE_SLOT))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        db.add(_version(CONTEXT_STATUS_CLOSED, None, version_number=1))
        await db.flush()
        db.add(_version(CONTEXT_STATUS_CLOSED, None, version_number=2))
        await db.flush()
        rows = (
            await db.execute(
                select(KnowledgeContextVersion).where(
                    KnowledgeContextVersion.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(row.active_slot is None for row in rows)


@pytest.mark.asyncio
async def test_context_version_number_unique_per_conversation() -> None:
    """同一对话版本号唯一；不同对话允许相同版本号。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)

        def _version(conversation_id: int) -> KnowledgeContextVersion:
            return KnowledgeContextVersion(
                conversation_id=conversation_id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                version_number=1,
                scope_type=SCOPE_WORKSPACE,
                topic_label="主题",
                status=CONTEXT_STATUS_CLOSED,
                close_reason=CONTEXT_CLOSE_REASON_NEW_TOPIC,
                active_slot=None,
            )

        db.add(_version(first.id))
        await db.flush()
        db.add(_version(first.id))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 不同对话可以使用相同版本号
        db.add(_version(first.id))
        await db.flush()
        db.add(_version(second.id))
        await db.flush()


@pytest.mark.asyncio
async def test_working_set_item_unique_per_version() -> None:
    """同一版本内 Entry 线索不重复；entry_id 可空允许多个空版本项。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        version = KnowledgeContextVersion(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            version_number=1,
            scope_type=SCOPE_WORKSPACE,
            topic_label="闭水试验",
            status=CONTEXT_STATUS_ACTIVE,
            active_slot=ACTIVE_SLOT,
        )
        db.add(version)
        await db.flush()

        def _item(entry_id: int | None) -> KnowledgeWorkingSetItem:
            return KnowledgeWorkingSetItem(
                context_version_id=version.id,
                entry_id=entry_id,
                include_reason="cited",
                sort_order=0,
            )

        db.add(_item(100))
        await db.flush()
        db.add(_item(100))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        db.add(_item(None))
        await db.flush()
        db.add(_item(None))
        await db.flush()


@pytest.mark.asyncio
async def test_run_context_fields_and_serialization() -> None:
    """Run 上下文契约字段可空且可序列化；旧 Run 无上下文不报错。"""
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
        await db.commit()

        out = run_out(run)
        assert isinstance(out, KnowledgeRunOut)
        assert out.request_context_mode is None
        assert out.context_decision is None
        assert out.context_degraded is False

        run.request_context_mode = "continue"
        run.context_decision = "continue"
        run.standalone_query = "闭水试验为什么不能提前放水？"
        run.topic_label = "闭水试验"
        run.context_meta_json = (
            '{"provider":"llm","model":"fake","is_fallback":true,"error":"失败"}'
        )
        await db.flush()
        await db.refresh(run)
        out = run_out(run)
        assert out.request_context_mode == "continue"
        assert out.context_decision == "continue"
        assert out.standalone_query == "闭水试验为什么不能提前放水？"
        assert out.topic_label == "闭水试验"
        assert out.context_degraded is True


def test_submit_request_defaults_and_answer_status() -> None:
    """context_mode 默认 auto；回答状态支持 clarification。"""
    request = KnowledgeRunSubmitRequest(client_message_id="x", message="问题")
    assert request.context_mode == "auto"
    assert (
        KnowledgeRunSubmitRequest(
            client_message_id="x", message="问题", context_mode="continue"
        ).context_mode
        == "continue"
    )
    answer = KnowledgeAnswerOut(answer="请补充主题", status="clarification")
    assert answer.status == "clarification"


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
        assert "knowledge_context_versions" in tables
        assert "knowledge_working_set_items" in tables

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

        # 上下文版本单活动约束
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(id, conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, active_slot) "
            "VALUES (1, 1, 1, 1, 1, 'workspace', '闭水试验', 'active', 'active')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_context_versions "
                "(id, conversation_id, workspace_id, owner_user_id, version_number, "
                " scope_type, topic_label, status, active_slot) "
                "VALUES (2, 1, 1, 1, 2, 'workspace', '新话题', 'active', 'active')"
            )
        conn.execute(
            "UPDATE knowledge_context_versions "
            "SET status='closed', active_slot=NULL WHERE id=1"
        )
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(id, conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, active_slot) "
            "VALUES (3, 1, 1, 1, 2, 'workspace', '新话题', 'active', 'active')"
        )

        # 工作集项唯一约束与空主题版本
        conn.execute(
            "INSERT INTO knowledge_working_set_items "
            "(id, context_version_id, entry_id, include_reason, sort_order) "
            "VALUES (1, 3, NULL, 'cited', 0)"
        )
        conn.execute(
            "INSERT INTO knowledge_working_set_items "
            "(id, context_version_id, entry_id, include_reason, sort_order) "
            "VALUES (2, 3, NULL, 'recent', 1)"
        )

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

        # SQLite 自增回归：迁移创建的表（含知识 Agent 底座表）id 必须可自动生成
        conn.execute(
            "INSERT INTO knowledge_agent_runs "
            "(conversation_id, workspace_id, owner_user_id, scope_type, status, "
            " active_slot, retry_count, max_retries) "
            "VALUES (1, 1, 1, 'workspace', 'completed', NULL, 0, 1)"
        )
        auto_run_id = conn.execute(
            "SELECT id FROM knowledge_agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert auto_run_id is not None
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, close_reason, active_slot) "
            "VALUES (1, 1, 1, 5, 'workspace', '自增主题', 'closed', 'scope_change', NULL)"
        )
        auto_version_id = conn.execute(
            "SELECT id FROM knowledge_context_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert auto_version_id is not None

        # 版本号唯一约束：同一对话重复 version_number 被拒绝
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_context_versions "
                "(conversation_id, workspace_id, owner_user_id, version_number, "
                " scope_type, topic_label, status, close_reason, active_slot) "
                "VALUES (1, 1, 1, 1, 'workspace', '重复版本号', 'closed', 'scope_change', NULL)"
            )
        conn.commit()
    finally:
        conn.close()
