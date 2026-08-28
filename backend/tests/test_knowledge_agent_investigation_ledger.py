"""知识 Agent 调查账本与可信只读工具测试：去重、幂等、归属、紧凑性与重建。"""

import uuid

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentEvidence,
    KnowledgeAgentToolCall,
    KnowledgeConversation,
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
)
from app.models.knowledge_agent import (
    ANSWER_MODE_INVESTIGATE,
    INVESTIGATION_QUERY_EXECUTED,
    INVESTIGATION_ROUND_COMPLETED,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.ledger import (
    InvestigationLedger,
    LedgerEntryRef,
    LedgerEvidenceRef,
    clean_query_text,
    dedupe_proposed_queries,
    normalize_query_text,
    query_fingerprint,
    rebuild_ledger,
)
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    search_confirmed_knowledge,
)
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


def test_query_normalization_and_fingerprint() -> None:
    """查询规范化：去空白、小写，指纹稳定且区分不同语义。"""
    assert clean_query_text("  闭水试验  持续  多久  ") == "闭水试验 持续 多久"
    assert normalize_query_text(" 闭水试验 持续 多久 ") == "闭水试验持续多久"
    assert normalize_query_text("Water Test") == "watertest"
    assert query_fingerprint("闭水试验") == query_fingerprint("  闭水试验  ")
    assert query_fingerprint("闭水试验持续多久") == query_fingerprint(
        "闭水试验 持续 多久"
    )
    assert query_fingerprint("放水时机") != query_fingerprint("闭水试验")


def test_dedupe_proposed_queries_partial_duplicates() -> None:
    """重复查询不执行；部分重复只保留合法新查询并计入上限。"""
    executed = {query_fingerprint("闭水试验")}
    new_queries, duplicates = dedupe_proposed_queries(
        ["  闭水试验  ", "放水时机", "  ", "放水时机", "验收标准", "第五个"],
        executed,
        max_queries=3,
    )
    assert new_queries == ["放水时机", "验收标准", "第五个"]
    assert duplicates == ["闭水试验", "放水时机"]


def test_ledger_entry_and_evidence_dedup_across_rounds() -> None:
    """同 Entry/Evidence 跨轮多次命中只保留一条；已发现集合按身份去重。"""
    ledger = InvestigationLedger()
    assert ledger.add_entry(
        LedgerEntryRef(entry_id=1, entry_title="闭水试验", round_number=1)
    ) is True
    assert ledger.add_entry(
        LedgerEntryRef(entry_id=1, entry_title="闭水试验", round_number=2)
    ) is False
    assert ledger.add_entry(
        LedgerEntryRef(entry_id=2, entry_title="验收规则", round_number=2)
    ) is True
    assert ledger.distinct_entry_count() == 2

    assert ledger.add_evidence(
        LedgerEvidenceRef(
            evidence_id=10,
            handle="ev_1",
            entry_id=1,
            source_id=3,
            quote="24 小时",
            round_number=1,
        )
    ) is True
    assert ledger.add_evidence(
        LedgerEvidenceRef(
            evidence_id=10,
            handle="ev_1",
            entry_id=1,
            source_id=3,
            quote="24 小时",
            round_number=2,
        )
    ) is False
    assert ledger.distinct_evidence_count() == 1
    assert "ev_1" in ledger.evidence_handles


def test_ledger_controller_summary_is_compact() -> None:
    """控制器账本摘要只含 ID/短摘要，不复制整份原文。"""
    ledger = InvestigationLedger()
    ledger.add_entry(
        LedgerEntryRef(
            entry_id=1,
            entry_title="长标题" + "长" * 500,
            round_number=1,
        )
    )
    ledger.add_evidence(
        LedgerEvidenceRef(
            evidence_id=2,
            handle="ev_x",
            entry_id=1,
            source_id=3,
            quote="原文片段" + "长" * 1000,
            round_number=1,
        )
    )
    ledger.set_observations(coverage=["已覆盖时长"], gaps=["放水时机"], conflicts=[])
    summary = ledger.controller_summary(max_chars=2000)
    assert len(summary) <= 2000
    assert "长" * 500 not in summary
    assert "原文片段" in summary
    assert "ev_x" not in summary  # 句柄只用于最终综合，不进控制器文本


def test_round_payload_round_trip_restores_ledger() -> None:
    """轮次账本载荷序列化后可恢复到新账本（重建路径）。"""
    source = InvestigationLedger()
    source.add_entry(
        LedgerEntryRef(
            entry_id=1,
            entry_title="闭水试验",
            project_name="项目",
            node_path="施工",
            round_number=1,
        )
    )
    source.add_unavailable(kind="entry", obj_id=9, reason="Entry 已删除", round_number=1)
    source.set_observations(coverage=["时长"], gaps=["放水时机"], conflicts=[])
    payload = source.round_payload(1)
    assert payload["entries"][0]["entry_id"] == 1
    assert payload["unavailable"][0]["id"] == 9

    restored = InvestigationLedger()
    restored.restore_round_payload(payload, 1)
    assert restored.distinct_entry_count() == 1
    assert restored.discovered_entries[1].entry_title == "闭水试验"
    assert restored.coverage == ["时长"]
    assert restored.gaps == ["放水时机"]
    assert restored.unavailable[0]["reason"] == "Entry 已删除"


@pytest.mark.asyncio
async def test_tool_records_round_attribution_and_idempotent_evidence() -> None:
    """证据工具按 round/query 记录归属；跨轮命中同一 Evidence 幂等复用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "账本归属")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "归属项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="验收手册",
            text_content="闭水试验通常持续 24 小时，验收前不得放水。",
        )
        await create_entry_with_evidence(
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
            scope_type=SCOPE_WORKSPACE,
            title="归属对话",
        )
        db.add(conversation)
        await db.flush()
        _user_message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"ledger-{uuid.uuid4().hex[:8]}",
                message="闭水试验",
            ),
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        search = await search_confirmed_knowledge(
            db,
            ctx,
            "闭水试验",
            recall_limit=10,
            context_limit=5,
        )
        assert search.items
        entries = await read_entries(
            db, ctx, [item.entry_id for item in search.items]
        )
        source_ids = [item["source_id"] for item in entries.items[0].sources]
        first = await read_source_evidence(
            db,
            ctx,
            entries.items[0].entry_id,
            source_ids,
            round_number=1,
            query_sequence=1,
        )
        assert first.items and first.items[0].citable
        evidence_id = first.items[0].evidence_id

        second = await read_source_evidence(
            db,
            ctx,
            entries.items[0].entry_id,
            source_ids,
            round_number=2,
            query_sequence=1,
        )
        assert second.items[0].evidence_id == evidence_id
        row = await db.get(KnowledgeAgentEvidence, evidence_id)
        assert row.round_number == 1
        assert row.query_sequence == 1
        # 只存在一条 Evidence（幂等复用）
        count = (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == run.id
                )
            )
        ).scalars().all()
        assert len(count) == 1


@pytest.mark.asyncio
async def test_controller_query_text_cannot_change_scope() -> None:
    """控制器文本查询不能携带或改变可信范围：项目范围 Run 只召回项目内知识。"""
    async with async_session_factory() as db:
        user = await create_user(db, "范围约束")
        workspace = await create_workspace(db, user)
        in_project = await create_project(db, workspace, "范围内项目")
        out_project = await create_project(db, workspace, "范围外项目")
        in_node = await create_child_node(db, in_project, "施工")
        out_node = await create_child_node(db, out_project, "室外")
        source_in, attachment_in = await create_source_attachment(
            db,
            workspace,
            in_project,
            text_content="闭水试验通常持续 24 小时。",
        )
        source_out, attachment_out = await create_source_attachment(
            db,
            workspace,
            out_project,
            text_content="庭院树木冬季养护要点。",
        )
        await create_entry_with_evidence(
            db,
            in_project,
            in_node,
            source_in,
            attachment_in,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        await create_entry_with_evidence(
            db,
            out_project,
            out_node,
            source_out,
            attachment_out,
            title="庭院养护",
            content="庭院树木冬季养护要点。",
            quote="庭院树木冬季养护要点",
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=in_project.id,
            project_name="范围内项目",
        )
        # 查询文本提到范围外内容，工具仍只返回范围内 Entry
        search = await search_confirmed_knowledge(
            db,
            ctx,
            "庭院树木冬季养护",
            recall_limit=10,
            context_limit=5,
        )
        assert all(item.project_name == "范围内项目" for item in search.items)


@pytest.mark.asyncio
async def test_rebuild_ledger_from_persisted_rows() -> None:
    """重建：从已提交轮次、查询与 Evidence 恢复账本，不重复计数。"""
    async with async_session_factory() as db:
        user = await create_user(db, "账本重建")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="重建对话",
        )
        db.add(conversation)
        await db.flush()
        _user_message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"rebuild-{uuid.uuid4().hex[:8]}",
                message="调查问题",
            ),
        )
        investigation = KnowledgeInvestigation(
            run_id=run.id,
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            objective="调查问题",
            requested_answer_mode=ANSWER_MODE_INVESTIGATE,
            actual_answer_mode=ANSWER_MODE_INVESTIGATE,
            current_round=1,
            total_queries_executed=2,
            distinct_entries_found=2,
            citable_evidence_count=1,
        )
        db.add(investigation)
        await db.flush()
        round_row = KnowledgeInvestigationRound(
            investigation_id=investigation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            round_number=1,
            status=INVESTIGATION_ROUND_COMPLETED,
            controller_action="search",
            coverage_json='["已覆盖时长"]',
            gaps_json='["放水时机未覆盖"]',
            conflicts_json="[]",
            entries_json=(
                '[{"entry_id":1,"entry_title":"闭水试验","project_name":"项目",'
                '"node_path":"施工","round_number":1},'
                '{"entry_id":2,"entry_title":"验收规则","project_name":"项目",'
                '"node_path":"验收","round_number":1}]'
            ),
            unavailable_json='[{"kind":"entry","id":9,"reason":"已删除","round_number":1}]',
            queries_planned=2,
            queries_executed=2,
            entries_added=2,
            evidence_added=1,
        )
        db.add(round_row)
        await db.flush()
        for sequence, text, fingerprint in [
            (1, "闭水试验时长", "hash-1"),
            (2, "放水时机", "hash-2"),
        ]:
            db.add(
                KnowledgeInvestigationQuery(
                    investigation_id=investigation.id,
                    round_id=round_row.id,
                    workspace_id=workspace.id,
                    owner_user_id=user.id,
                    round_number=1,
                    sequence=sequence,
                    original_query=text,
                    normalized_query=normalize_query_text(text),
                    normalized_query_hash=fingerprint,
                    status=INVESTIGATION_QUERY_EXECUTED,
                )
            )
        db.add(
            KnowledgeAgentEvidence(
                run_id=run.id,
                handle="ev_rebuild",
                entry_id=1,
                project_id=None,
                source_id=3,
                attachment_id=None,
                entry_title="闭水试验",
                source_title="来源",
                quote="闭水试验通常持续 24 小时",
                content_fingerprint="fp",
                purpose="answer",
                is_citable=True,
                round_number=1,
                query_sequence=1,
            )
        )
        await db.commit()

        rebuilt = await rebuild_ledger(db, investigation, run.id)
        assert rebuilt.executed_query_hashes == {"hash-1", "hash-2"}
        assert rebuilt.distinct_entry_count() == 2
        assert rebuilt.discovered_entries[1].entry_title == "闭水试验"
        assert rebuilt.distinct_evidence_count() == 1
        assert "ev_rebuild" in rebuilt.evidence_handles
        assert rebuilt.coverage == ["已覆盖时长"]
        assert rebuilt.gaps == ["放水时机未覆盖"]
        assert rebuilt.unavailable[0]["id"] == 9
        assert len(rebuilt.executed_queries) == 2


@pytest.mark.asyncio
async def test_long_attachment_evidence_keeps_minimal_audit() -> None:
    """长原文：Evidence 只保存核验子串，工具审计摘要受限不复制整份原文。"""
    async with async_session_factory() as db:
        user = await create_user(db, "长原文")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "长原文项目")
        node = await create_child_node(db, project, "施工")
        long_text = "闭水试验通常持续 24 小时。" + "填充" * 3000
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="长手册",
            text_content=long_text,
        )
        await create_entry_with_evidence(
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
            scope_type=SCOPE_WORKSPACE,
            title="长原文对话",
        )
        db.add(conversation)
        await db.flush()
        _user_message, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"long-{uuid.uuid4().hex[:8]}",
                message="闭水试验",
            ),
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        search = await search_confirmed_knowledge(
            db, ctx, "闭水试验", recall_limit=10, context_limit=5
        )
        entries = await read_entries(
            db, ctx, [item.entry_id for item in search.items]
        )
        result = await read_source_evidence(
            db,
            ctx,
            entries.items[0].entry_id,
            [item["source_id"] for item in entries.items[0].sources],
            round_number=1,
            query_sequence=1,
        )
        assert result.items and result.items[0].citable
        evidence = await db.get(KnowledgeAgentEvidence, result.items[0].evidence_id)
        assert len(evidence.quote) < 200
        assert evidence.quote in long_text
        tool_calls = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id,
                    KnowledgeAgentToolCall.tool_name == "read_source_evidence",
                )
            )
        ).scalars().all()
        for call in tool_calls:
            assert len(call.params_summary or "") <= 500
            assert len(call.result_summary or "") <= 500
            assert "填充" not in (call.params_summary or "")
