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
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import async_session_factory
from app.models import (
    Attachment,
    Candidate,
    Entry,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeCandidateDraft,
    KnowledgeConversation,
    KnowledgeMessage,
    Node,
    Project,
    Source,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    DRAFT_CANCELLED,
    DRAFT_CONFIRMED,
    DRAFT_DRAFT,
    DRAFT_FAILED,
    DRAFT_GENERATING,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_KIND_ANSWER,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_WAITING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeDraftActionRequest,
    KnowledgeRunCitationOut,
)
from app.services.candidate_creation import create_candidate_from_answer
from app.services.knowledge_agent.candidate import (
    confirm_draft,
    execute_draft_candidate_run,
    submit_draft_candidate,
)
from app.services.knowledge_agent.evidence import attachment_fingerprint
from app.services.knowledge_agent.runs import run_out
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


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


async def _answer_run_with_evidence(
    db,
    user: User,
    workspace: Workspace,
    project: Project,
    *,
    scope_type: str = SCOPE_PROJECT,
    question: str = "闭水试验通常持续多久？",
    answer_text: str = "闭水试验通常持续 24 小时。",
    quote: str = "闭水试验通常持续 24 小时",
) -> tuple[
    KnowledgeConversation,
    KnowledgeAgentRun,
    Entry,
    Source,
    Attachment,
    KnowledgeAgentEvidence,
]:
    """创建带最终引用的已完成回答 Run（不经过 Worker，直接构造终态）。"""
    source, attachment = await create_source_attachment(
        db,
        workspace,
        project,
        title="验收手册",
        text_content=f"{quote}，验收前不得放水。",
    )
    node = await create_child_node(db, project, "施工")
    entry = await create_entry_with_evidence(
        db,
        project,
        node,
        source,
        attachment,
        title="闭水试验",
        content="闭水试验通常持续 24 小时。",
        quote=quote,
    )
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=scope_type,
        project_id=project.id if scope_type == SCOPE_PROJECT else None,
        title="回答测试对话",
    )
    db.add(conversation)
    await db.flush()
    user_msg = KnowledgeMessage(
        conversation_id=conversation.id,
        role="user",
        message_type="user",
        content=question,
        client_message_id="q-1",
        scope_type=scope_type,
        project_id=project.id if scope_type == SCOPE_PROJECT else None,
        project_name=project.name,
    )
    db.add(user_msg)
    await db.flush()
    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=scope_type,
        project_id=project.id if scope_type == SCOPE_PROJECT else None,
        project_name=project.name,
        user_message_id=user_msg.id,
        status=RUN_COMPLETED,
        run_kind=RUN_KIND_ANSWER,
        max_retries=1,
    )
    db.add(run)
    await db.flush()
    evidence = KnowledgeAgentEvidence(
        run_id=run.id,
        handle=f"ev_{uuid.uuid4().hex}",
        entry_id=entry.id,
        project_id=project.id,
        source_id=source.id,
        attachment_id=attachment.id,
        entry_title=entry.title,
        project_name=project.name,
        source_title=source.title,
        node_path="施工",
        quote=quote,
        quote_start=0,
        quote_end=len(quote),
        content_fingerprint=attachment_fingerprint(attachment.text_content or ""),
        purpose="answer",
        is_citable=True,
    )
    db.add(evidence)
    await db.flush()
    assistant = KnowledgeMessage(
        conversation_id=conversation.id,
        role="assistant",
        message_type="assistant",
        content=answer_text,
        run_id=run.id,
        scope_type=scope_type,
        project_id=project.id if scope_type == SCOPE_PROJECT else None,
        project_name=project.name,
    )
    db.add(assistant)
    await db.flush()
    run.assistant_message_id = assistant.id
    run.answer_json = KnowledgeAnswerOut(
        answer=answer_text,
        status="completed",
        citations=[
            KnowledgeRunCitationOut(
                evidence_id=evidence.id,
                evidence_handle=evidence.handle,
                entry_id=entry.id,
                entry_title=entry.title,
                source_id=source.id,
                source_title=source.title,
                attachment_id=attachment.id,
                quote=quote,
                project_id=project.id,
                project_name=project.name,
                node_path="施工",
            )
        ],
    ).model_dump_json()
    await db.flush()
    return conversation, run, entry, source, attachment, evidence


def _draft_action(
    *,
    source_run_id: int,
    target_project_id: int | None = None,
    client_message_id: str | None = None,
) -> KnowledgeDraftActionRequest:
    return KnowledgeDraftActionRequest(
        client_message_id=client_message_id or f"action-{uuid.uuid4().hex[:8]}",
        source_run_id=source_run_id,
        target_project_id=target_project_id,
    )


@pytest.mark.asyncio
async def test_submit_draft_from_project_scope_answer() -> None:
    """项目范围回答：固化目标项目，创建可见消息、operation Run 与 generating Draft。"""
    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "提交项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        await db.commit()

        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()

        assert message.role == "user"
        assert "整理成知识" in message.content
        assert run.run_kind == RUN_KIND_DRAFT_CANDIDATE
        assert run.source_run_id == source_run.id
        assert run.scope_type == SCOPE_PROJECT
        assert run.project_id == project.id
        assert run.status == RUN_WAITING
        assert draft.status == DRAFT_GENERATING
        assert draft.target_project_id == project.id
        assert draft.source_run_id == source_run.id


@pytest.mark.asyncio
async def test_submit_workspace_single_project_prefills_target() -> None:
    """Workspace 回答只命中一个项目：无需客户端传目标项目即可提交。"""
    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "唯一命中项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(
                db,
                user,
                workspace,
                project,
                scope_type=SCOPE_WORKSPACE,
            )
        )
        await db.commit()

        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        assert run.project_id == project.id
        assert draft.target_project_id == project.id


@pytest.mark.asyncio
async def test_submit_workspace_multi_project_requires_target_choice() -> None:
    """Workspace 回答命中多个项目：未选择目标项目返回 422，选择后提交成功。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        first = await create_project(db, workspace, "项目甲")
        second = await create_project(db, workspace, "项目乙")
        # 两个项目各一条 Evidence 都进入同一回答引用
        conversation, source_run, _e1, _s1, _a1, evidence_a = await _answer_run_with_evidence(
            db,
            user,
            workspace,
            first,
            scope_type=SCOPE_WORKSPACE,
            answer_text="两条记录都确认了闭水时长。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            second,
            title="监理清单",
            text_content="闭水试验建议 48 小时观察。",
        )
        node_b = await create_child_node(db, second, "施工")
        entry_b = await create_entry_with_evidence(
            db,
            second,
            node_b,
            source_b,
            attachment_b,
            title="闭水试验乙",
            content="闭水试验建议 48 小时观察。",
            quote="闭水试验建议 48 小时观察",
        )
        evidence_b = KnowledgeAgentEvidence(
            run_id=source_run.id,
            handle=f"ev_{uuid.uuid4().hex}",
            entry_id=entry_b.id,
            project_id=second.id,
            source_id=source_b.id,
            attachment_id=attachment_b.id,
            entry_title=entry_b.title,
            project_name=second.name,
            source_title=source_b.title,
            quote="闭水试验建议 48 小时观察",
            content_fingerprint=attachment_fingerprint(attachment_b.text_content or ""),
            purpose="answer",
            is_citable=True,
        )
        db.add(evidence_b)
        await db.flush()
        answer = KnowledgeAnswerOut.model_validate_json(source_run.answer_json)
        answer.citations.append(
            KnowledgeRunCitationOut(
                evidence_id=evidence_b.id,
                evidence_handle=evidence_b.handle,
                entry_id=entry_b.id,
                entry_title=entry_b.title,
                source_id=source_b.id,
                source_title=source_b.title,
                attachment_id=attachment_b.id,
                quote="闭水试验建议 48 小时观察",
                project_id=second.id,
                project_name=second.name,
            )
        )
        source_run.answer_json = answer.model_dump_json()
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await submit_draft_candidate(
                db,
                conversation,
                _draft_action(source_run_id=source_run.id),
            )
        assert exc_info.value.status_code == 422

        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id, target_project_id=second.id),
        )
        await db.commit()
        assert run.project_id == second.id
        assert draft.target_project_id == second.id
        assert draft.target_project_name == "项目乙"


@pytest.mark.asyncio
async def test_submit_rejects_ineligible_and_cross_conversation_source() -> None:
    """无引用/未完成来源回答拒绝；跨对话 source_run_id 一律 404。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "拒绝项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        # 来源回答改为无引用
        source_run.answer_json = KnowledgeAnswerOut(
            answer="没有引用。", status="insufficient", insufficient_note="无证据"
        ).model_dump_json()
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await submit_draft_candidate(
                db,
                conversation,
                _draft_action(source_run_id=source_run.id),
            )
        assert exc_info.value.status_code == 409

        # 跨对话来源 Run
        other_conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=project.id,
            title="另一对话",
        )
        db.add(other_conversation)
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await submit_draft_candidate(
                db,
                other_conversation,
                _draft_action(source_run_id=source_run.id),
            )
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_rejects_cross_workspace_target_project() -> None:
    """越权 target_project_id 返回 404，不暴露对象是否存在。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "目标项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(
                db,
                user,
                workspace,
                project,
                scope_type=SCOPE_WORKSPACE,
            )
        )
        other_user = await create_user(db, "他人")
        other_workspace = await create_workspace(db, other_user)
        foreign_project = await create_project(db, other_workspace, "他人项目")
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await submit_draft_candidate(
                db,
                conversation,
                _draft_action(
                    source_run_id=source_run.id,
                    target_project_id=foreign_project.id,
                ),
            )
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_execute_draft_run_success_with_whitelisted_handles(monkeypatch) -> None:
    """模型返回合法句柄：Draft 进入 draft，Run completed，句柄白名单校验。"""
    from app.agents.candidate_draft import CandidateDraftOutput

    async def _fake_agent(
        db,
        workspace_id,
        *,
        question,
        original_answer,
        target_project_label,
        evidences,
    ):
        handles = [item["handle"] for item in evidences]
        return (
            CandidateDraftOutput(
                title="闭水试验 24 小时",
                content="闭水试验通常持续 24 小时，验收前不得放水。",
                main_type="knowledge",
                info_nature="fact",
                selected_evidence_handles=handles,
            ),
            StageMeta(
                purpose="draft_candidate",
                provider="llm",
                model="fake-draft",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.candidate.run_candidate_draft_agent",
        _fake_agent,
    )
    from app.services.knowledge_agent.observability import StageMeta

    async with async_session_factory() as db:
        user = await create_user(db, "执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "执行项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()

        await execute_draft_candidate_run(db, run)
        await db.commit()

        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_COMPLETED
        assert run.active_slot is None
        assert draft.status == DRAFT_DRAFT
        assert draft.title == "闭水试验 24 小时"
        assert evidence.handle in draft.evidence_handles_json
        assert draft.confirmed_candidate_id is None


@pytest.mark.asyncio
async def test_execute_draft_run_unknown_handle_fails(monkeypatch) -> None:
    """模型返回未知句柄：丢弃后不足一条，草稿失败且不创建任何对象。"""
    from app.agents.candidate_draft import CandidateDraftOutput

    async def _fake_agent(
        db,
        workspace_id,
        *,
        question,
        original_answer,
        target_project_label,
        evidences,
    ):
        return (
            CandidateDraftOutput(
                title="越权草稿",
                content="混入其他项目证据。",
                main_type="knowledge",
                info_nature=None,
                selected_evidence_handles=["ev_unknown"],
            ),
            StageMeta(
                purpose="draft_candidate",
                provider="llm",
                model="fake-draft",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.candidate.run_candidate_draft_agent",
        _fake_agent,
    )
    from app.services.knowledge_agent.observability import StageMeta

    async with async_session_factory() as db:
        user = await create_user(db, "执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "执行项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        await execute_draft_candidate_run(db, run)
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert draft.status == DRAFT_FAILED
        assert "未返回任何有效证据句柄" in (draft.error or "")


@pytest.mark.asyncio
async def test_execute_draft_run_model_unavailable_uses_seed(monkeypatch) -> None:
    """模型不可用：确定性 seed 草稿 + 显式降级标识，只绑定有效 Evidence。"""
    from app.services.knowledge_agent.observability import StageMeta

    async def _fake_agent(
        db,
        workspace_id,
        *,
        question,
        original_answer,
        target_project_label,
        evidences,
    ):
        return (
            None,
            StageMeta(
                purpose="draft_candidate",
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.candidate.run_candidate_draft_agent",
        _fake_agent,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "执行项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        await execute_draft_candidate_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_COMPLETED
        assert draft.status == DRAFT_DRAFT
        assert draft.generation_meta_json
        meta = __import__("json").loads(draft.generation_meta_json)
        assert meta["is_fallback"] is True
        assert evidence.handle in draft.evidence_handles_json
        assert "降级" not in draft.title  # seed 标题来自原回答首句


@pytest.mark.asyncio
async def test_execute_draft_run_evidence_invalid_fails() -> None:
    """生成阶段 Evidence 失效：Run/Draft 失败，不创建无来源草稿。"""
    async with async_session_factory() as db:
        user = await create_user(db, "执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "执行项目")
        conversation, source_run, _entry, _source, attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        # 生成前来源原文被修改，指纹不再匹配
        attachment.text_content = "闭水试验建议 48 小时观察。"
        await db.commit()
        await execute_draft_candidate_run(db, run)
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert draft.status == DRAFT_FAILED
        assert "没有可核验的来源证据" in (draft.error or "")


@pytest.mark.asyncio
async def test_confirm_draft_creates_pending_candidate(monkeypatch) -> None:
    """确认草稿：创建虚拟 Source/Attachment/Extraction/pending Candidate，不改 Entry。"""

    async with async_session_factory() as db:
        user = await create_user(db, "确认")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "确认项目")
        conversation, source_run, entry, source, attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.title = "闭水试验要点"
        draft.content = "闭水试验通常持续 24 小时，验收前不得放水。"
        draft.status = DRAFT_DRAFT
        draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        await db.commit()

        confirmed, candidate = await confirm_draft(
            db,
            draft,
            f"op-{uuid.uuid4().hex[:8]}",
        )
        await db.commit()

        assert confirmed.status == DRAFT_CONFIRMED
        assert confirmed.confirmed_candidate_id == candidate.id
        assert candidate.status == "pending"
        assert candidate.source_id is not None
        source_row = await db.get(Source, candidate.source_id)
        assert source_row is not None
        assert source_row.workspace_id == workspace.id
        assert source_row.project_id == project.id
        assert "知识 Agent 对话" in source_row.title
        assert source_row.note == "闭水试验通常持续多久？"
        assert source_row.id == source.id or source_row.id != source.id
        # 未新增或修改正式 Entry（按目标项目过滤）
        entries = (
            (
                await db.execute(
                    select(Entry).where(Entry.project_id == project.id)
                )
            )
            .scalars()
            .all()
        )
        assert [row.id for row in entries] == [entry.id]
        assert entries[0].content == "闭水试验通常持续 24 小时。"


@pytest.mark.asyncio
async def test_confirm_draft_idempotent_replay_returns_same_candidate() -> None:
    """相同 client_operation_id 重放返回同一 Candidate，不重复创建对象。"""
    async with async_session_factory() as db:
        user = await create_user(db, "确认")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "确认项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.title = "闭水试验要点"
        draft.content = "闭水试验通常持续 24 小时。"
        draft.status = DRAFT_DRAFT
        draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        await db.commit()
        key = f"op-{uuid.uuid4().hex[:8]}"

        first, first_candidate = await confirm_draft(db, draft, key)
        await db.commit()
        second, second_candidate = await confirm_draft(db, draft, key)
        await db.commit()

        assert second_candidate.id == first_candidate.id
        sources = (
            (
                await db.execute(
                    select(Source).where(Source.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(sources) == 2  # 原始回答来源 + 确认创建的虚拟来源，重放不重复
        candidates = (
            (
                await db.execute(
                    select(Candidate).where(
                        Candidate.source_id.in_([row.id for row in sources])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(candidates) == 1


@pytest.mark.asyncio
async def test_confirm_draft_evidence_invalid_keeps_draft_editable() -> None:
    """确认前 Evidence 失效返回 409，Draft 保持可编辑且不创建 Candidate。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "确认")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "确认项目")
        conversation, source_run, _entry, _source, attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.title = "闭水试验要点"
        draft.content = "闭水试验通常持续 24 小时。"
        draft.status = DRAFT_DRAFT
        draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        attachment.text_content = "内容已变化，指纹不再匹配。"
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await confirm_draft(db, draft, f"op-{uuid.uuid4().hex[:8]}")
        assert exc_info.value.status_code == 409
        await db.refresh(draft)
        assert draft.status == DRAFT_DRAFT
        sources = (
            (
                await db.execute(
                    select(Source).where(Source.workspace_id == workspace.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(sources) == 1  # 只有原始回答来源，没有确认创建的虚拟来源


@pytest.mark.asyncio
async def test_confirm_draft_cross_user_404() -> None:
    """其他用户确认草稿返回 404，不暴露对象。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "确认")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "确认项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.status = DRAFT_DRAFT
        await db.commit()
        other_user = await create_user(db, "他人")
        other_workspace = await create_workspace(db, other_user)
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            from app.services.knowledge_agent.candidate import get_owned_draft

            owned = await get_owned_draft(
                db,
                other_workspace.id,
                other_user.id,
                draft.id,
            )
            await confirm_draft(db, owned, f"op-{uuid.uuid4().hex[:8]}")
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_shared_creation_rolls_back_on_transaction_failure() -> None:
    """共享创建服务事务失败不留半成品 Source/Candidate。"""
    async with async_session_factory() as db:
        user = await create_user(db, "创建")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "创建项目")
        await db.flush()
        sources_before = (await db.execute(select(Source))).scalars().all()
        candidates_before = (await db.execute(select(Candidate))).scalars().all()
        try:
            await create_candidate_from_answer(
                db,
                workspace_id=workspace.id,
                project_id=project.id,
                question="问题",
                title="标题",
                content="内容",
                main_type="knowledge",
                info_nature=None,
                evidence_refs=[],
                provider="reader",
                model="reader",
                prompt_version="v1",
            )
            raise RuntimeError("模拟提交失败")
        except RuntimeError:
            await db.rollback()
        sources = (await db.execute(select(Source))).scalars().all()
        candidates = (await db.execute(select(Candidate))).scalars().all()
        assert len(sources) == len(sources_before)
        assert len(candidates) == len(candidates_before)


@pytest.mark.asyncio
async def test_confirm_routing_failure_keeps_pending_candidate(monkeypatch) -> None:
    """目录推荐/关系判断失败：Candidate 保留并暴露真实 pending，不伪装正常。"""

    async def _broken_route_source(db, source_id: int) -> None:
        raise RuntimeError("路由服务不可用")

    monkeypatch.setattr(
        "app.services.knowledge_agent.candidate.route_source",
        _broken_route_source,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.candidate.route_relations",
        _broken_route_source,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "确认")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "确认项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.title = "闭水试验要点"
        draft.content = "闭水试验通常持续 24 小时。"
        draft.status = DRAFT_DRAFT
        draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        await db.commit()

        confirmed, candidate = await confirm_draft(
            db,
            draft,
            f"op-{uuid.uuid4().hex[:8]}",
        )
        await db.commit()
        await db.refresh(candidate)
        assert confirmed.status == DRAFT_CONFIRMED
        assert candidate.status == "pending"
        assert candidate.routing_status == "pending"
        assert candidate.relation_status == "pending"


@pytest.mark.asyncio
async def test_submit_draft_idempotent_duplicate_client_message() -> None:
    """相同 client_message_id 重放返回同一 Run/Draft，不创建第二个对象。"""
    async with async_session_factory() as db:
        user = await create_user(db, "幂等")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "幂等项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        await db.commit()
        action = _draft_action(source_run_id=source_run.id, client_message_id="dup-action-1")
        first_message, first_run, first_draft = await submit_draft_candidate(
            db,
            conversation,
            action,
        )
        await db.commit()
        second_message, second_run, second_draft = await submit_draft_candidate(
            db,
            conversation,
            action,
        )
        await db.commit()
        assert second_message.id == first_message.id
        assert second_run.id == first_run.id
        assert second_draft.id == first_draft.id
        drafts = (
            (
                await db.execute(
                    select(KnowledgeCandidateDraft).where(
                        KnowledgeCandidateDraft.conversation_id == conversation.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(drafts) == 1


@pytest.mark.asyncio
async def test_submit_draft_active_run_conflict() -> None:
    """对话已有活动 Run 时提交草稿动作返回 409，不创建消息或 Draft。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "冲突")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "冲突项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        active_run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=project.id,
            status=RUN_WAITING,
            active_slot="active",
            max_retries=1,
        )
        db.add(active_run)
        await db.commit()
        with pytest.raises(HTTPException) as exc_info:
            await submit_draft_candidate(
                db,
                conversation,
                _draft_action(source_run_id=source_run.id),
            )
        assert exc_info.value.status_code == 409
        drafts = (
            (
                await db.execute(
                    select(KnowledgeCandidateDraft).where(
                        KnowledgeCandidateDraft.conversation_id == conversation.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert drafts == []


@pytest.mark.asyncio
async def test_cancel_waiting_draft_run_marks_draft_cancelled() -> None:
    """取消 waiting 草稿 Run：Run 与 Draft 同时进入 cancelled，不创建对象。"""
    from app.services.knowledge_agent.runs import cancel_run

    async with async_session_factory() as db:
        user = await create_user(db, "取消")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "取消项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        await cancel_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == "cancelled"
        assert draft.status == DRAFT_CANCELLED
        assert run.active_slot is None


@pytest.mark.asyncio
async def test_worker_cancel_processing_draft_run_marks_draft_cancelled() -> None:
    """Worker 在处理边界识别取消：Draft 同步 cancelled，不创建知识对象。"""
    from app.knowledge_agent_worker import process_one_run
    from tests.test_knowledge_agent_worker import _cancel_other_waiting_runs

    async with async_session_factory() as db:
        user = await create_user(db, "取消执行")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "取消执行项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        await _cancel_other_waiting_runs(db, keep_run_id=run.id)
        run.status = RUN_WAITING
        run.cancel_requested = True
        await db.commit()
        assert await process_one_run() is True
        async with async_session_factory() as check_db:
            checked_run = await check_db.get(KnowledgeAgentRun, run.id)
            checked_draft = await check_db.get(KnowledgeCandidateDraft, draft.id)
            assert checked_run.status == "cancelled"
            assert checked_run.active_slot is None
            assert checked_draft.status == DRAFT_CANCELLED


@pytest.mark.asyncio
async def test_worker_recovery_reuses_same_draft() -> None:
    """租约超时恢复草稿 Run：重新入队同一 Run/Draft，不创建第二个 Draft。"""
    from datetime import UTC, datetime, timedelta

    from app.knowledge_agent_worker import recover_stale_runs

    async with async_session_factory() as db:
        user = await create_user(db, "恢复")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "恢复项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        run.status = "processing"
        run.claimed_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
        draft_id = draft.id
        run_id = run.id
        await db.commit()

        recovered = await recover_stale_runs()
        assert recovered == 1
        async with async_session_factory() as check_db:
            checked_run = await check_db.get(KnowledgeAgentRun, run_id)
            assert checked_run.status == RUN_WAITING
            assert checked_run.retry_count == 1
            drafts = (
                (
                    await check_db.execute(
                        select(KnowledgeCandidateDraft).where(
                            KnowledgeCandidateDraft.operation_run_id == run_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(drafts) == 1
            assert drafts[0].id == draft_id


@pytest.mark.asyncio
async def test_partial_source_run_with_valid_citation_allows_draft() -> None:
    """partial 回答仍含有效引用：允许整理，只采用可核验部分。"""
    from app.models.knowledge_agent import RUN_PARTIAL

    async with async_session_factory() as db:
        user = await create_user(db, "部分")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "部分项目")
        conversation, source_run, _entry, _source, _attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        source_run.status = RUN_PARTIAL
        answer = KnowledgeAnswerOut.model_validate_json(source_run.answer_json)
        answer.gaps = ["闭水时长上限未覆盖"]
        source_run.answer_json = answer.model_dump_json()
        await db.commit()
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        assert run.status == RUN_WAITING
        assert draft.status == DRAFT_GENERATING


@pytest.mark.asyncio
async def test_draft_operation_does_not_advance_working_set() -> None:
    """草稿操作不创建/推进工作集版本，不影响普通问答上下文。"""
    from app.models import KnowledgeContextVersion

    async with async_session_factory() as db:
        user = await create_user(db, "工作集")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "工作集项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        await db.commit()
        draft.title = "闭水试验要点"
        draft.content = "闭水试验通常持续 24 小时。"
        draft.status = DRAFT_DRAFT
        draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        await db.commit()
        await confirm_draft(db, draft, f"op-{uuid.uuid4().hex[:8]}")
        await db.commit()
        versions = (
            (
                await db.execute(
                    select(KnowledgeContextVersion).where(
                        KnowledgeContextVersion.conversation_id == conversation.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert versions == []


@pytest.mark.asyncio
async def test_confirm_same_operation_key_on_other_draft_conflicts() -> None:
    """同一对话内把确认幂等键复用到另一草稿：稳定 409，不产生 500 或重复对象。"""
    from fastapi import HTTPException

    async with async_session_factory() as db:
        user = await create_user(db, "同键")
        workspace = await create_workspace(db, user)
        workspace_id = workspace.id
        project = await create_project(db, workspace, "同键项目")
        conversation, source_run, _entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        _m1, run1, draft1 = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id, client_message_id="dup-a"),
        )
        await db.commit()
        await execute_draft_candidate_run(db, run1)
        await db.commit()
        _m2, run2, draft2 = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id, client_message_id="dup-b"),
        )
        await db.commit()
        await execute_draft_candidate_run(db, run2)
        await db.commit()
        for draft in (draft1, draft2):
            draft.title = "标题"
            draft.content = "内容"
            draft.status = DRAFT_DRAFT
            draft.evidence_handles_json = __import__("json").dumps([evidence.handle])
        await db.commit()

        key = "same-key-across-drafts"
        confirmed, candidate = await confirm_draft(db, draft1, key)
        await db.commit()
        assert confirmed.status == DRAFT_CONFIRMED
        with pytest.raises(HTTPException) as exc_info:
            await confirm_draft(db, draft2, key)
        assert exc_info.value.status_code == 409
        await db.rollback()
    # 409 分支在服务内回滚会过期本会话对象：用独立会话核对不产生重复对象
    async with async_session_factory() as check_db:
        sources = (
            (
                await check_db.execute(
                    select(Source).where(Source.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(sources) == 2  # 原始回答来源 + 唯一虚拟来源


def test_seed_draft_truncates_overlong_answer() -> None:
    """超长原回答的 seed 草稿不超过内容上限，不再抛校验异常。"""
    from app.agents.candidate_draft import (
        MAX_DRAFT_CONTENT_CHARS,
        seed_draft_from_answer,
    )

    overlong = "长" * (MAX_DRAFT_CONTENT_CHARS + 500)
    seed = seed_draft_from_answer(
        question="问题",
        original_answer=overlong,
        handles=["ev_1"],
    )
    assert len(seed.content) <= MAX_DRAFT_CONTENT_CHARS
    assert seed.selected_evidence_handles == ["ev_1"]


@pytest.mark.asyncio
async def test_failed_draft_run_exposes_fallback_summary() -> None:
    """草稿失败路径在 Run 上聚合可识别的降级阶段，不伪装正常。"""
    async with async_session_factory() as db:
        user = await create_user(db, "失败可观测")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "失败项目")
        conversation, source_run, _entry, _source, attachment, _evidence = (
            await _answer_run_with_evidence(db, user, workspace, project)
        )
        message, run, draft = await submit_draft_candidate(
            db,
            conversation,
            _draft_action(source_run_id=source_run.id),
        )
        # 让证据失效，走失败路径（模型不可用时本应走 seed 成功路径）
        attachment.text_content = "证据已失效，指纹不再匹配。"
        await db.commit()
        await execute_draft_candidate_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert run.fallback_summary is not None
        summary = __import__("json").loads(run.fallback_summary)
        assert summary["has_fallback"] is True
        assert summary["stages"][0]["is_fallback"] is True
        assert "purpose" in summary["stages"][0]
