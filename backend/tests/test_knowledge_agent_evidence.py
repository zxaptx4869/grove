"""Knowledge Agent Evidence 句柄与引用校验测试。"""

import pytest
from sqlalchemy import select

from app.agents.knowledge_agent import KnowledgeAnswerDraft, KnowledgeCitationDraft
from app.db.session import async_session_factory
from app.models import (
    EntrySourceEvidence,
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeConversation,
)
from app.models.knowledge_agent import RUN_PROCESSING
from app.services.knowledge_agent.evidence import (
    attachment_fingerprint,
    build_validated_answer,
    create_answer_evidence,
    locate_verified_quote,
    resolve_evidence_handles,
)
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


async def _evidence_row(
    db,
    *,
    run_id: int,
    entry,
    project,
    source,
    attachment,
    entry_evidence,
    quote: str,
) -> KnowledgeAgentEvidence:
    """直接创建一条核验过的 Evidence。"""
    verified = locate_verified_quote(attachment.text_content or "", quote)
    assert verified is not None
    return await create_answer_evidence(
        db,
        run_id=run_id,
        entry=entry,
        project_name=project.name,
        node_path="施工",
        evidence=entry_evidence,
        attachment=attachment,
        verified=verified,
    )


async def _entry_evidence(db, entry_id: int, source_id: int) -> EntrySourceEvidence:
    """读取 Entry 的来源证据行。"""
    return (
        await db.execute(
            select(EntrySourceEvidence).where(
                EntrySourceEvidence.entry_id == entry_id,
                EntrySourceEvidence.source_id == source_id,
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_resolve_handles_only_current_run() -> None:
    """句柄解析拒绝其他 Run 的句柄。"""
    async with async_session_factory() as db:
        user = await create_user(db, "句柄")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "句柄项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            quote="闭水试验通常持续 24 小时",
        )
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            title="句柄测试",
        )
        db.add(conversation)
        await db.flush()
        run_a = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            status=RUN_PROCESSING,
            active_slot="active",
            max_retries=1,
        )
        db.add(run_a)
        await db.flush()
        run_b = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            status=RUN_PROCESSING,
            active_slot=None,
            max_retries=1,
        )
        db.add(run_b)
        await db.flush()

        entry_evidence = await _entry_evidence(db, entry.id, source.id)
        evidence_a = await _evidence_row(
            db,
            run_id=run_a.id,
            entry=entry,
            project=project,
            source=source,
            attachment=attachment,
            entry_evidence=entry_evidence,
            quote="闭水试验通常持续 24 小时",
        )
        evidence_b = await _evidence_row(
            db,
            run_id=run_b.id,
            entry=entry,
            project=project,
            source=source,
            attachment=attachment,
            entry_evidence=entry_evidence,
            quote="闭水试验通常持续 24 小时",
        )
        await db.commit()

        resolved = await resolve_evidence_handles(
            db,
            run_a.id,
            [evidence_a.handle, evidence_b.handle, "ev_forged"],
        )
        assert set(resolved) == {evidence_a.handle}
        assert evidence_b.handle not in resolved


@pytest.mark.asyncio
async def test_build_validated_answer_drops_fake_handles_and_quotes() -> None:
    """最终回答只保留本 Run 可引用句柄，模型自由 quote 不进入响应。"""
    async with async_session_factory() as db:
        user = await create_user(db, "校验")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "校验项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时，且不得提前放水。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            quote="闭水试验通常持续 24 小时",
        )
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            title="校验测试",
        )
        db.add(conversation)
        await db.flush()
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            status=RUN_PROCESSING,
            active_slot="active",
            max_retries=1,
        )
        db.add(run)
        await db.flush()
        entry_evidence = await _entry_evidence(db, entry.id, source.id)
        evidence = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry,
            project=project,
            source=source,
            attachment=attachment,
            entry_evidence=entry_evidence,
            quote="闭水试验通常持续 24 小时",
        )
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="闭水试验通常持续 24 小时。",
            citations=[
                KnowledgeCitationDraft(evidence_handle=evidence.handle),
                KnowledgeCitationDraft(evidence_handle="ev_other_run"),
                KnowledgeCitationDraft(evidence_handle="ev_unknown"),
            ],
        )
        answer = await build_validated_answer(db, run.id, draft)
        assert len(answer.citations) == 1
        assert answer.citations[0].evidence_handle == evidence.handle
        # quote 必须是服务端核验过的原文，而不是模型提供的任何文本
        assert answer.citations[0].quote == "闭水试验通常持续 24 小时"
        assert answer.citations[0].entry_id == entry.id
        assert answer.citations[0].source_id == source.id
        assert answer.status == "completed"


@pytest.mark.asyncio
async def test_fingerprint_and_quote_verification() -> None:
    """内容指纹稳定；无法定位的 quote 返回 None。"""
    assert attachment_fingerprint("同一段文本") == attachment_fingerprint("同一段文本")
    assert attachment_fingerprint("A") != attachment_fingerprint("B")
    verified = locate_verified_quote("闭水试验 持续24小时。", "闭水试验持续24小时")
    assert verified is not None
    assert verified.text in "闭水试验 持续24小时。"
    assert locate_verified_quote("原文", "完全不同的内容") is None
