"""知识 Agent 单 Entry 修订：目标校验、Evidence 约束、提交、执行、编辑与取消。"""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import (
    EntrySourceEvidence,
    EntryVersion,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeEntryRevisionDraft,
    KnowledgeEntryRevisionExecution,
    KnowledgeMessage,
    Node,
    Project,
    User,
    Workspace,
)
from app.models.knowledge_agent import (
    REVISION_DRAFT_CANCELLED,
    REVISION_DRAFT_DRAFT,
    REVISION_DRAFT_FAILED,
    REVISION_DRAFT_GENERATING,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_KIND_ANSWER,
    RUN_KIND_ENTRY_REVISION,
    RUN_PARTIAL,
    RUN_PROCESSING,
    RUN_WAITING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeRevisionActionRequest,
    KnowledgeRevisionDraftEditRequest,
    KnowledgeRunCitationOut,
)
from app.services.knowledge_agent.entry_revision import (
    cancel_revision_draft,
    confirm_entry_revision,
    edit_revision_draft,
    execute_entry_revision_run,
    submit_entry_revision,
    undo_entry_revision,
)
from app.services.knowledge_agent.evidence import attachment_fingerprint
from app.services.knowledge_agent.observability import StageMeta
from tests._knowledge_agent_fixtures import (
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)

QUOTE = "闭水期间应持续观察水位变化，并到楼下检查顶面是否出现渗漏。"
CONTENT = "闭水试验完成后再验收防水层。"


async def _draft_to_ready(
    db,
    draft: KnowledgeEntryRevisionDraft,
    evidence: KnowledgeAgentEvidence,
    *,
    title: str = "闭水试验完成后再验收防水层（含适用条件）",
    content: str = CONTENT + "闭水期间同时观察水位与楼下顶面。",
) -> None:
    """把 generating 草稿推进到可确认的 draft 状态（模拟生成完成）。"""
    draft.status = REVISION_DRAFT_DRAFT
    draft.title = title
    draft.content = content
    draft.main_type = "method"
    draft.info_nature = "advice"
    draft.applicable_condition = "材料说明未覆盖时按现场条件确认"
    draft.change_summary = "补充适用条件与观察要求"
    draft.reason = "依据防水验收记录原文"
    draft.selected_evidence_handles_json = json.dumps([evidence.handle])
    await db.flush()


def _action(
    *,
    source_run_id: int,
    target_entry_id: int,
    instruction: str = "补充适用条件与验收步骤",
    client_message_id: str | None = None,
) -> KnowledgeRevisionActionRequest:
    return KnowledgeRevisionActionRequest(
        client_message_id=client_message_id or f"rev-{uuid.uuid4().hex[:12]}",
        source_run_id=source_run_id,
        target_entry_id=target_entry_id,
        instruction=instruction,
    )


async def _answer_run_with_evidence(
    db,
    user: User,
    workspace: Workspace,
    *,
    conversation: KnowledgeConversation | None = None,
    status: str = RUN_COMPLETED,
) -> tuple[
    KnowledgeConversation,
    KnowledgeAgentRun,
    object,
    object,
    object,
    KnowledgeAgentEvidence,
]:
    """创建带最终引用 Evidence 的来源回答 Run。"""
    if conversation is None:
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="修订测试对话",
        )
        db.add(conversation)
        await db.flush()
    project = await create_project(db, workspace, "防水项目")
    node = (
        await db.execute(
            select(Node)
            .where(Node.project_id == project.id, Node.parent_id.is_(None))
            .limit(1)
        )
    ).scalar_one()
    source, attachment = await create_source_attachment(
        db,
        workspace,
        project,
        title="防水验收记录.md",
        text_content=QUOTE,
    )
    entry = await create_entry_with_evidence(
        db,
        project,
        node,
        source,
        attachment,
        title="闭水试验完成后再验收防水层",
        content=CONTENT,
        quote=QUOTE,
    )
    run = KnowledgeAgentRun(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_PROJECT,
        project_id=project.id,
        project_name=project.name,
        status=status,
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
        quote=QUOTE,
        content_fingerprint=attachment_fingerprint(QUOTE),
        purpose="answer",
        is_citable=True,
    )
    db.add(evidence)
    await db.flush()
    answer = KnowledgeAnswerOut(
        answer=f"现有知识已确认：{CONTENT}",
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
                quote=QUOTE,
                project_id=project.id,
                project_name=project.name,
                node_path="根",
            )
        ],
    )
    run.answer_json = answer.model_dump_json()
    await db.flush()
    return conversation, run, entry, source, attachment, evidence


@pytest.mark.asyncio
async def test_submit_revision_success_creates_visible_message_run_draft() -> None:
    """合法修订请求创建可见用户消息、entry_revision Run 与 generating Draft。"""
    async with async_session_factory() as db:
        user = await create_user(db, "提交")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        await db.commit()

        message, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()

        assert message.role == "user"
        assert "修订《闭水试验完成后再验收防水层》" in message.content
        assert run.run_kind == RUN_KIND_ENTRY_REVISION
        assert run.source_run_id == source_run.id
        assert run.target_entry_id == entry.id
        assert run.status == RUN_WAITING
        assert draft.status == REVISION_DRAFT_GENERATING
        assert draft.target_entry_id == entry.id
        assert evidence.handle in draft.allowed_evidence_handles_json
        assert draft.base_entry_fingerprint
        assert draft.instruction == "补充适用条件与验收步骤"


@pytest.mark.asyncio
async def test_submit_revision_idempotent_replay() -> None:
    """同一 client_message_id 重放返回首次对象，不创建重复消息或 Run。"""
    async with async_session_factory() as db:
        user = await create_user(db, "幂等")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        payload = _action(source_run_id=source_run.id, target_entry_id=entry.id)
        first = await submit_entry_revision(db, conversation, payload)
        await db.commit()

        second = await submit_entry_revision(db, conversation, payload)
        await db.commit()
        assert second[0].id == first[0].id
        assert second[1].id == first[1].id
        assert second[2].id == first[2].id
        messages = (
            await db.execute(
                select(KnowledgeMessage).where(
                    KnowledgeMessage.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert len(messages) == 2  # 用户消息 + 助手占位


@pytest.mark.asyncio
async def test_submit_revision_requires_non_empty_instruction() -> None:
    """空指令被拒绝，不创建任何对象。"""
    async with async_session_factory() as db:
        user = await create_user(db, "空指令")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        payload = _action(
            source_run_id=source_run.id,
            target_entry_id=entry.id,
            instruction="   ",
        )
        with pytest.raises(HTTPException) as exc:
            await submit_entry_revision(db, conversation, payload)
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_submit_revision_rejects_target_not_in_final_citations() -> None:
    """目标未出现在最终引用中时拒绝且不创建 Draft。"""
    async with async_session_factory() as db:
        user = await create_user(db, "未引用")
        workspace = await create_workspace(db, user)
        conversation, source_run, _entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        other_project = await create_project(db, workspace, "其他项目")
        other_node = (
            await db.execute(
                select(Node)
                .where(Node.project_id == other_project.id, Node.parent_id.is_(None))
                .limit(1)
            )
        ).scalar_one()
        other_source, other_attachment = await create_source_attachment(
            db, workspace, other_project, title="其他来源", text_content="其他内容"
        )
        other_entry = await create_entry_with_evidence(
            db,
            other_project,
            other_node,
            other_source,
            other_attachment,
            title="未引用知识",
        )
        payload = _action(
            source_run_id=source_run.id,
            target_entry_id=other_entry.id,
        )
        with pytest.raises(HTTPException) as exc:
            await submit_entry_revision(db, conversation, payload)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_revision_rejects_cross_workspace_target() -> None:
    """其他 Workspace 的 target Entry 一律 404。"""
    async with async_session_factory() as db:
        user = await create_user(db, "越权")
        workspace = await create_workspace(db, user)
        conversation, source_run, _entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        other_user = await create_user(db, "他人")
        other_workspace = await create_workspace(db, other_user)
        other_project = await create_project(db, other_workspace, "他人项目")
        other_node = (
            await db.execute(
                select(Node)
                .where(Node.project_id == other_project.id, Node.parent_id.is_(None))
                .limit(1)
            )
        ).scalar_one()
        other_source, other_attachment = await create_source_attachment(
            db, other_workspace, other_project, title="他人来源", text_content="他人内容"
        )
        other_entry = await create_entry_with_evidence(
            db,
            other_project,
            other_node,
            other_source,
            other_attachment,
            title="他人知识",
        )
        payload = _action(
            source_run_id=source_run.id,
            target_entry_id=other_entry.id,
        )
        with pytest.raises(HTTPException) as exc:
            await submit_entry_revision(db, conversation, payload)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_revision_rejects_stale_evidence() -> None:
    """证据内容变化后当前无法核验，提交返回 409 且不创建 Draft。"""
    async with async_session_factory() as db:
        user = await create_user(db, "失效证据")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, attachment, _e = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        attachment.text_content = "来源内容已被修改，原文不再可核验。"
        await db.flush()

        payload = _action(source_run_id=source_run.id, target_entry_id=entry.id)
        with pytest.raises(HTTPException) as exc:
            await submit_entry_revision(db, conversation, payload)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_revision_rejects_active_run_conflict() -> None:
    """对话存在活动 Run 时返回 409，不创建第二个活动 Run。"""
    async with async_session_factory() as db:
        user = await create_user(db, "活动冲突")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        active = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot="active",
            max_retries=1,
        )
        db.add(active)
        await db.flush()

        payload = _action(source_run_id=source_run.id, target_entry_id=entry.id)
        with pytest.raises(HTTPException) as exc:
            await submit_entry_revision(db, conversation, payload)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_submit_revision_accepts_partial_answer_with_valid_citations() -> None:
    """partial 回答仍含有效引用时可发起修订。"""
    async with async_session_factory() as db:
        user = await create_user(db, "部分回答")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace, status=RUN_PARTIAL
        )
        message, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        assert run.run_kind == RUN_KIND_ENTRY_REVISION
        assert draft.status == REVISION_DRAFT_GENERATING


@pytest.mark.asyncio
async def test_plain_answer_submit_does_not_create_revision_draft() -> None:
    """普通问答提交不创建修订草稿（只读语义）。"""
    async with async_session_factory() as db:
        user = await create_user(db, "普通问答")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        db.add(
            KnowledgeMessage(
                conversation_id=conversation.id,
                role="user",
                message_type="user",
                content="这条知识需要修改吗？",
                client_message_id="plain-1",
                scope_type=SCOPE_WORKSPACE,
            )
        )
        await db.flush()
        drafts = (
            await db.execute(
                select(KnowledgeEntryRevisionDraft).where(
                    KnowledgeEntryRevisionDraft.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert drafts == []


@pytest.mark.asyncio
async def test_execute_revision_run_generates_draft(monkeypatch) -> None:
    """合法模型输出生成可编辑草稿并原子终态提交。"""
    from app.agents.entry_revision import EntryRevisionOutput

    captured: dict = {}

    async def _fake_agent(
        db,
        workspace_id,
        *,
        entry,
        instruction,
        question,
        original_answer,
        evidences,
    ):
        captured["handles"] = sorted(item["handle"] for item in evidences)
        return (
            EntryRevisionOutput(
                title="闭水试验完成后再验收防水层（含适用条件）",
                content=CONTENT + "闭水期间同时观察水位与楼下顶面。",
                main_type="method",
                info_nature="advice",
                applicable_condition="材料说明与施工方案未覆盖时按现场条件确认",
                note=None,
                change_summary="补充适用条件与观察要求",
                reason="依据防水验收记录原文",
                selected_evidence_handles=captured["handles"],
            ),
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model="fake-model",
                is_fallback=False,
                error=None,
                duration_ms=10,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_revision.run_entry_revision_agent",
        _fake_agent,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "生成")
        workspace = await create_workspace(db, user)
        conversation, source_run, _entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        message, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=_entry.id),
        )
        await db.commit()

        run.status = RUN_PROCESSING
        run.active_slot = "active"
        await db.commit()
        await execute_entry_revision_run(db, run)
        await db.commit()

        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_COMPLETED
        assert run.active_slot is None
        assert draft.status == REVISION_DRAFT_DRAFT
        assert draft.title.startswith("闭水试验完成后再验收防水层")
        assert evidence.handle in draft.selected_evidence_handles_json
        assert draft.change_summary == "补充适用条件与观察要求"


@pytest.mark.asyncio
async def test_execute_revision_run_rejects_unknown_handle(monkeypatch) -> None:
    """模型混入未知句柄时丢弃，剩余句柄为空则草稿失败。"""
    from app.agents.entry_revision import EntryRevisionOutput

    async def _fake_agent(db, workspace_id, **kwargs):
        return (
            EntryRevisionOutput(
                title="新标题",
                content="新内容",
                main_type="knowledge",
                info_nature=None,
                applicable_condition=None,
                note=None,
                change_summary="改写",
                reason="依据证据",
                selected_evidence_handles=["ev_unknown"],
            ),
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=5,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_revision.run_entry_revision_agent",
        _fake_agent,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "未知句柄")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        await db.commit()

        await execute_entry_revision_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert draft.status == REVISION_DRAFT_FAILED
        assert "未返回任何有效证据句柄" in (draft.error or "")


@pytest.mark.asyncio
async def test_execute_revision_run_fails_when_model_unavailable() -> None:
    """未配置模型时不生成伪草稿，Run/Draft 进入失败且可重试。"""
    async with async_session_factory() as db:
        user = await create_user(db, "模型不可用")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        await db.commit()

        await execute_entry_revision_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert draft.status == REVISION_DRAFT_FAILED
        assert draft.generation_meta_json
        assert "未配置文本模型密钥" in (draft.error or "")


@pytest.mark.asyncio
async def test_execute_revision_run_fails_when_no_actual_change(monkeypatch) -> None:
    """归一化后与基线一致时不生成可执行草稿。"""
    from app.agents.entry_revision import EntryRevisionOutput

    async def _fake_agent(db, workspace_id, **kwargs):
        handles = [item["handle"] for item in kwargs["evidences"]]
        return (
            EntryRevisionOutput(
                title="闭水试验完成后再验收防水层",
                content=CONTENT,
                main_type="knowledge",
                info_nature=None,
                applicable_condition=None,
                note=None,
                change_summary="无变化",
                reason="无变化",
                selected_evidence_handles=handles,
            ),
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=5,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_revision.run_entry_revision_agent",
        _fake_agent,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "无差异")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        await db.commit()

        await execute_entry_revision_run(db, run)
        await db.commit()
        await db.refresh(run)
        await db.refresh(draft)
        assert run.status == RUN_FAILED
        assert "没有实际差异" in (draft.error or "")


@pytest.mark.asyncio
async def test_execute_revision_run_cancelled_before_generate(monkeypatch) -> None:
    """取消请求在步骤边界命中：Run/Draft 进入 cancelled，不提交模型结果。"""
    async with async_session_factory() as db:
        user = await create_user(db, "取消生成")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        run.cancel_requested = True
        await db.commit()

        # 直接执行会在首个取消边界抛出 RunCancelled；这里验证取消标志使执行器停止
        from app.services.knowledge_agent.runner import RunCancelled

        with pytest.raises(RunCancelled):
            await execute_entry_revision_run(db, run)


@pytest.mark.asyncio
async def test_execute_revision_evidence_excludes_uncited_run_evidence(
    monkeypatch,
) -> None:
    """允许集合只含最终采用 Evidence，不含回答未采用的整轮证据。"""
    from app.agents.entry_revision import EntryRevisionOutput

    captured: dict = {}

    async def _fake_agent(db, workspace_id, **kwargs):
        captured["handles"] = sorted(item["handle"] for item in kwargs["evidences"])
        return (
            EntryRevisionOutput(
                title="新标题",
                content="新内容",
                main_type="knowledge",
                info_nature=None,
                applicable_condition=None,
                note=None,
                change_summary="改写",
                reason="依据证据",
                selected_evidence_handles=captured["handles"],
            ),
            StageMeta(
                purpose="entry_revision",
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=5,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_revision.run_entry_revision_agent",
        _fake_agent,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "证据边界")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, cited = await _answer_run_with_evidence(
            db, user, workspace
        )
        # 添加一条回答未采用的本 Run 证据（整轮证据）
        uncited = KnowledgeAgentEvidence(
            run_id=source_run.id,
            handle=f"ev_uncited_{uuid.uuid4().hex[:8]}",
            entry_id=entry.id,
            project_id=entry.project_id,
            source_id=cited.source_id,
            attachment_id=cited.attachment_id,
            entry_title=entry.title,
            quote="未采用内容",
            content_fingerprint="fp-uncited",
            purpose="answer",
            is_citable=True,
        )
        db.add(uncited)
        await db.flush()

        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await db.commit()
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        await db.commit()
        await execute_entry_revision_run(db, run)
        await db.commit()

        assert captured["handles"] == [cited.handle]
        assert uncited.handle not in captured["handles"]
        assert uncited.handle not in (draft.allowed_evidence_handles_json or "")


@pytest.mark.asyncio
async def test_edit_revision_draft_updates_fields_and_recomputes_diff() -> None:
    """编辑允许字段并返回服务端按基线计算的字段差异。"""
    async with async_session_factory() as db:
        user = await create_user(db, "编辑")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        draft.status = REVISION_DRAFT_DRAFT
        draft.title = "候选标题"
        draft.content = "候选内容"
        await db.flush()

        await edit_revision_draft(
            db,
            draft,
            KnowledgeRevisionDraftEditRequest(
                title="编辑后的标题",
                content="编辑后的内容",
                applicable_condition="仅南方潮湿地区",
                change_summary="按用户要求改写",
            ),
        )
        await db.commit()
        await db.refresh(draft)
        from app.services.knowledge_agent.entry_revision import (
            changed_fields_for_draft,
        )

        diffs = changed_fields_for_draft(draft)
        by_field = {diff.field: diff for diff in diffs}
        assert by_field["title"].after == "编辑后的标题"
        assert by_field["content"].after == "编辑后的内容"
        assert by_field["applicable_condition"].after == "仅南方潮湿地区"
        assert draft.change_summary == "按用户要求改写"


@pytest.mark.asyncio
async def test_edit_revision_draft_rejects_unknown_fields() -> None:
    """受保护字段（target/source/base/Evidence）不在编辑 schema 内，拒绝请求。"""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        KnowledgeRevisionDraftEditRequest(
            title="新标题",
            target_entry_id=999,
            base_entry_fingerprint="forged",
        )


@pytest.mark.asyncio
async def test_edit_applied_revision_draft_rejected() -> None:
    """applied 草稿不可编辑。"""
    async with async_session_factory() as db:
        user = await create_user(db, "已应用编辑")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        draft.status = "applied"
        await db.flush()
        with pytest.raises(HTTPException) as exc:
            await edit_revision_draft(
                db,
                draft,
                KnowledgeRevisionDraftEditRequest(title="新标题"),
            )
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_revision_draft_and_applied_rejected() -> None:
    """draft 可取消；applied 不可取消；cancelled 重入幂等。"""
    async with async_session_factory() as db:
        user = await create_user(db, "取消修订")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, _e = await _answer_run_with_evidence(
            db, user, workspace
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        draft.status = REVISION_DRAFT_DRAFT
        await db.flush()

        await cancel_revision_draft(db, draft)
        assert draft.status == REVISION_DRAFT_CANCELLED
        await cancel_revision_draft(db, draft)
        assert draft.status == REVISION_DRAFT_CANCELLED

        applied_draft = KnowledgeEntryRevisionDraft(
            workspace_id=conversation.workspace_id,
            owner_user_id=conversation.owner_user_id,
            conversation_id=conversation.id,
            operation_run_id=_run.id + 1,
            instruction="已应用",
            base_entry_json="{}",
            base_entry_fingerprint="fp",
            status="applied",
        )
        db.add(applied_draft)
        await db.flush()
        with pytest.raises(HTTPException) as exc:
            await cancel_revision_draft(db, applied_draft)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_confirm_applies_entry_version_evidence_and_execution() -> None:
    """确认后原子更新 Entry、追加 knowledge_agent_revision 版本、去重补证据并创建 Execution。"""
    async with async_session_factory() as db:
        user = await create_user(db, "确认应用")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        entry_id = entry.id
        before_version_number = 0

        confirmed, execution, applied_entry = await confirm_entry_revision(
            db, draft, "confirm-1"
        )
        await db.commit()

        assert confirmed.status == "applied"
        assert execution.status == "applied"
        assert execution.entry_id == entry_id
        assert execution.after_version_number == before_version_number + 1
        assert execution.before_fingerprint == draft.base_entry_fingerprint
        assert applied_entry.title == "闭水试验完成后再验收防水层（含适用条件）"

        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry_id)
            )
        ).scalars().all()
        assert len(versions) == 1
        assert versions[0].change_type == "knowledge_agent_revision"
        assert versions[0].change_summary == "补充适用条件与观察要求"

        relations = (
            await db.execute(
                select(EntrySourceEvidence).where(
                    EntrySourceEvidence.entry_id == entry_id
                )
            )
        ).scalars().all()
        # 提交时 Entry 已带一条证据；采用证据等价已存在 → 去重复用，新增数为 0
        assert len(relations) == 1
        assert execution.added_evidence_ids_json == "[]"


@pytest.mark.asyncio
async def test_confirm_idempotent_replay() -> None:
    """同一 client_operation_id 重放返回同一 Execution，不重复追加版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "确认幂等")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()

        first = await confirm_entry_revision(db, draft, "confirm-dup")
        await db.commit()
        second = await confirm_entry_revision(db, draft, "confirm-dup")
        await db.commit()
        assert second[1].id == first[1].id
        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry.id)
            )
        ).scalars().all()
        assert len(versions) == 1


@pytest.mark.asyncio
async def test_confirm_rejects_expired_baseline_and_restores_editable() -> None:
    """Entry 在草稿生成后被修改：确认返回 409，草稿恢复可编辑，不覆盖新内容。"""
    async with async_session_factory() as db:
        user = await create_user(db, "基线过期")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        entry.content = "用户稍后人工修改了内容。"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await confirm_entry_revision(db, draft, "confirm-expired")
        assert exc.value.status_code == 409
        assert "知识后来发生了变化" in exc.value.detail
        await db.refresh(draft)
        assert draft.status == REVISION_DRAFT_DRAFT
        assert draft.client_operation_id is None
        executions = (
            await db.execute(
                select(KnowledgeEntryRevisionExecution).where(
                    KnowledgeEntryRevisionExecution.draft_id == draft.id
                )
            )
        ).scalars().all()
        assert executions == []


@pytest.mark.asyncio
async def test_confirm_rejects_stale_evidence_and_restores_editable() -> None:
    """确认前 Evidence 失效：409 且不修改 Entry。"""
    async with async_session_factory() as db:
        user = await create_user(db, "确认证据失效")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        attachment.text_content = "来源内容已被修改，原文不再可核验。"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await confirm_entry_revision(db, draft, "confirm-evidence")
        assert exc.value.status_code == 409
        assert "来源证据当前无法核验" in exc.value.detail
        await db.refresh(draft)
        assert draft.status == REVISION_DRAFT_DRAFT
        assert draft.execution_id is None


@pytest.mark.asyncio
async def test_confirm_rejects_no_actual_change_without_empty_version() -> None:
    """候选与基线无实际差异：409、不追加空版本、不创建 Execution。"""
    async with async_session_factory() as db:
        user = await create_user(db, "确认无差异")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        # 候选字段与基线一致（仅 change_summary 不同不构成 Entry 字段变化）
        await _draft_to_ready(
            db,
            draft,
            evidence,
            title="闭水试验完成后再验收防水层",
            content=CONTENT,
        )
        draft.main_type = "knowledge"
        draft.info_nature = None
        draft.applicable_condition = None
        draft.note = None
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await confirm_entry_revision(db, draft, "confirm-noop")
        assert exc.value.status_code == 409
        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry.id)
            )
        ).scalars().all()
        assert versions == []
        executions = (
            await db.execute(
                select(KnowledgeEntryRevisionExecution).where(
                    KnowledgeEntryRevisionExecution.draft_id == draft.id
                )
            )
        ).scalars().all()
        assert executions == []


@pytest.mark.asyncio
async def test_confirm_adds_only_missing_evidence_and_keeps_existing() -> None:
    """确认补入尚未关联的真实来源；已有等价关系复用，不记录为新增。"""
    async with async_session_factory() as db:
        user = await create_user(db, "证据增量")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, source, attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        # 目标 Entry 目前只有另一条来源：构造第二条来源的 Evidence 并加入回答引用
        project = await db.get(Project, entry.project_id)
        second_source, second_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="监理检查清单.md",
            text_content="地漏、管根和门槛石周边应逐项检查。",
        )
        second_quote = "地漏、管根和门槛石周边应逐项检查。"
        second_evidence = KnowledgeAgentEvidence(
            run_id=source_run.id,
            handle=f"ev_second_{uuid.uuid4().hex[:8]}",
            entry_id=entry.id,
            project_id=project.id,
            source_id=second_source.id,
            attachment_id=second_attachment.id,
            entry_title=entry.title,
            project_name=project.name,
            source_title=second_source.title,
            quote=second_quote,
            content_fingerprint=attachment_fingerprint(second_quote),
            purpose="answer",
            is_citable=True,
        )
        db.add(second_evidence)
        await db.flush()
        # 回答引用加入第二条来源（重新生成 answer_json）
        answer = KnowledgeAnswerOut(
            answer="现有知识已确认；请补充易渗漏位置检查。",
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
                    quote=QUOTE,
                    project_id=project.id,
                    project_name=project.name,
                    node_path="根",
                ),
                KnowledgeRunCitationOut(
                    evidence_id=second_evidence.id,
                    evidence_handle=second_evidence.handle,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    source_id=second_source.id,
                    source_title=second_source.title,
                    attachment_id=second_attachment.id,
                    quote=second_quote,
                    project_id=project.id,
                    project_name=project.name,
                    node_path="根",
                ),
            ],
        )
        source_run.answer_json = answer.model_dump_json()
        await db.flush()

        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        # 候选采用第二条来源；目标 Entry 尚无该来源关系
        await _draft_to_ready(db, draft, second_evidence)
        await db.commit()

        confirmed, execution, _applied = await confirm_entry_revision(
            db, draft, "confirm-second"
        )
        await db.commit()

        relations = (
            await db.execute(
                select(EntrySourceEvidence).where(
                    EntrySourceEvidence.entry_id == entry.id
                )
            )
        ).scalars().all()
        assert len(relations) == 2  # 既有 + 新增
        added = execution.added_evidence_ids_json
        assert added != "[]"
        assert str(relations[1].id) in added or str(relations[0].id) in added


@pytest.mark.asyncio
async def test_confirm_transaction_failure_rolls_back(monkeypatch) -> None:
    """应用阶段任一步失败整体回滚：不产生版本、Execution 或证据残留。"""
    async with async_session_factory() as db:
        user = await create_user(db, "事务回滚")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        entry_id = entry.id
        draft_id = draft.id

        async def _boom(db, entry, **kwargs):
            raise RuntimeError("模拟数据库写入失败")

        monkeypatch.setattr(
            "app.services.knowledge_agent.entry_revision.apply_knowledge_agent_revision",
            _boom,
        )
        with pytest.raises(RuntimeError):
            await confirm_entry_revision(db, draft, "confirm-fail")
        await db.rollback()
        await db.commit()

        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry_id)
            )
        ).scalars().all()
        assert versions == []
        executions = (
            await db.execute(
                select(KnowledgeEntryRevisionExecution).where(
                    KnowledgeEntryRevisionExecution.draft_id == draft_id
                )
            )
        ).scalars().all()
        assert executions == []


@pytest.mark.asyncio
async def test_desktop_entry_edit_still_works_after_revision_flow() -> None:
    """既有桌面 Entry 编辑与版本语义不受修订流程影响。"""
    async with async_session_factory() as db:
        user = await create_user(db, "桌面兼容")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        confirmed, _execution, _applied = await confirm_entry_revision(
            db, draft, "confirm-desktop"
        )
        await db.commit()

        from app.schemas.entry import EntryUpdate
        from app.services.entry import edit_entry

        await edit_entry(
            db,
            entry,
            EntryUpdate(title="桌面编辑后的标题"),
        )
        await db.commit()
        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry.id)
            )
        ).scalars().all()
        change_types = [version.change_type for version in versions]
        assert "knowledge_agent_revision" in change_types
        assert "edited" in change_types


@pytest.mark.asyncio
async def test_confirm_concurrent_second_request_replays_same_execution() -> None:
    """并发确认同一草稿：第二个请求返回同一 Execution，不重复追加版本。"""
    async with async_session_factory() as db_a:
        user = await create_user(db_a, "并发确认")
        workspace = await create_workspace(db_a, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db_a, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db_a,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db_a, draft, evidence)
        await db_a.commit()
        draft_id = draft.id
        entry_id = entry.id

        first, execution_a, _entry_a = await confirm_entry_revision(
            db_a, draft, "concurrent-key"
        )
        await db_a.commit()

        async with async_session_factory() as db_b:
            stale = await db_b.get(KnowledgeEntryRevisionDraft, draft_id)
            second, execution_b, _entry_b = await confirm_entry_revision(
                db_b, stale, "concurrent-key"
            )
            await db_b.commit()
            assert execution_b.id == execution_a.id
            assert second.status == "applied"

        versions = (
            await db_a.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry_id)
            )
        ).scalars().all()
        assert len(versions) == 1


@pytest.mark.asyncio
async def test_confirm_records_tool_call_observability() -> None:
    """确认工具调用记录真实状态、版本与 Evidence 增量，不掩盖失败。"""
    from app.models import KnowledgeAgentToolCall

    async with async_session_factory() as db:
        user = await create_user(db, "可观测")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()

        await confirm_entry_revision(db, draft, "confirm-obs")
        await db.commit()
        calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id
                )
            )
        ).scalars().all()
        confirm_calls = [call for call in calls if call.tool_name == "entry_revision_confirm"]
        assert len(confirm_calls) == 1
        assert confirm_calls[0].status == "ok"
        assert confirm_calls[0].result_summary
        assert "after_version_number" in (confirm_calls[0].result_summary or "")
        assert confirm_calls[0].error is None


@pytest.mark.asyncio
async def test_undo_restores_before_snapshot_and_appends_restored_version() -> None:
    """撤销恢复 before 快照、追加 restored 版本并标记 undone。"""
    async with async_session_factory() as db:
        user = await create_user(db, "撤销成功")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        applied, execution, applied_entry = await confirm_entry_revision(
            db, draft, "confirm-undo-1"
        )
        await db.commit()
        assert applied_entry.title.startswith("闭水试验完成后再验收防水层（含适用条件）")

        undone, undone_execution, restored_entry = await undo_entry_revision(
            db, draft, "undo-key-1"
        )
        await db.commit()

        assert undone.status == "undone"
        assert undone_execution.status == "undone"
        assert undone_execution.undone_at is not None
        assert restored_entry.title == "闭水试验完成后再验收防水层"
        assert restored_entry.content == CONTENT
        assert restored_entry.main_type == "knowledge"

        versions = (
            await db.execute(
                select(EntryVersion)
                .where(EntryVersion.entry_id == entry.id)
                .order_by(EntryVersion.version_number)
            )
        ).scalars().all()
        change_types = [version.change_type for version in versions]
        assert change_types == ["knowledge_agent_revision", "restored"]


@pytest.mark.asyncio
async def test_undo_idempotent_same_key_no_second_restored_version() -> None:
    """重复撤销返回同一结果，不追加第二个恢复版本。"""
    async with async_session_factory() as db:
        user = await create_user(db, "撤销幂等")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        await confirm_entry_revision(db, draft, "confirm-undo-2")
        await db.commit()

        first = await undo_entry_revision(db, draft, "undo-dup")
        await db.commit()
        second = await undo_entry_revision(db, draft, "undo-dup")
        await db.commit()
        assert second[1].id == first[1].id
        assert second[0].status == "undone"
        versions = (
            await db.execute(
                select(EntryVersion).where(EntryVersion.entry_id == entry.id)
            )
        ).scalars().all()
        restored = [v for v in versions if v.change_type == "restored"]
        assert len(restored) == 1


@pytest.mark.asyncio
async def test_undo_rejected_when_later_modification_exists() -> None:
    """Entry 在应用后又被修改：撤销返回 409，不覆盖新内容。"""
    async with async_session_factory() as db:
        user = await create_user(db, "撤销冲突")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        await confirm_entry_revision(db, draft, "confirm-undo-3")
        await db.commit()
        entry.content = "应用后的又一次人工编辑。"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await undo_entry_revision(db, draft, "undo-conflict")
        assert exc.value.status_code == 409
        assert "知识后来发生了变化" in exc.value.detail
        await db.refresh(draft)
        assert draft.status == "applied"
        execution = await db.get(
            KnowledgeEntryRevisionExecution, draft.execution_id
        )
        assert execution is not None
        assert execution.status == "applied"


@pytest.mark.asyncio
async def test_undo_deletes_only_own_added_evidence() -> None:
    """撤销只删除本操作新增且仍属目标 Entry 的 Evidence，保留既有与其他来源。"""
    async with async_session_factory() as db:
        user = await create_user(db, "撤销证据")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, source, _attachment, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        project = await db.get(Project, entry.project_id)
        # 目标 Entry 预置一条既有证据（不同于回答引用）
        pre_source, pre_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="既有来源.md",
            text_content="既有来源内容。",
        )
        pre_relation = EntrySourceEvidence(
            entry_id=entry.id,
            source_id=pre_source.id,
            attachment_id=pre_attachment.id,
            quote="既有来源内容。",
        )
        db.add(pre_relation)
        await db.flush()
        existing_ids_before = {
            row.id
            for row in (
                await db.execute(
                    select(EntrySourceEvidence).where(
                        EntrySourceEvidence.entry_id == entry.id
                    )
                )
            ).scalars().all()
        }

        # 回答引用指向第二条来源（目标 Entry 尚未关联）
        second_source, second_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="回答采用来源.md",
            text_content="回答采用的核验原文内容。",
        )
        second_quote = "回答采用的核验原文内容。"
        second_evidence = KnowledgeAgentEvidence(
            run_id=source_run.id,
            handle=f"ev_undo_{uuid.uuid4().hex[:8]}",
            entry_id=entry.id,
            project_id=project.id,
            source_id=second_source.id,
            attachment_id=second_attachment.id,
            entry_title=entry.title,
            project_name=project.name,
            source_title=second_source.title,
            quote=second_quote,
            content_fingerprint=attachment_fingerprint(second_quote),
            purpose="answer",
            is_citable=True,
        )
        db.add(second_evidence)
        await db.flush()
        answer = KnowledgeAnswerOut(
            answer="现有知识已确认；请补充核验原文。",
            status="completed",
            citations=[
                KnowledgeRunCitationOut(
                    evidence_id=second_evidence.id,
                    evidence_handle=second_evidence.handle,
                    entry_id=entry.id,
                    entry_title=entry.title,
                    source_id=second_source.id,
                    source_title=second_source.title,
                    attachment_id=second_attachment.id,
                    quote=second_quote,
                    project_id=project.id,
                    project_name=project.name,
                    node_path="根",
                )
            ],
        )
        source_run.answer_json = answer.model_dump_json()
        await db.flush()

        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, second_evidence)
        await db.commit()
        _applied, execution, _applied_entry = await confirm_entry_revision(
            db, draft, "confirm-undo-ev"
        )
        await db.commit()
        added_ids = __import__("json").loads(execution.added_evidence_ids_json or "[]")
        assert len(added_ids) == 1

        await undo_entry_revision(db, draft, "undo-ev-key")
        await db.commit()

        relations = (
            await db.execute(
                select(EntrySourceEvidence).where(
                    EntrySourceEvidence.entry_id == entry.id
                )
            )
        ).scalars().all()
        assert {relation.id for relation in relations} == existing_ids_before
        assert not any(relation.id in added_ids for relation in relations)


@pytest.mark.asyncio
async def test_undo_transaction_failure_keeps_applied(monkeypatch) -> None:
    """撤销事务中途失败整体回滚：Execution 保持 applied，可重试。"""
    async with async_session_factory() as db:
        user = await create_user(db, "撤销回滚")
        workspace = await create_workspace(db, user)
        conversation, source_run, entry, _s, _a, evidence = (
            await _answer_run_with_evidence(db, user, workspace)
        )
        _m, _run, draft = await submit_entry_revision(
            db,
            conversation,
            _action(source_run_id=source_run.id, target_entry_id=entry.id),
        )
        await _draft_to_ready(db, draft, evidence)
        await db.commit()
        await confirm_entry_revision(db, draft, "confirm-undo-fail")
        await db.commit()
        execution_id = draft.execution_id
        draft_id = draft.id

        async def _boom(db, entry, **kwargs):
            raise RuntimeError("模拟撤销写入失败")

        monkeypatch.setattr(
            "app.services.knowledge_agent.entry_revision.restore_entry_from_snapshot",
            _boom,
        )
        with pytest.raises(RuntimeError):
            await undo_entry_revision(db, draft, "undo-fail-key")
        await db.rollback()

        execution = await db.get(KnowledgeEntryRevisionExecution, execution_id)
        assert execution is not None
        assert execution.status == "applied"
        assert execution.undo_client_operation_id is None
        assert execution.undone_at is None
        fresh_draft = await db.get(KnowledgeEntryRevisionDraft, draft_id)
        assert fresh_draft is not None
        assert fresh_draft.status == "applied"
