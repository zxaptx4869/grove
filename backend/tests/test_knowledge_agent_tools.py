"""知识 Agent 可信只读工具测试：范围、已发现集合、证据核验与拒绝路径。"""

import pytest
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import KnowledgeAgentEvidence
from app.models.knowledge_agent import (
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
    TOOL_DENIED,
    TOOL_OK,
    TOOL_UNAVAILABLE,
)
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


async def _base_ctx(
    workspace_id: int,
    run_id: int = 1,
    scope_type: str = SCOPE_WORKSPACE,
) -> RunToolContext:
    return RunToolContext(
        run_id=run_id,
        workspace_id=workspace_id,
        owner_user_id=1,
        scope_type=scope_type,
        project_id=None,
        project_name=None,
    )


@pytest.mark.asyncio
async def test_workspace_search_returns_multiple_projects_with_ownership() -> None:
    """Workspace 范围搜索跨项目返回正式 Entry 并携带项目归属。"""
    async with async_session_factory() as db:
        user = await create_user(db, "搜索")
        workspace = await create_workspace(db, user)
        first_project = await create_project(db, workspace, "装修项目")
        second_project = await create_project(db, workspace, "园林项目")
        first_node = await create_child_node(db, first_project, "施工")
        second_node = await create_child_node(db, second_project, "养护")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            first_project,
            title="装修手册",
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            second_project,
            title="园林手册",
            text_content="新栽树木需要浇透水。",
        )
        await create_entry_with_evidence(
            db,
            first_project,
            first_node,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        await create_entry_with_evidence(
            db,
            second_project,
            second_node,
            source_b,
            attachment_b,
            title="树木浇水",
            content="新栽树木需要浇透水。",
            quote="新栽树木需要浇透水",
        )
        await db.commit()

        ctx = await _base_ctx(workspace.id, scope_type=SCOPE_WORKSPACE)
        result = await search_confirmed_knowledge(
            db,
            ctx,
            "闭水试验",
            recall_limit=10,
            context_limit=5,
        )
        assert result.items
        titles = {item.title for item in result.items}
        assert "闭水试验" in titles
        by_title = {item.title: item for item in result.items}
        assert by_title["闭水试验"].project_name == "装修项目"
        assert by_title["闭水试验"].node_path == "施工"
        assert len(ctx.discovered_entry_ids) == len(result.items)


@pytest.mark.asyncio
async def test_project_scope_search_only_returns_project_entries() -> None:
    """项目范围搜索只返回该项目 Entry，不泄露其他项目内容。"""
    async with async_session_factory() as db:
        user = await create_user(db, "项目范围")
        workspace = await create_workspace(db, user)
        project_a = await create_project(db, workspace, "甲项目")
        project_b = await create_project(db, workspace, "乙项目")
        node_a = await create_child_node(db, project_a, "目录A")
        node_b = await create_child_node(db, project_b, "目录B")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project_a,
            text_content="甲项目独有的闭水试验知识。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project_b,
            text_content="乙项目独有的闭水试验知识。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project_a,
            node_a,
            source_a,
            attachment_a,
            title="甲闭水",
            content="甲项目独有的闭水试验知识。",
            quote="甲项目独有的闭水试验知识",
        )
        await create_entry_with_evidence(
            db,
            project_b,
            node_b,
            source_b,
            attachment_b,
            title="乙闭水",
            content="乙项目独有的闭水试验知识。",
            quote="乙项目独有的闭水试验知识",
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=project_a.id,
            project_name="甲项目",
        )
        result = await search_confirmed_knowledge(
            db,
            ctx,
            "闭水试验",
            recall_limit=10,
            context_limit=5,
        )
        assert [item.entry_id for item in result.items] == [entry_a.id]
        assert all(item.project_name == "甲项目" for item in result.items)


@pytest.mark.asyncio
async def test_read_entries_requires_discovery_and_rechecks_scope() -> None:
    """未发现或移出范围的 Entry 拒绝读取；发现后可读完整内容。"""
    async with async_session_factory() as db:
        user = await create_user(db, "发现集")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "发现项目")
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
        await db.commit()

        # 未发现：拒绝
        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        denied = await read_entries(db, ctx, [entry.id])
        assert denied.items == []
        assert denied.denied_entry_ids == [entry.id]

        # 发现后：返回完整内容与来源关系
        ctx.discovered_entry_ids.add(entry.id)
        loaded = await read_entries(db, ctx, [entry.id])
        assert len(loaded.items) == 1
        assert loaded.items[0].content == "闭水试验通常持续 24 小时。"
        assert loaded.items[0].sources[0]["source_id"] == source.id

        # 项目范围 Run 强制读取其他项目对象：范围复验拒绝
        other_project = await create_project(db, workspace, "他项目")
        other_node = await create_child_node(db, other_project, "其他")
        other_source, other_attachment = await create_source_attachment(
            db,
            workspace,
            other_project,
            text_content="其他项目内容。",
        )
        other_entry = await create_entry_with_evidence(
            db,
            other_project,
            other_node,
            other_source,
            other_attachment,
            title="其他知识",
            content="其他项目内容。",
            quote="其他项目内容",
        )
        await db.commit()
        project_ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_PROJECT,
            project_id=project.id,
            project_name="发现项目",
        )
        # 模拟模型猜测 UUID：即使加入已发现集合，范围复验仍拒绝
        project_ctx.discovered_entry_ids.add(other_entry.id)
        cross = await read_entries(db, project_ctx, [other_entry.id])
        assert cross.items == []
        assert other_entry.id in cross.denied_entry_ids


@pytest.mark.asyncio
async def test_source_evidence_verified_quote_creates_citable_evidence() -> None:
    """可核验原文生成可引用 Evidence，quote 为原文精确子串。"""
    async with async_session_factory() as db:
        user = await create_user(db, "证据")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "证据项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="验收手册",
            text_content="闭水试验通常持续 24 小时，验收前不得放水。",
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
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        ctx.discovered_entry_ids.add(entry.id)
        result = await read_source_evidence(db, ctx, entry.id, [source.id])
        assert len(result.items) == 1
        item = result.items[0]
        assert item.citable is True
        assert item.status == TOOL_OK
        assert item.quote == "闭水试验通常持续 24 小时"
        assert item.evidence_handle.startswith("ev_")

        evidence = (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.handle == item.evidence_handle
                )
            )
        ).scalar_one()
        assert evidence.entry_id == entry.id
        assert evidence.source_id == source.id
        assert evidence.attachment_id == attachment.id
        assert evidence.quote == "闭水试验通常持续 24 小时"
        assert evidence.content_fingerprint


@pytest.mark.asyncio
async def test_source_evidence_ocr_normalization() -> None:
    """OCR 文本差异可归一化定位，仍保存原文精确子串。"""
    async with async_session_factory() as db:
        user = await create_user(db, "OCR")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "OCR项目")
        node = await create_child_node(db, project, "图像")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="扫描件",
            ocr_text="闭水试验…通常持续 24 小时。验收前不得放水。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续24小时",
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        ctx.discovered_entry_ids.add(entry.id)
        result = await read_source_evidence(db, ctx, entry.id, [source.id])
        assert result.items[0].citable is True
        # 保存的必须是 OCR 原文中真实存在的子串（带省略号版本）
        assert "…" in result.items[0].quote
        assert result.items[0].quote in attachment.ocr_text


@pytest.mark.asyncio
async def test_source_evidence_unavailable_and_denied() -> None:
    """无引用片段或无法核验时不生成 Evidence；无关 Source 拒绝。"""
    async with async_session_factory() as db:
        user = await create_user(db, "拒绝")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "拒绝项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="无引用",
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
            quote=None,
        )
        unrelated, _unrelated_attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="无关来源",
            text_content="完全不相关的内容。",
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        ctx.discovered_entry_ids.add(entry.id)
        # 无引用片段 → 不可用
        result = await read_source_evidence(db, ctx, entry.id, [source.id])
        assert result.items[0].citable is False
        assert result.items[0].status == TOOL_UNAVAILABLE
        # 无关 Source → 拒绝
        denied = await read_source_evidence(db, ctx, entry.id, [unrelated.id])
        assert denied.items[0].citable is False
        assert denied.items[0].status == TOOL_DENIED
        # 未发现 Entry → 拒绝
        undiscovered = await read_source_evidence(db, ctx, 99999, [source.id])
        assert undiscovered.items[0].status == TOOL_DENIED


@pytest.mark.asyncio
async def test_read_source_evidence_deleted_source_not_crash() -> None:
    """证据指向已删除 Source 时不崩溃，记录为不可用且不产生引用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "孤儿来源")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "来源项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="旧来源",
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
        # SQLite 不强制外键：直接删除 Source 会留下孤儿证据行
        await db.delete(source)
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        ctx.discovered_entry_ids.add(entry.id)
        result = await read_source_evidence(db, ctx, entry.id, [source.id])
        assert len(result.items) == 1
        item = result.items[0]
        assert item.citable is False
        assert item.status == TOOL_UNAVAILABLE
        assert item.reason == "Source 已删除"


@pytest.mark.asyncio
async def test_evidence_unverified_quote() -> None:
    """候选片段无法在原文中定位时禁止引用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无法核验")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "核验项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="原文说的是完全不同的内容。",
        )
        entry = await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="模型编造的完全不存在的一句话",
        )
        await db.commit()

        ctx = RunToolContext(
            run_id=1,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        ctx.discovered_entry_ids.add(entry.id)
        result = await read_source_evidence(db, ctx, entry.id, [source.id])
        assert result.items[0].citable is False
        assert result.items[0].status == TOOL_UNAVAILABLE
