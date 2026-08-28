"""知识 Agent 调查数据骨架测试：枚举、默认值、所有权冗余、唯一约束与迁移。"""

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
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
)
from app.models.knowledge_agent import (
    ANSWER_MODE_AUTO,
    ANSWER_MODE_INVESTIGATE,
    ANSWER_MODE_QUICK,
    ANSWER_MODES,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_ACTIONS,
    INVESTIGATION_STATUS_ACTIVE,
    INVESTIGATION_STATUS_CANCELLED,
    INVESTIGATION_STATUS_COMPLETED,
    INVESTIGATION_STATUS_FAILED,
    INVESTIGATION_STATUS_INSUFFICIENT,
    INVESTIGATION_TERMINAL_STATUSES,
    SCOPE_WORKSPACE,
    STOP_REASON_CANCELLED,
    STOP_REASON_CONTROLLER_COMPLETE,
    STOP_REASON_ENTRY_BUDGET,
    STOP_REASON_EVIDENCE_BUDGET,
    STOP_REASON_FAILED,
    STOP_REASON_INSUFFICIENT,
    STOP_REASON_MAX_ROUNDS,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_QUERY_BUDGET,
    STOP_REASONS,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.runs import submit_message
from tests._knowledge_agent_fixtures import create_user, create_workspace


async def _user_workspace_conversation(
    db, prefix: str = "调查模型"
) -> tuple[object, object, KnowledgeConversation]:
    """创建独立用户、Workspace 与对话。"""
    user = await create_user(db, prefix)
    workspace = await create_workspace(db, user)
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="调查模型测试",
    )
    db.add(conversation)
    await db.flush()
    return user, workspace, conversation


async def _investigation_with_run(
    db,
    conversation,
) -> tuple[KnowledgeInvestigation, KnowledgeAgentRun]:
    """创建带调查的 waiting Run（走真实幂等提交 + 直接创建 Investigation）。"""
    user_message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"inv-model-{uuid.uuid4().hex[:8]}",
            message="调查问题",
        ),
    )
    investigation = KnowledgeInvestigation(
        run_id=run.id,
        conversation_id=conversation.id,
        workspace_id=conversation.workspace_id,
        owner_user_id=conversation.owner_user_id,
        scope_type=SCOPE_WORKSPACE,
        objective="调查问题",
        requested_answer_mode=ANSWER_MODE_INVESTIGATE,
        actual_answer_mode=ANSWER_MODE_INVESTIGATE,
        status=INVESTIGATION_STATUS_ACTIVE,
    )
    db.add(investigation)
    await db.flush()
    return investigation, run


def test_answer_mode_and_investigation_enums_stable() -> None:
    """回答模式、调查状态、停止原因与控制器动作枚举保持稳定。"""
    assert ANSWER_MODES == (ANSWER_MODE_AUTO, ANSWER_MODE_QUICK, ANSWER_MODE_INVESTIGATE)
    assert INVESTIGATION_ACTIONS == (
        INVESTIGATION_ACTION_SEARCH,
        INVESTIGATION_ACTION_ANSWER,
        INVESTIGATION_ACTION_INSUFFICIENT,
    )
    assert INVESTIGATION_TERMINAL_STATUSES == {
        INVESTIGATION_STATUS_COMPLETED,
        INVESTIGATION_STATUS_INSUFFICIENT,
        INVESTIGATION_STATUS_CANCELLED,
        INVESTIGATION_STATUS_FAILED,
    }
    assert STOP_REASONS == (
        STOP_REASON_CONTROLLER_COMPLETE,
        STOP_REASON_INSUFFICIENT,
        STOP_REASON_NO_PROGRESS,
        STOP_REASON_MAX_ROUNDS,
        STOP_REASON_QUERY_BUDGET,
        STOP_REASON_ENTRY_BUDGET,
        STOP_REASON_EVIDENCE_BUDGET,
        STOP_REASON_CANCELLED,
        STOP_REASON_FAILED,
    )


@pytest.mark.asyncio
async def test_investigation_defaults_ownership_and_run_one_to_one() -> None:
    """调查默认预算与所有权冗余；同一 Run 不能创建第二个调查。"""
    async with async_session_factory() as db:
        user, workspace, conversation = await _user_workspace_conversation(db)
        investigation, run = await _investigation_with_run(db, conversation)
        await db.commit()

        loaded = await db.get(KnowledgeInvestigation, investigation.id)
        assert loaded is not None
        assert loaded.run_id == run.id
        assert loaded.workspace_id == workspace.id
        assert loaded.owner_user_id == user.id
        assert loaded.conversation_id == conversation.id
        assert loaded.status == INVESTIGATION_STATUS_ACTIVE
        assert loaded.max_rounds == 3
        assert loaded.max_queries_per_round == 3
        assert loaded.max_total_queries == 6
        assert loaded.max_entries == 30
        assert loaded.max_evidence == 12
        assert loaded.current_round == 0
        assert loaded.total_queries_executed == 0
        assert loaded.stop_reason is None

        duplicate = KnowledgeInvestigation(
            run_id=run.id,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            objective="重复调查",
            requested_answer_mode=ANSWER_MODE_INVESTIGATE,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_round_number_and_query_hash_unique_constraints() -> None:
    """同调查轮次号与规范化查询指纹唯一；重复写入被数据库拒绝。"""
    async with async_session_factory() as db:
        user, workspace, conversation = await _user_workspace_conversation(db)
        investigation, _run = await _investigation_with_run(db, conversation)
        round_one = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            status="running",
        )
        db.add(round_one)
        await db.flush()
        duplicate_round = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            status="completed",
        )
        db.add(duplicate_round)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        query_a = KnowledgeInvestigationQuery(
            investigation_id=investigation.id,
            round_id=round_one.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            sequence=1,
            original_query="闭水试验持续多久",
            normalized_query="闭水试验 持续 多久",
            normalized_query_hash="hash-a",
        )
        db.add(query_a)
        await db.flush()
        duplicate_query = KnowledgeInvestigationQuery(
            investigation_id=investigation.id,
            round_id=round_one.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            sequence=2,
            original_query="闭水试验持续多久？",
            normalized_query="闭水试验 持续 多久",
            normalized_query_hash="hash-a",
        )
        db.add(duplicate_query)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 不同规范化指纹允许写入（恢复/多轮不误伤）
        query_b = KnowledgeInvestigationQuery(
            investigation_id=investigation.id,
            round_id=round_one.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            sequence=2,
            original_query="放水时机",
            normalized_query="放水 时机",
            normalized_query_hash="hash-b",
        )
        db.add(query_b)
        await db.flush()
        await db.commit()


@pytest.mark.asyncio
async def test_run_delete_cascades_investigation_rounds_and_queries() -> None:
    """删除 Run 级联删除调查、轮次与查询（SQLite 外键级联）。"""
    async with async_session_factory() as db:
        user, workspace, conversation = await _user_workspace_conversation(db)
        investigation, run = await _investigation_with_run(db, conversation)
        round_row = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            status="completed",
            controller_action=INVESTIGATION_ACTION_ANSWER,
            coverage_json='["覆盖项"]',
            gaps_json='["缺口项"]',
            conflicts_json="[]",
            queries_planned=1,
            queries_executed=1,
            entries_added=1,
            evidence_added=1,
            meta_json='{"provider":"llm","model":"fake","is_fallback":false}',
        )
        db.add(round_row)
        await db.flush()
        query_row = KnowledgeInvestigationQuery(
            investigation_id=investigation.id,
            round_id=round_row.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            sequence=1,
            original_query="闭水试验",
            normalized_query="闭水试验",
            normalized_query_hash="hash-cascade",
            status="executed",
            result_counts_json='{"new_entries":1}',
        )
        db.add(query_row)
        await db.commit()

        await db.delete(run)
        await db.commit()
        assert await db.get(KnowledgeInvestigation, investigation.id) is None
        assert await db.get(KnowledgeInvestigationRound, round_row.id) is None
        assert await db.get(KnowledgeInvestigationQuery, query_row.id) is None


@pytest.mark.asyncio
async def test_investigation_json_summary_round_trip() -> None:
    """覆盖/缺口/冲突与恢复时间可序列化保存并读回。"""
    async with async_session_factory() as db:
        user, workspace, conversation = await _user_workspace_conversation(db)
        investigation, run = await _investigation_with_run(db, conversation)
        investigation.coverage_summary = '["闭水试验 24 小时"]'
        investigation.gaps_summary = '["放水时机未覆盖"]'
        investigation.conflicts_summary = "[]"
        investigation.stop_reason = STOP_REASON_MAX_ROUNDS
        investigation.current_round = 3
        investigation.total_queries_executed = 5
        investigation.distinct_entries_found = 8
        investigation.citable_evidence_count = 6
        run.current_round = 3
        await db.commit()
        await db.refresh(investigation)
        assert investigation.stop_reason == STOP_REASON_MAX_ROUNDS
        assert investigation.coverage_summary == '["闭水试验 24 小时"]'
        assert investigation.distinct_entries_found == 8


def test_migration_upgrade_downgrade_upgrade_and_investigation_columns(
    tmp_path: Path,
) -> None:
    """全新 SQLite 库执行 upgrade→downgrade→upgrade，验证调查表与字段。"""
    db_path = tmp_path / "investigation_migration.db"
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
        assert {
            "knowledge_investigations",
            "knowledge_investigation_rounds",
            "knowledge_investigation_queries",
        } <= tables
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert {
            "request_answer_mode",
            "actual_answer_mode",
            "current_round",
            "investigation_summary",
        } <= run_columns
        invocation_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(knowledge_agent_model_invocations)"
            ).fetchall()
        }
        assert {"investigation_id", "round_number", "query_sequence"} <= invocation_columns
        tool_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(knowledge_agent_tool_calls)"
            ).fetchall()
        }
        assert {"investigation_id", "round_number", "query_sequence"} <= tool_columns
        evidence_columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(knowledge_agent_evidences)"
            ).fetchall()
        }
        assert {"round_number", "query_sequence"} <= evidence_columns
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
        assert "knowledge_investigations" not in tables
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert "request_answer_mode" not in run_columns
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
        assert "knowledge_investigations" in tables
        run_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert "investigation_summary" in run_columns
    finally:
        conn.close()
