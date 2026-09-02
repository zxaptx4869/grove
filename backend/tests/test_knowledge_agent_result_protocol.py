"""结构化 Entry 查找协议测试：结果形态枚举、模型字段、旧行兼容与迁移。"""

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.main import create_app
from app.models import (
    KnowledgeAgentRun,
    KnowledgeConversation,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_LIMITED,
    RESULT_MODE_ANSWER,
    RESULT_MODE_AUTO,
    RESULT_MODE_ENTRIES,
    RUN_COMPLETED,
    RUN_WAITING,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerBasisOut,
    KnowledgeAnswerOut,
    KnowledgeEntryResultItemOut,
    KnowledgeEntryResultSnapshotOut,
    KnowledgeEntryResultsPageOut,
    KnowledgeMessageOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitRequest,
)
from app.services.knowledge_agent.conversations import message_out
from app.services.knowledge_agent.runs import finalize_run, run_out, submit_message


async def _user_and_workspace(db, prefix: str = "协议") -> tuple[User, Workspace]:
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


async def _conversation(db, user: User, workspace: Workspace) -> KnowledgeConversation:
    """创建工作区范围对话。"""
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="协议测试对话",
    )
    db.add(conversation)
    await db.flush()
    return conversation


def test_result_mode_constants_and_schema_defaults() -> None:
    """结果形态枚举与提交请求默认值稳定。"""
    assert (RESULT_MODE_AUTO, RESULT_MODE_ANSWER, RESULT_MODE_ENTRIES) == (
        "auto",
        "answer",
        "entries",
    )
    request = KnowledgeRunSubmitRequest(
        client_message_id="x",
        message="找一下血压知识",
    )
    assert request.result_mode == RESULT_MODE_AUTO
    assert KnowledgeRunSubmitRequest(
        client_message_id="x",
        message="y",
        result_mode=RESULT_MODE_ENTRIES,
    ).result_mode == RESULT_MODE_ENTRIES
    with pytest.raises(ValidationError):
        KnowledgeRunSubmitRequest(
            client_message_id="x",
            message="y",
            result_mode="list",  # type: ignore[arg-type]
        )


def test_result_schema_shapes() -> None:
    """结果项/快照/分页响应字段契约。"""
    now = datetime.now(UTC)
    item = KnowledgeEntryResultItemOut(
        entry_id=1,
        title="闭水试验",
        excerpt="通常持续 24 小时。",
        project_id=2,
        project_name="新房装修",
        node_id=3,
        node_path="施工 / 防水",
        main_type="knowledge",
        info_nature="fact",
        updated_at=now,
        source_count=2,
        match_hint="标题命中「闭水试验」",
        matched_fields=["title"],
    )
    snapshot = KnowledgeEntryResultSnapshotOut(
        query="闭水试验",
        status="completed",
        completeness=RESULT_COMPLETENESS_LIMITED,
        items=[item],
        returned_count=1,
        candidate_limit=50,
        snapshot_updated_at=now,
    )
    assert snapshot.schema_version == "v1"
    assert snapshot.items[0].entry_id == 1
    page = KnowledgeEntryResultsPageOut(
        status="completed",
        completeness=RESULT_COMPLETENESS_LIMITED,
        items=[item],
        returned_count=1,
        total_in_snapshot=6,
        candidate_limit=50,
        has_more=True,
        next_cursor="opaque",
        snapshot_updated_at=now,
    )
    assert page.has_more is True


@pytest.mark.asyncio
async def test_run_model_has_result_mode_fields() -> None:
    """Run 模型新增字段类型与可空性满足契约。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_WAITING,
            max_retries=1,
            request_result_mode=RESULT_MODE_ENTRIES,
        )
        db.add(run)
        await db.flush()
        assert run.request_result_mode == RESULT_MODE_ENTRIES
        assert run.actual_result_mode is None
        assert run.entry_result_json is None
        # 字段类型：枚举长度 8，结果 JSON 为 Text
        request_column = KnowledgeAgentRun.__table__.c.request_result_mode
        actual_column = KnowledgeAgentRun.__table__.c.actual_result_mode
        json_column = KnowledgeAgentRun.__table__.c.entry_result_json
        assert request_column.type.length == 8
        assert actual_column.type.length == 8
        assert str(json_column.type).lower().startswith("text")
        # JSON 字节上限必须低于 MySQL TEXT 上限
        assert get_settings().knowledge_agent_result_json_bytes_limit < 65535


@pytest.mark.asyncio
async def test_submit_message_stores_result_mode_and_idempotent_first_wins() -> None:
    """提交固化请求结果形态；重复 client_message_id 返回首次模式。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        first_message, first_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="client-result-mode",
                message="帮我找出和血压有关的知识",
                result_mode=RESULT_MODE_ENTRIES,
            ),
        )
        assert first_run.request_result_mode == RESULT_MODE_ENTRIES
        assert first_run.actual_result_mode is None

        # 重复提交携带不同结果形态：返回首次消息与 Run，不覆盖首次模式
        second_message, second_run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="client-result-mode",
                message="改掉的文本",
                result_mode=RESULT_MODE_ANSWER,
            ),
        )
        assert second_message.id == first_message.id
        assert second_run.id == first_run.id
        assert second_run.request_result_mode == RESULT_MODE_ENTRIES


@pytest.mark.asyncio
async def test_run_out_and_message_out_compat_fields() -> None:
    """run_out/message_out：新字段输出，旧行与缺失 JSON 兼容。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_WAITING,
            max_retries=1,
        )
        db.add(run)
        await db.flush()
        out = run_out(run)
        assert isinstance(out, KnowledgeRunOut)
        # 旧行三个新字段为空：请求按无覆盖、实际形态与结果为空
        assert out.request_result_mode is None
        assert out.actual_result_mode is None
        assert out.entry_result is None

        now = datetime.now(UTC)
        run.entry_result_json = KnowledgeEntryResultSnapshotOut(
            query="闭水试验",
            status="completed",
            completeness=RESULT_COMPLETENESS_LIMITED,
            items=[
                KnowledgeEntryResultItemOut(
                    entry_id=7,
                    title="闭水试验",
                    excerpt="24 小时",
                    project_name="新房装修",
                    updated_at=now,
                    source_count=1,
                )
            ],
            returned_count=1,
            candidate_limit=50,
            snapshot_updated_at=now,
        ).model_dump_json()
        run.request_result_mode = RESULT_MODE_AUTO
        run.actual_result_mode = RESULT_MODE_ENTRIES
        out = run_out(run)
        assert out.request_result_mode == RESULT_MODE_AUTO
        assert out.actual_result_mode == RESULT_MODE_ENTRIES
        assert out.entry_result is not None
        assert out.entry_result.items[0].entry_id == 7

        from app.models import KnowledgeMessage
        from app.models.knowledge_agent import MESSAGE_TYPE_ASSISTANT

        assistant = KnowledgeMessage(
            conversation_id=conversation.id,
            role="assistant",
            message_type=MESSAGE_TYPE_ASSISTANT,
            content="",
            run_id=run.id,
            scope_type=SCOPE_WORKSPACE,
        )
        db.add(assistant)
        await db.flush()
        msg_out = message_out(assistant, run)
        assert isinstance(msg_out, KnowledgeMessageOut)
        assert msg_out.request_result_mode == RESULT_MODE_AUTO
        assert msg_out.actual_result_mode == RESULT_MODE_ENTRIES


@pytest.fixture
async def api_client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _register(client: httpx.AsyncClient) -> None:
    username = f"protocol_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201


async def _conversation_api(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/knowledge-agent/conversations",
        json={"scope_type": "workspace"},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_api_submit_result_mode_default_and_invalid(api_client: httpx.AsyncClient) -> None:
    """API：默认 auto；非法 result_mode 返回 422。"""
    await _register(api_client)
    conversation = await _conversation_api(api_client)
    default_response = await api_client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "default-mode",
            "message": "默认结果形态",
        },
    )
    assert default_response.status_code == 201
    run = default_response.json()["run"]
    assert run["request_result_mode"] == "auto"

    invalid = await api_client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "invalid-mode",
            "message": "非法形态",
            "result_mode": "list",
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_api_submit_idempotent_keeps_first_result_mode(
    api_client: httpx.AsyncClient,
) -> None:
    """API：重复 client_message_id 携带不同 result_mode 返回首次模式。"""
    await _register(api_client)
    conversation = await _conversation_api(api_client)
    first = await api_client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "idem-result-mode",
            "message": "列出血压知识",
            "result_mode": "entries",
        },
    )
    assert first.status_code == 201
    second = await api_client.post(
        f"/api/knowledge-agent/conversations/{conversation['id']}/messages",
        json={
            "client_message_id": "idem-result-mode",
            "message": "改写文本",
            "result_mode": "answer",
        },
    )
    assert second.status_code == 200
    assert second.json()["user_message"]["id"] == first.json()["user_message"]["id"]
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert second.json()["run"]["request_result_mode"] == "entries"


def test_migration_upgrade_creates_result_and_basis_columns(tmp_path: Path) -> None:
    """fresh SQLite 上迁移链完整升级并创建结果形态与依据字段。"""
    db_path = tmp_path / "result_protocol_migration.db"
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
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert {
            "request_result_mode",
            "actual_result_mode",
            "entry_result_json",
            "request_basis_mode",
            "planned_basis_strategy",
            "planned_basis_json",
            "answer_basis_json",
        } <= columns
        # 枚举列保持约定长度；结果与依据 JSON 为 Text
        info = {
            row[1]: row
            for row in conn.execute("PRAGMA table_info(knowledge_agent_runs)").fetchall()
        }
        assert info["request_result_mode"][2] == "VARCHAR(8)"
        assert info["entry_result_json"][2] == "TEXT"
        assert info["request_basis_mode"][2] == "VARCHAR(16)"
        assert info["planned_basis_json"][2] == "TEXT"
        assert info["answer_basis_json"][2] == "TEXT"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_finalize_run_atomically_persists_answer_basis() -> None:
    """终态提交原子写入回答与实际依据；run_out 返回同一依据快照。"""
    from app.services.knowledge_agent.basis import build_answer_basis

    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        _message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id="basis-finalize-1",
                message="结合预算与项目记录给建议",
                basis_mode="auto",
            ),
        )
        run.status = "processing"
        run.active_slot = "active"
        run.planned_basis_strategy = "hybrid"
        await db.flush()

        answer = KnowledgeAnswerOut(
            answer="建议先核对预算上限。",
            status="completed",
            citations=[],
        )
        basis = build_answer_basis(
            answer=answer,
            user_statement_ids=[11, 9, 11],
            model_knowledge_used=True,
            external_material_required=False,
        )
        await finalize_run(
            db,
            run,
            answer=answer,
            status=RUN_COMPLETED,
            fallback_summary={"has_fallback": False, "stages": []},
            answer_basis=basis,
        )
        await db.commit()

        await db.refresh(run)
        assert run.answer_basis_json is not None
        out = run_out(run)
        assert out.answer_basis is not None
        assert out.answer_basis.schema_version == "v1"
        assert out.answer_basis.grove.used is False
        assert out.answer_basis.grove.citation_count == 0
        assert out.answer_basis.user_statements.message_ids == [9, 11]
        assert out.answer_basis.model_knowledge.used is True
        assert out.answer_basis.external_material.status == "not_used"
        assert isinstance(out.answer_basis, KnowledgeAnswerBasisOut)


@pytest.mark.asyncio
async def test_answer_basis_grove_counts_derive_from_final_citations() -> None:
    """Grove 数量只从最终 Citation 派生；失效句柄不进入实际依据。"""
    from app.schemas.knowledge_agent import KnowledgeRunCitationOut
    from app.services.knowledge_agent.basis import build_answer_basis

    answer = KnowledgeAnswerOut(
        answer="两个来源的回答。",
        status="completed",
        citations=[
            KnowledgeRunCitationOut(
                evidence_id=1,
                evidence_handle="ev_a",
                entry_id=10,
                entry_title="条目一",
                source_id=1,
                source_title="来源一",
                quote="原文一",
            ),
            KnowledgeRunCitationOut(
                evidence_id=2,
                evidence_handle="ev_b",
                entry_id=10,
                entry_title="条目一",
                source_id=2,
                source_title="来源二",
                quote="原文二",
            ),
            KnowledgeRunCitationOut(
                evidence_id=3,
                evidence_handle="ev_c",
                entry_id=20,
                entry_title="条目二",
                source_id=3,
                source_title="来源三",
                quote="原文三",
            ),
        ],
    )
    basis = build_answer_basis(
        answer=answer,
        user_statement_ids=[],
        model_knowledge_used=False,
        external_material_required=True,
    )
    assert basis.grove.used is True
    assert basis.grove.citation_count == 3
    assert basis.grove.entry_count == 2
    assert basis.user_statements.message_ids == []
    assert basis.model_knowledge.used is False
    assert basis.external_material.status == "required_unavailable"


def test_migration_downgrade_then_upgrade_roundtrip(tmp_path: Path) -> None:
    """downgrade→upgrade 往返：结果形态字段删除后可重建，历史 Run 行保留。

    直接降级到结果形态迁移的父 revision，再重新升级验证结果列重建与
    历史行兼容；不使用相对步数，避免后续追加迁移后测试目标漂移。
    """
    db_path = tmp_path / "result_protocol_roundtrip.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    backend = Path(__file__).resolve().parents[1]

    def _run_alembic(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )

    upgrade = _run_alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

    # 写入带新字段的 Run 行后再降级
    conn = sqlite3.connect(db_path)
    now = "2026-08-31 22:00:00"
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
        "INSERT INTO knowledge_conversations "
        "(id, workspace_id, owner_user_id, scope_type, title) "
        "VALUES (1, 1, 1, 'workspace', '迁移对话')"
    )
    conn.execute(
        "INSERT INTO knowledge_agent_runs "
        "(id, conversation_id, run_kind, workspace_id, owner_user_id, scope_type, "
        " status, max_retries, request_result_mode, actual_result_mode) "
        "VALUES (1, 1, 'answer', 1, 1, 'workspace', 'waiting', 1, 'auto', 'entries')"
    )
    conn.commit()
    conn.close()

    downgrade = _run_alembic("downgrade", "e7f8a9b0c1d2")
    assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    re_upgrade = _run_alembic("upgrade", "head")
    assert re_upgrade.returncode == 0, re_upgrade.stdout + re_upgrade.stderr

    conn = sqlite3.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, request_result_mode, actual_result_mode "
            "FROM knowledge_agent_runs WHERE id = 1"
        ).fetchone()
        assert run is not None
        assert run[0] == "waiting"
        # 降级删除后重建：历史行新字段为空，按旧行兼容读取
        assert run[1] is None
        assert run[2] is None
    finally:
        conn.close()
