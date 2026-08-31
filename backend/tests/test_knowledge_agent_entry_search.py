"""有界正式 Entry 查找测试：范围隔离、快照装配、完整性、字节与终态语义。"""

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.session import async_session_factory
from app.models import (
    Candidate,
    Extraction,
    KnowledgeAgentEvidence,
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeContextVersion,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    RESULT_COMPLETENESS_COMPLETE,
    RESULT_COMPLETENESS_LIMITED,
    RESULT_COMPLETENESS_UNKNOWN,
    RESULT_MODE_ENTRIES,
    RUN_COMPLETED,
    RUN_PROCESSING,
    SCOPE_PROJECT,
    SCOPE_WORKSPACE,
)
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.entry_search import (
    _completeness_for,
)
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runner import RunCancelled, execute_run
from app.services.knowledge_agent.runs import submit_message
from app.services.knowledge_agent.working_set import get_active_context_version
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)


def _decision() -> ContextDecisionResult:
    return ContextDecisionResult(
        decision="new_topic",
        standalone_query="闭水试验",
        topic_label="闭水试验",
        clarify_question=None,
        degraded=False,
        history_message_ids=[],
        meta=StageMeta(
            purpose="context_decision",
            provider="server",
            model=None,
            is_fallback=False,
            error=None,
            duration_ms=0,
        ),
    )


@pytest.fixture(autouse=True)
def _runner_stubs(monkeypatch):
    """默认决策与回答路由替身：entries 路径不得进入回答模式路由。"""

    async def _decide(db, **kwargs):
        return _decision()

    async def _fail_answer_route(db, **kwargs):
        raise AssertionError("entries 不应调用回答模式路由")

    monkeypatch.setattr("app.services.knowledge_agent.runner.decide_context", _decide)
    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _fail_answer_route,
    )


async def _user_workspace(db, prefix: str = "查找"):
    user = await create_user(db, f"{prefix}_{uuid.uuid4().hex[:6]}")
    workspace = await create_workspace(db, user)
    return user, workspace


async def _seed_workspace(db, workspace, *, entry_count: int = 3):
    """创建多项目、多 Entry 的查找范围数据。"""
    project_a = await create_project(db, workspace, "项目甲")
    node_a = await create_child_node(db, project_a, "施工")
    project_b = await create_project(db, workspace, "项目乙")
    node_b = await create_child_node(db, project_b, "健康")
    for index in range(entry_count):
        project, node = (project_a, node_a) if index % 2 == 0 else (project_b, node_b)
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title=f"来源{index}",
            text_content=f"闭水试验记录{index}：持续 24 小时。",
        )
        await create_entry_with_evidence(
            db,
            project,
            node,
            source,
            attachment,
            title=f"闭水试验 {index}",
            content=f"闭水试验记录{index}：基层处理、涂刷范围与验收要点。",
            quote=f"闭水试验记录{index}",
        )
    return project_a, project_b, node_a, node_b


async def _run_for_search(
    db,
    user,
    workspace,
    *,
    scope_type: str = SCOPE_WORKSPACE,
    project_id: int | None = None,
    message: str = "找出和闭水试验有关的知识",
) -> KnowledgeAgentRun:
    """创建显式 entries Run 并进入 processing。"""
    from app.models import KnowledgeConversation

    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=scope_type,
        project_id=project_id,
        title="查找测试对话",
    )
    db.add(conversation)
    await db.flush()
    _user_message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"search-{uuid.uuid4().hex[:8]}",
            message=message,
            result_mode=RESULT_MODE_ENTRIES,
        ),
    )
    run.status = RUN_PROCESSING
    run.current_step = "claim"
    await db.flush()
    return run


def _snapshot(run: KnowledgeAgentRun) -> dict | None:
    if not run.entry_result_json:
        return None
    return json.loads(run.entry_result_json)


@pytest.mark.asyncio
async def test_workspace_search_returns_cross_project_entries() -> None:
    """Workspace 范围查找：返回多项目正式 Entry 并逐项保存项目归属。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=3)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()

        assert run.status == RUN_COMPLETED
        assert run.actual_result_mode == RESULT_MODE_ENTRIES
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["status"] == "completed"
        assert snapshot["completeness"] == RESULT_COMPLETENESS_COMPLETE
        assert snapshot["returned_count"] == 3
        project_names = {item["project_name"] for item in snapshot["items"]}
        assert project_names == {"项目甲", "项目乙"}
        assert all(item["project_name"] for item in snapshot["items"])
        assert all(item["source_count"] == 1 for item in snapshot["items"])
        # 摘要、类型与匹配线索有界
        assert all(item["excerpt"] for item in snapshot["items"])
        assert all(item["main_type"] == "knowledge" for item in snapshot["items"])
        assert any(item["matched_fields"] for item in snapshot["items"])
        # 兼容助手摘要写入，但不生成回答/Citation
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert assistant is not None
        assert "找到 3 条相关正式知识" in assistant.content
        assert run.answer_json is None
        evidences = (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == run.id
                )
            )
        ).scalars().all()
        assert evidences == []
        # 不推进工作集
        assert run.output_context_version_id is None
        active = await get_active_context_version(db, run.conversation_id)
        assert active is None


@pytest.mark.asyncio
async def test_project_scope_limits_results_to_project() -> None:
    """项目范围查找：只返回该项目正式 Entry，目录仅作定位。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        project_a, project_b, _node_a, _node_b = await _seed_workspace(
            db, workspace, entry_count=3
        )
        run = await _run_for_search(
            db,
            user,
            workspace,
            scope_type=SCOPE_PROJECT,
            project_id=project_a.id,
        )
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["status"] == "completed"
        assert len(snapshot["items"]) == 2
        assert all(item["project_id"] == project_a.id for item in snapshot["items"])
        assert all(item["project_name"] == "项目甲" for item in snapshot["items"])
        assert project_b.id not in {item["project_id"] for item in snapshot["items"]}


@pytest.mark.asyncio
async def test_other_workspace_entries_never_returned() -> None:
    """跨 Workspace/用户隔离：其他空间 Entry 不会进入结果。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        other_user, other_workspace = await _user_workspace(db, "其他空间")
        await _seed_workspace(db, workspace, entry_count=2)
        await _seed_workspace(db, other_workspace, entry_count=4)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["returned_count"] == 2
        assert all(
            item["project_id"] is not None
            for item in snapshot["items"]
        )
        del other_user


@pytest.mark.asyncio
async def test_pending_candidate_never_enters_results() -> None:
    """待确认 Candidate 不进入正式 Entry 结果集。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        project, _other, node, _other_node = await _seed_workspace(
            db, workspace, entry_count=2
        )
        # 同源挂一条 pending Candidate（内容命中查询），但不应出现在结果中
        source, _attachment = await create_source_attachment(
            db,
            workspace,
            project,
            title="待确认来源",
            text_content="闭水试验待确认内容",
        )
        extraction = Extraction(
            source_id=source.id,
            provider="test",
            model="test",
            prompt_version="v1",
        )
        db.add(extraction)
        await db.flush()
        db.add(
            Candidate(
                extraction_id=extraction.id,
                source_id=source.id,
                title="闭水试验候选",
                content="闭水试验待确认内容",
                main_type="knowledge",
                info_nature="fact",
                status="pending",
            )
        )
        await db.flush()
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["returned_count"] == 2
        titles = {item["title"] for item in snapshot["items"]}
        assert "闭水试验候选" not in titles
        assert node is not None


@pytest.mark.asyncio
async def test_empty_scope_completes_normally() -> None:
    """空结果正常完成：completed + 空列表 + 可证明穷尽。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        assert run.status == RUN_COMPLETED
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["status"] == "completed"
        assert snapshot["items"] == []
        assert snapshot["returned_count"] == 0
        assert snapshot["completeness"] == RESULT_COMPLETENESS_COMPLETE
        assistant = await db.get(KnowledgeMessage, run.assistant_message_id)
        assert "没有找到匹配" in assistant.content


@pytest.mark.asyncio
async def test_dedupe_stable_order_and_pure_semantic_without_hint() -> None:
    """去重稳定、顺序一致；纯语义查询无字段命中时匹配线索留空。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=3)
        # 完全无语义关联、无关键词命中的查询
        run = await _run_for_search(
            db,
            user,
            workspace,
            message="完全不相关的天文观测记录",
        )
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        entry_ids = [item["entry_id"] for item in snapshot["items"]]
        assert len(entry_ids) == len(set(entry_ids))
        # 确定性低相似可能仍召回；纯语义命中时不得伪造字段命中
        for item in snapshot["items"]:
            if not item["matched_fields"]:
                assert item["match_hint"] is None


@pytest.mark.asyncio
async def test_recall_and_persist_limits_mark_limited(monkeypatch) -> None:
    """候选/持久化上限截断：返回 limited 与 warning，不显示全部。"""
    fake_settings = SimpleNamespace(
        knowledge_agent_result_candidate_limit=2,
        knowledge_agent_result_persist_limit=1,
        knowledge_agent_result_excerpt_chars=240,
        knowledge_agent_result_node_path_chars=400,
        knowledge_agent_result_match_hint_chars=120,
        knowledge_agent_result_json_bytes_limit=60000,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.get_settings",
        lambda: fake_settings,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=4)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert snapshot["completeness"] == RESULT_COMPLETENESS_LIMITED
        assert snapshot["returned_count"] == 1
        assert snapshot["warning"] is not None


@pytest.mark.asyncio
async def test_json_bytes_limit_drops_items(monkeypatch) -> None:
    """序列化字节上限：超限确定性丢弃末尾项并标记 limited。"""
    fake_settings = SimpleNamespace(
        knowledge_agent_result_candidate_limit=50,
        knowledge_agent_result_persist_limit=30,
        knowledge_agent_result_excerpt_chars=240,
        knowledge_agent_result_node_path_chars=400,
        knowledge_agent_result_match_hint_chars=120,
        knowledge_agent_result_json_bytes_limit=500,
    )
    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.get_settings",
        lambda: fake_settings,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=3)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        snapshot = _snapshot(run)
        assert snapshot is not None
        assert len(snapshot["items"]) < 3
        assert snapshot["completeness"] == RESULT_COMPLETENESS_LIMITED
        assert "容量超出限制" in (snapshot["warning"] or "")
        # 持久化 JSON 字节数不超过服务端上限
        assert len(run.entry_result_json.encode("utf-8")) <= 500


def test_completeness_rule_units() -> None:
    """完整性规则：截断/语义扩展→limited；装配失败→unknown；关键词穷尽→complete。"""
    assert (
        _completeness_for(
            scope_total=60,
            candidates_count=50,
            persist_count=30,
            recall_limit=50,
            persist_limit=30,
            keyword_verified=True,
            embedding_meta=None,
            assembly_failed=False,
        )
        == RESULT_COMPLETENESS_LIMITED
    )
    assert (
        _completeness_for(
            scope_total=10,
            candidates_count=10,
            persist_count=10,
            recall_limit=50,
            persist_limit=30,
            keyword_verified=False,
            embedding_meta=SimpleNamespace(is_fallback=False),
            assembly_failed=False,
        )
        == RESULT_COMPLETENESS_LIMITED
    )
    assert (
        _completeness_for(
            scope_total=10,
            candidates_count=10,
            persist_count=10,
            recall_limit=50,
            persist_limit=30,
            keyword_verified=True,
            embedding_meta=SimpleNamespace(is_fallback=True),
            assembly_failed=False,
        )
        == RESULT_COMPLETENESS_COMPLETE
    )
    assert (
        _completeness_for(
            scope_total=10,
            candidates_count=10,
            persist_count=8,
            recall_limit=50,
            persist_limit=30,
            keyword_verified=True,
            embedding_meta=None,
            assembly_failed=True,
        )
        == RESULT_COMPLETENESS_UNKNOWN
    )


@pytest.mark.asyncio
async def test_finalize_failure_does_not_commit_half_snapshot(monkeypatch) -> None:
    """终态事务失败：不暴露半份快照，Run 可重试。"""

    async def _explode(db, run, **kwargs):
        raise RuntimeError("数据库写入失败")

    monkeypatch.setattr(
        "app.services.knowledge_agent.entry_search.finalize_entry_run",
        _explode,
    )
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=2)
        run = await _run_for_search(db, user, workspace)
        run_id = run.id
        await db.commit()
        with pytest.raises(RuntimeError):
            await execute_run(db, run)
        await db.rollback()
        reloaded = await db.get(KnowledgeAgentRun, run_id)
        assert reloaded is not None
        assert reloaded.entry_result_json is None
        assert reloaded.status == RUN_PROCESSING
        assert reloaded.active_slot is not None


@pytest.mark.asyncio
async def test_cancel_aborts_without_snapshot() -> None:
    """取消：在终态前停止，不提交结果快照。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=2)
        run = await _run_for_search(db, user, workspace)
        run_id = run.id
        run.cancel_requested = True
        await db.commit()
        with pytest.raises(RunCancelled):
            await execute_run(db, run)
        await db.rollback()
        reloaded = await db.get(KnowledgeAgentRun, run_id)
        assert reloaded.entry_result_json is None
        assert reloaded.status == RUN_PROCESSING


@pytest.mark.asyncio
async def test_replay_produces_same_snapshot_and_no_duplicates() -> None:
    """崩溃恢复重放：同一有界图重跑并原子覆盖，不产生第二个结果集。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=2)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        first = _snapshot(run)
        assert first is not None
        first_ids = [item["entry_id"] for item in first["items"]]

        # 重放：actual_result_mode 已固化，跳过路由，重新执行查找并覆盖
        run.status = RUN_PROCESSING
        run.active_slot = "active"
        run.current_step = "recovered"
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        second = _snapshot(run)
        assert second is not None
        assert [item["entry_id"] for item in second["items"]] == first_ids
        assert run.status == RUN_COMPLETED


@pytest.mark.asyncio
async def test_no_context_version_created_for_entries_run() -> None:
    """entries Run 不创建输出上下文版本，活动工作集不推进。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=2)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        before = (
            await db.execute(
                select(func.count()).select_from(KnowledgeContextVersion)
            )
        ).scalar_one()
        await execute_run(db, run)
        await db.commit()
        after = (
            await db.execute(
                select(func.count()).select_from(KnowledgeContextVersion)
            )
        ).scalar_one()
        assert after == before
        assert run.output_context_version_id is None


@pytest.mark.asyncio
async def test_search_tool_observability_recorded() -> None:
    """结构化查找记录工具调用与 embedding/rerank 模型调用，含完整性摘要。"""
    async with async_session_factory() as db:
        user, workspace = await _user_workspace(db)
        await _seed_workspace(db, workspace, entry_count=2)
        run = await _run_for_search(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        from app.models import KnowledgeAgentToolCall

        tool_rows = (
            await db.execute(
                select(KnowledgeAgentToolCall).where(
                    KnowledgeAgentToolCall.run_id == run.id,
                    KnowledgeAgentToolCall.tool_name == "structured_entry_search",
                )
            )
        ).scalars().all()
        assert len(tool_rows) == 1
        result = json.loads(tool_rows[0].result_summary)
        assert result["scope_total"] == 2
        assert result["persisted"] == 2
        assert result["completeness"] in {
            RESULT_COMPLETENESS_COMPLETE,
            RESULT_COMPLETENESS_LIMITED,
        }
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id
                )
            )
        ).scalars().all()
        assert {item.purpose for item in invocations} >= {
            "embedding",
            "rerank",
        }
