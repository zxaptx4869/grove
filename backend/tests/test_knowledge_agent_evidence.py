"""Knowledge Agent Evidence 句柄与引用校验测试。"""

import pytest
from sqlalchemy import select

from app.agents.knowledge_agent import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
    KnowledgeConflictDraft,
    KnowledgeEvidenceSummaryDraft,
)
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
    sanitize_answer_text,
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
    node_path: str = "施工",
) -> KnowledgeAgentEvidence:
    """直接创建一条核验过的 Evidence。"""
    verified = locate_verified_quote(attachment.text_content or "", quote)
    assert verified is not None
    return await create_answer_evidence(
        db,
        run_id=run_id,
        entry=entry,
        project_name=project.name,
        node_path=node_path,
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


def test_sanitize_answer_text_removes_leaked_handles() -> None:
    """正文中误写入的 ev_ 句柄（含括号包裹）会被清洗，正常内容保留。"""
    dirty = (
        "六种常见板材的结构与特点（ev_1c8f81ddf8e14cce87475e6af9df3c30）："
        "实木板整木裁切（ev_09d30d52bd184b33b901af05d687d113）"
        "欧松板稳定不易变形 ev_87dce3bbe7c2492ea76061fbd7b9104a。"
    )
    cleaned = sanitize_answer_text(dirty)
    assert "ev_" not in cleaned
    assert "六种常见板材的结构与特点" in cleaned
    assert "欧松板稳定不易变形" in cleaned
    assert "实木板整木裁切" in cleaned


def test_sanitize_answer_text_keeps_normal_text() -> None:
    """没有句柄的正文原样保留，不误伤内容。"""
    text = "ENF≤0.025mg/m³，国产正规品牌已足够安全。"
    assert sanitize_answer_text(text) == text


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
                KnowledgeCitationDraft(evidence_handle=evidence.handle),
                KnowledgeCitationDraft(evidence_handle="ev_other_run"),
                KnowledgeCitationDraft(evidence_handle="ev_unknown"),
            ],
        )
        answer, stats = await build_validated_answer(db, run.id, draft)
        assert len(answer.citations) == 1
        assert answer.citations[0].evidence_handle == evidence.handle
        # quote 必须是服务端核验过的原文，而不是模型提供的任何文本
        assert answer.citations[0].quote == "闭水试验通常持续 24 小时"
        assert answer.citations[0].entry_id == entry.id
        assert answer.citations[0].source_id == source.id
        # 部分句柄失效：保留有效引用并把回答标记为 partial
        assert answer.status == "partial"
        assert stats.requested_count == 3
        assert stats.valid_count == 1
        assert stats.discarded_count == 2


@pytest.mark.asyncio
async def test_build_validated_answer_keeps_only_evidence_linked_terminal_summary() -> None:
    """覆盖与缺口必须关联最终采用的 Evidence，重复句柄不夸大计数。"""
    async with async_session_factory() as db:
        user = await create_user(db, "终态摘要")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "摘要项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db, workspace, project, text_content="闭水试验通常持续 24 小时。"
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
            title="终态摘要测试",
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
        evidence = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry,
            project=project,
            source=source,
            attachment=attachment,
            entry_evidence=await _entry_evidence(db, entry.id, source.id),
            quote="闭水试验通常持续 24 小时",
        )
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="闭水试验通常持续 24 小时。",
            citations=[
                KnowledgeCitationDraft(evidence_handle=evidence.handle),
                KnowledgeCitationDraft(evidence_handle=evidence.handle),
            ],
            coverage=[
                KnowledgeEvidenceSummaryDraft(
                    summary="已覆盖闭水时长", evidence_handles=[evidence.handle]
                ),
                KnowledgeEvidenceSummaryDraft(
                    summary="模型自由覆盖结论", evidence_handles=["ev_unknown"]
                ),
            ],
            gaps=[
                KnowledgeEvidenceSummaryDraft(
                    summary="放水时机尚缺证据", evidence_handles=[evidence.handle]
                ),
                KnowledgeEvidenceSummaryDraft(
                    summary="不可验证缺口", evidence_handles=["ev_unknown"]
                ),
            ],
            coverage_complete=False,
        )
        answer, stats = await build_validated_answer(db, run.id, draft)

        assert answer.status == "partial"
        assert len(answer.citations) == 1
        assert stats.requested_count == 1
        assert answer.coverage == ["已覆盖闭水时长"]
        assert answer.gaps == ["放水时机尚缺证据"]

        missing_assessment, _ = await build_validated_answer(
            db,
            run.id,
            KnowledgeAnswerDraft(
                answer="闭水试验通常持续 24 小时。",
                citations=[KnowledgeCitationDraft(evidence_handle=evidence.handle)],
            ),
        )
        assert missing_assessment.status == "partial"
        assert missing_assessment.coverage == ["当前回答采用 1 条核验证据，涉及 1 条正式知识"]

        verified_missing, _ = await build_validated_answer(
            db,
            run.id,
            KnowledgeAnswerDraft(
                answer="闭水时长已有依据，但放水时机没有正式知识支持。",
                citations=[KnowledgeCitationDraft(evidence_handle=evidence.handle)],
                core_question_answered=True,
                coverage_complete=False,
                gaps=[
                    KnowledgeEvidenceSummaryDraft(
                        summary="放水时机缺少正式知识",
                        evidence_handles=[],
                    ),
                    KnowledgeEvidenceSummaryDraft(
                        summary="模型自由生成的缺口",
                        evidence_handles=[],
                    ),
                ],
            ),
            verifiable_gaps=["放水时机缺少正式知识"],
        )
        assert verified_missing.status == "partial"
        assert verified_missing.gaps == ["放水时机缺少正式知识"]


@pytest.mark.asyncio
async def test_build_validated_answer_all_invalid_becomes_insufficient() -> None:
    """事实性回答全部引用失效：不得保持 completed，标记 insufficient。"""
    async with async_session_factory() as db:
        user = await create_user(db, "全失效")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "失效项目")
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
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            title="全失效测试",
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
        await _evidence_row(
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
                KnowledgeCitationDraft(evidence_handle="ev_other_run"),
                KnowledgeCitationDraft(evidence_handle="ev_unknown"),
            ],
        )
        answer, stats = await build_validated_answer(db, run.id, draft)
        assert answer.status == "insufficient"
        assert answer.citations == []
        assert "全部引用被丢弃" in (answer.insufficient_note or "")
        assert stats.requested_count == 2
        assert stats.valid_count == 0
        assert stats.discarded_count == 2


@pytest.mark.asyncio
async def test_build_validated_answer_factual_without_any_citation() -> None:
    """事实性回答没有任何引用请求：同样降级为 insufficient。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无引用")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            title="无引用测试",
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
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="凭模型自身知识给出的结论。",
            citations=[],
        )
        answer, stats = await build_validated_answer(db, run.id, draft)
        assert answer.status == "insufficient"
        assert stats.requested_count == 0
        assert stats.valid_count == 0


@pytest.mark.asyncio
async def test_citation_snapshots_survive_object_deletion() -> None:
    """引用携带项目/目录快照；当前 Entry/Source 删除后历史快照仍可展示。"""
    async with async_session_factory() as db:
        user = await create_user(db, "快照")
        workspace = await create_workspace(db, user)
        project_a = await create_project(db, workspace, "项目甲")
        project_b = await create_project(db, workspace, "项目乙")
        node_a = await create_child_node(db, project_a, "施工")
        node_b = await create_child_node(db, project_b, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project_a,
            title="来源甲",
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project_b,
            title="来源乙",
            text_content="闭水试验建议观察 48 小时。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project_a,
            node_a,
            source_a,
            attachment_a,
            title="闭水 24 小时",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project_b,
            node_b,
            source_b,
            attachment_b,
            title="闭水 48 小时",
            content="闭水试验建议观察 48 小时。",
            quote="闭水试验建议观察 48 小时",
        )
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="workspace",
            title="快照测试",
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
        evidence_a = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry_a,
            project=project_a,
            source=source_a,
            attachment=attachment_a,
            entry_evidence=await _entry_evidence(db, entry_a.id, source_a.id),
            quote="闭水试验通常持续 24 小时",
        )
        evidence_b = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry_b,
            project=project_b,
            source=source_b,
            attachment=attachment_b,
            entry_evidence=await _entry_evidence(db, entry_b.id, source_b.id),
            quote="闭水试验建议观察 48 小时",
            node_path="验收",
        )
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="两种闭水口径。",
            citations=[
                KnowledgeCitationDraft(evidence_handle=evidence_a.handle),
                KnowledgeCitationDraft(evidence_handle=evidence_b.handle),
            ],
            core_question_answered=True,
            coverage_complete=True,
        )
        answer, _stats = await build_validated_answer(db, run.id, draft)
        assert answer.status == "completed"
        by_project = {
            citation.project_name: citation for citation in answer.citations
        }
        # Workspace 回答中每条引用可独立归属到各自项目
        assert set(by_project) == {"项目甲", "项目乙"}
        citation_a = by_project["项目甲"]
        assert citation_a.project_id == project_a.id
        assert citation_a.node_path == "施工"
        assert citation_a.entry_title == "闭水 24 小时"
        assert citation_a.source_title == "来源甲"
        citation_b = by_project["项目乙"]
        assert citation_b.project_name == "项目乙"
        assert citation_b.node_path == "验收"
        assert citation_b.quote == "闭水试验建议观察 48 小时"

        # 删除当前 Entry/Source：历史快照字段不受影响
        evidence_result = await db.execute(
            select(KnowledgeAgentEvidence).where(
                KnowledgeAgentEvidence.run_id == run.id
            )
        )
        for row in evidence_result.scalars().all():
            await db.refresh(row)
        # 先删除引用行，避免外键顺序问题（证据行本身 FK 为 SET NULL）
        ref_result = await db.execute(
            select(EntrySourceEvidence).where(
                EntrySourceEvidence.entry_id.in_([entry_a.id, entry_b.id])
            )
        )
        for entry_evidence in ref_result.scalars().all():
            await db.delete(entry_evidence)
        await db.flush()
        await db.delete(entry_a)
        await db.delete(entry_b)
        await db.delete(source_a)
        await db.delete(source_b)
        await db.commit()

        answer_after, _stats = await build_validated_answer(db, run.id, draft)
        assert answer_after.status == "completed"
        assert len(answer_after.citations) == 2
        assert {citation.project_name for citation in answer_after.citations} == {
            "项目甲",
            "项目乙",
        }
        assert {
            citation.entry_title for citation in answer_after.citations
        } == {"闭水 24 小时", "闭水 48 小时"}
        assert {
            citation.source_title for citation in answer_after.citations
        } == {"来源甲", "来源乙"}


@pytest.mark.asyncio
async def test_conflict_returns_both_full_citations() -> None:
    """冲突两侧各自返回完整 citation；旧响应无 citation 字段仍可解析。"""
    from app.schemas.knowledge_agent import KnowledgeConflictOut

    async with async_session_factory() as db:
        user = await create_user(db, "双边冲突")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "冲突项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            title="来源 A",
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            title="来源 B",
            text_content="闭水试验建议观察 48 小时。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="闭水 24 小时口径",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="闭水 48 小时口径",
            content="闭水试验建议观察 48 小时。",
            quote="闭水试验建议观察 48 小时",
        )
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            title="冲突测试",
        )
        db.add(conversation)
        await db.flush()
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type="project",
            project_id=project.id,
            status=RUN_PROCESSING,
            active_slot="active",
            max_retries=1,
        )
        db.add(run)
        await db.flush()
        evidence_a = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry_a,
            project=project,
            source=source_a,
            attachment=attachment_a,
            entry_evidence=await _entry_evidence(db, entry_a.id, source_a.id),
            quote="闭水试验通常持续 24 小时",
        )
        evidence_b = await _evidence_row(
            db,
            run_id=run.id,
            entry=entry_b,
            project=project,
            source=source_b,
            attachment=attachment_b,
            entry_evidence=await _entry_evidence(db, entry_b.id, source_b.id),
            quote="闭水试验建议观察 48 小时",
            node_path="验收",
        )
        await db.commit()

        draft = KnowledgeAnswerDraft(
            answer="闭水时长存在两种口径。",
            citations=[],
            conflicts=[
                KnowledgeConflictDraft(
                    evidence_handle_a=evidence_a.handle,
                    evidence_handle_b=evidence_b.handle,
                    summary="24 小时与 48 小时两种来源口径不一致",
                )
            ],
            core_question_answered=True,
            coverage_complete=True,
        )
        answer, _stats = await build_validated_answer(db, run.id, draft)
        assert answer.status == "completed"
        assert len(answer.conflicts) == 1
        conflict = answer.conflicts[0]
        # 兼容字段保留
        assert conflict.evidence_id_a == evidence_a.id
        assert conflict.entry_title_a == "闭水 24 小时口径"
        assert conflict.evidence_id_b == evidence_b.id
        # 双侧完整 citation：各自含 Source、quote、Entry 与项目/目录快照
        assert conflict.citation_a is not None
        assert conflict.citation_a.quote == "闭水试验通常持续 24 小时"
        assert conflict.citation_a.entry_title == "闭水 24 小时口径"
        assert conflict.citation_a.source_title == "来源 A"
        assert conflict.citation_a.project_name == "冲突项目"
        assert conflict.citation_a.node_path == "施工"
        assert conflict.citation_b is not None
        assert conflict.citation_b.quote == "闭水试验建议观察 48 小时"
        assert conflict.citation_b.entry_title == "闭水 48 小时口径"
        assert conflict.citation_b.source_title == "来源 B"
        assert conflict.citation_b.project_id == project.id
        assert conflict.citation_b.node_path == "验收"

    # 旧响应兼容：无 citation_a/b 的历史 JSON 仍能解析且两侧兜底为 None
    legacy = KnowledgeConflictOut.model_validate(
        {
            "summary": "旧冲突",
            "evidence_id_a": 1,
            "entry_id_a": 1,
            "entry_title_a": "旧 A",
            "evidence_id_b": 2,
            "entry_id_b": 2,
            "entry_title_b": "旧 B",
        }
    )
    assert legacy.citation_a is None
    assert legacy.citation_b is None


@pytest.mark.asyncio
async def test_fingerprint_and_quote_verification() -> None:
    """内容指纹稳定；无法定位的 quote 返回 None。"""
    assert attachment_fingerprint("同一段文本") == attachment_fingerprint("同一段文本")
    assert attachment_fingerprint("A") != attachment_fingerprint("B")
    verified = locate_verified_quote("闭水试验 持续24小时。", "闭水试验持续24小时")
    assert verified is not None
    assert verified.text in "闭水试验 持续24小时。"
    assert locate_verified_quote("原文", "完全不同的内容") is None
