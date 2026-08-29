"""知识 Agent 有界调查编排测试：单/多轮补查、预算、停止、引用与工作集过滤。"""

import json

import pytest
from sqlalchemy import select

from app.agents.investigation import InvestigationControllerDraft
from app.agents.knowledge_agent import KnowledgeConflictDraft
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentRun,
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
    KnowledgeWorkingSetItem,
)
from app.models.knowledge_agent import (
    ANSWER_MODE_INVESTIGATE,
    INVESTIGATION_ACTION_ANSWER,
    INVESTIGATION_ACTION_INSUFFICIENT,
    INVESTIGATION_ACTION_SEARCH,
    INVESTIGATION_ROUND_COMPLETED,
    INVESTIGATION_STATUS_COMPLETED,
    INVESTIGATION_STATUS_INSUFFICIENT,
    RUN_COMPLETED,
    RUN_PARTIAL,
    RUN_PROCESSING,
    STOP_REASON_CONTROLLER_COMPLETE,
    STOP_REASON_ENTRY_BUDGET,
    STOP_REASON_EVIDENCE_BUDGET,
    STOP_REASON_INSUFFICIENT,
    STOP_REASON_MAX_ROUNDS,
    STOP_REASON_NO_PROGRESS,
    STOP_REASON_QUERY_BUDGET,
)
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.investigation import AnswerModeResolution
from app.services.knowledge_agent.ledger import query_fingerprint
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runner import execute_run
from app.services.knowledge_agent.tools import SearchResultItem, SearchToolOutput
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)
from tests.test_knowledge_agent_runner import (
    KnowledgeAnswerDraft,
    KnowledgeCitationDraft,
    _conversation_and_run,
)


@pytest.fixture(autouse=True)
def _fixed_context_and_mode(monkeypatch):
    """固定上下文决策为 new_topic、回答模式为 investigate，避免模型依赖。"""

    async def _decide(
        db,
        *,
        workspace_id,
        conversation_id,
        current_message,
        request_mode,
        active_topic_label,
        working_set_titles,
        history_limit,
        history_message_chars,
        user_message_id=None,
        exclude_run_id=None,
    ):
        return ContextDecisionResult(
            decision="new_topic",
            standalone_query=current_message,
            topic_label="调查主题",
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

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.decide_context",
        _decide,
    )

    async def _resolve_mode(
        db,
        *,
        workspace_id,
        request_mode,
        objective,
        topic_summary,
    ):
        return AnswerModeResolution(mode="investigate")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _resolve_mode,
    )


async def _investigation_run(
    db,
    user,
    workspace,
    message: str = "闭水试验与放水时机怎么规定？",
):
    """创建对话与 investigate Run（提交后直接固化为调查模式）。"""
    conversation, run = await _conversation_and_run(db, user, workspace, message)
    run.request_answer_mode = ANSWER_MODE_INVESTIGATE
    run.status = RUN_PROCESSING
    run.current_step = "claim"
    await db.flush()
    return conversation, run


async def _fresh_investigation_run(
    db,
    user,
    workspace,
    message: str = "闭水试验与放水时机怎么规定？",
):
    """每个预算场景使用全新对话与 Run，避免复用已终态调查。"""
    return await _investigation_run(db, user, workspace, message)


def _controller_sequence(plans):
    """按顺序返回控制器草稿的替身；记录每次输入。"""
    calls: list[dict] = []

    async def _fake(
        db,
        workspace_id,
        *,
        objective,
        scope_label,
        working_set_summary,
        executed_queries,
        ledger_summary,
        remaining_budget,
    ):
        calls.append(
            {
                "executed": list(executed_queries),
                "budget": dict(remaining_budget),
                "summary": ledger_summary,
            }
        )
        draft = plans[min(len(calls) - 1, len(plans) - 1)]
        return (
            draft,
            StageMeta(
                purpose="investigation_controller",
                provider="llm",
                model="fake-controller",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    return _fake, calls


def _synthesis_agent():
    """综合回答替身：引用回答上下文里实际提供的第一个 Evidence 句柄。"""

    async def _fake(
        db,
        workspace_id,
        query,
        scope_label,
        entries,
        *,
        purpose=None,
        synthesis_context=None,
    ):
        handles = []
        for item in entries:
            for evidence in item.get("evidences", []):
                handles.append(evidence["handle"])
        return (
            KnowledgeAnswerDraft(
                answer="综合回答：根据多轮证据整理。",
                citations=[
                    KnowledgeCitationDraft(evidence_handle=handle)
                    for handle in handles
                ],
                conflicts=[],
                insufficient=False,
                insufficient_note=None,
            ),
            StageMeta(
                purpose=purpose or "synthesis",
                provider="llm",
                model="fake-synthesis",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    return _fake


def _search_result(entry) -> SearchResultItem:
    """构造脚本化搜索结果项。"""
    return SearchResultItem(
        entry_id=entry.id,
        title=entry.title,
        project_name=entry.project.name if entry.project else "项目",
        node_path="",
        summary=entry.content[:200],
        source_count=1,
    )


def _scripted_search(results_by_query: dict[str, list]):
    """脚本化搜索替身：按查询文本返回命中并维护已发现集合。"""

    async def _fake(
        db,
        ctx,
        query,
        *,
        recall_limit,
        context_limit,
        seed_entries=None,
    ):
        items = results_by_query.get(query, [])
        for item in items:
            ctx.discovered_entry_ids.add(item.entry_id)
        return SearchToolOutput(items=items)

    return _fake


async def _load_investigation(db, run_id):
    investigation = (
        await db.execute(
            select(KnowledgeInvestigation).where(
                KnowledgeInvestigation.run_id == run_id
            )
        )
    ).scalar_one()
    rounds = (
        await db.execute(
            select(KnowledgeInvestigationRound)
            .where(KnowledgeInvestigationRound.investigation_id == investigation.id)
            .order_by(KnowledgeInvestigationRound.round_number)
        )
    ).scalars().all()
    queries = (
        await db.execute(
            select(KnowledgeInvestigationQuery)
            .where(KnowledgeInvestigationQuery.investigation_id == investigation.id)
            .order_by(KnowledgeInvestigationQuery.round_number)
        )
    ).scalars().all()
    return investigation, list(rounds), list(queries)


@pytest.mark.asyncio
async def test_investigation_controller_answer_after_one_search_round(
    monkeypatch,
) -> None:
    """一轮补查后控制器主动回答：调查完成并带当前 Run 引用。"""
    async with async_session_factory() as db:
        user = await create_user(db, "调查单轮")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "调查项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
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
        _conversation, run = await _investigation_run(
            db, user, workspace, "闭水试验持续多久？"
        )
        await db.commit()

        controller, calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                    coverage=["时长"],
                    gaps=["放水时机"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_ANSWER,
                    coverage=["时长"],
                    gaps=[],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search({"闭水试验持续多久": [_search_result(entry)]}),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        assert run.status == RUN_COMPLETED
        assert run.actual_answer_mode == ANSWER_MODE_INVESTIGATE
        investigation, rounds, queries = await _load_investigation(db, run.id)
        assert investigation.current_round == 2
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        assert investigation.status == INVESTIGATION_STATUS_COMPLETED
        assert all(round_row.status == INVESTIGATION_ROUND_COMPLETED for round_row in rounds)
        assert len(queries) == 1
        assert investigation.total_queries_executed == 1
        answer = json.loads(run.answer_json)
        assert answer["citations"][0]["quote"] == "闭水试验通常持续 24 小时"
        summary = json.loads(run.investigation_summary)
        assert summary["stop_reason"] == STOP_REASON_CONTROLLER_COMPLETE
        assert summary["rounds_completed"] == 2
        assert len(calls) == 2


@pytest.mark.asyncio
async def test_investigation_multi_round_discovery_and_citations(monkeypatch) -> None:
    """多轮补查：不同查询发现不同 Entry，最终引用两轮证据。"""
    async with async_session_factory() as db:
        user = await create_user(db, "多轮调查")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "多轮项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验验收前不得放水。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="验收规则",
            content="闭水试验验收前不得放水。",
            quote="闭水试验验收前不得放水",
        )
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                    gaps=["放水时机未覆盖"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验放水时机"],
                    gaps=[],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_ANSWER,
                    coverage=["时长", "放水时机"],
                    gaps=[],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {
                    "闭水试验持续多久": [_search_result(entry_a)],
                    "闭水试验放水时机": [_search_result(entry_b)],
                }
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        assert run.status == RUN_COMPLETED
        investigation, rounds, queries = await _load_investigation(db, run.id)
        assert investigation.current_round == 3
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        assert investigation.total_queries_executed == 2
        assert investigation.distinct_entries_found == 2
        assert len(queries) == 2
        assert queries[0].normalized_query_hash == query_fingerprint("闭水试验持续多久")
        answer = json.loads(run.answer_json)
        assert len(answer["citations"]) == 2
        assert {item["entry_title"] for item in answer["citations"]} == {
            "闭水试验",
            "验收规则",
        }
        assert investigation.coverage_summary
        assert json.loads(investigation.coverage_summary) == [
            "当前回答采用 2 条核验证据，涉及 2 条正式知识"
        ]


@pytest.mark.asyncio
async def test_investigation_duplicate_query_stops_no_progress(monkeypatch) -> None:
    """控制器只返回重复查询：不执行、以 no_progress 停止。"""
    async with async_session_factory() as db:
        user = await create_user(db, "重复查询")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "重复项目")
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
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["  闭水试验  持续多久  "],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search({"闭水试验持续多久": [_search_result(entry)]}),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        investigation, rounds, queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_NO_PROGRESS
        assert investigation.total_queries_executed == 1
        assert len(queries) == 1
        # 第二轮控制器观察提交，但没有执行新查询
        assert len(rounds) == 2
        assert rounds[1].queries_executed == 0


@pytest.mark.asyncio
async def test_investigation_no_progress_when_search_empty(monkeypatch) -> None:
    """一轮搜索无新增 Entry/Evidence：以 no_progress 停止并明确知识不足。"""
    async with async_session_factory() as db:
        user = await create_user(db, "无进展调查")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空项目")
        _conversation, run = await _investigation_run(
            db, user, workspace, "完全不存在的主题"
        )
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["不存在的主题"],
                )
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search({"不存在的主题": []}),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        investigation, rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_NO_PROGRESS
        assert investigation.status == INVESTIGATION_STATUS_INSUFFICIENT
        assert run.status == RUN_PARTIAL
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        assert answer["citations"] == []


@pytest.mark.asyncio
async def test_investigation_budget_stops(monkeypatch) -> None:
    """每种硬预算：轮次/总查询/Entry/Evidence 上限确定性停止。"""
    from app.core.config import get_settings

    async with async_session_factory() as db:
        user = await create_user(db, "预算调查")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "预算项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验验收前不得放水。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="验收规则",
            content="闭水试验验收前不得放水。",
            quote="闭水试验验收前不得放水",
        )
        always_search = _controller_sequence(
            [
                InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验"],
                )
            ]
        )[0]
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            always_search,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {
                    "闭水试验": [_search_result(entry_a), _search_result(entry_b)],
                }
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        settings = get_settings()
        # 轮次预算：最多 1 轮
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_rounds", 1)
        _conversation, run = await _fresh_investigation_run(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_MAX_ROUNDS
        assert investigation.current_round == 1

        # 总查询预算：最多 1 个不同查询
        monkeypatch.setattr(
            settings, "knowledge_agent_investigation_max_total_queries", 1
        )
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_rounds", 3)
        _conversation, run = await _fresh_investigation_run(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_QUERY_BUDGET

        # Entry 预算：最多 1 个不同 Entry
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_entries", 1)
        monkeypatch.setattr(
            settings, "knowledge_agent_investigation_max_total_queries", 6
        )
        _conversation, run = await _fresh_investigation_run(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_ENTRY_BUDGET

        # Evidence 预算：最多 1 条可引用 Evidence
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_entries", 30)
        monkeypatch.setattr(
            settings, "knowledge_agent_investigation_max_evidence", 1
        )
        _conversation, run = await _fresh_investigation_run(db, user, workspace)
        await db.commit()
        await execute_run(db, run)
        await db.commit()
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_EVIDENCE_BUDGET


@pytest.mark.asyncio
async def test_investigation_entry_budget_admits_only_remaining_in_batch(
    monkeypatch,
) -> None:
    """单轮搜索返回多个新 Entry 时只接纳剩余预算数量，任何计数不超上限。"""
    from app.core.config import get_settings

    async with async_session_factory() as db:
        user = await create_user(db, "批量预算")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "批量项目")
        entries = []
        for index in range(4):
            node = await create_child_node(db, project, f"节点{index}")
            source, attachment = await create_source_attachment(
                db,
                workspace,
                project,
                text_content=f"批量记录 {index}：闭水试验持续 24 小时。",
            )
            entries.append(
                await create_entry_with_evidence(
                    db,
                    project,
                    node,
                    source,
                    attachment,
                    title=f"批量条目 {index}",
                    content=f"批量记录 {index}：闭水试验持续 24 小时。",
                    quote=f"批量记录 {index}：闭水试验持续 24 小时",
                )
            )
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["批量记录"],
                )
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {"批量记录": [_search_result(entry) for entry in entries]}
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        settings = get_settings()
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_entries", 2)
        monkeypatch.setattr(
            settings, "knowledge_agent_investigation_max_total_queries", 6
        )
        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        investigation, rounds, queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_ENTRY_BUDGET
        assert investigation.distinct_entries_found == 2
        assert (
            investigation.distinct_entries_found
            <= settings.knowledge_agent_investigation_max_entries
        )
        assert rounds[0].entries_added == 2
        assert len(queries) == 1
        counts = json.loads(queries[0].result_counts_json)
        # 命中 4 个候选，但只接纳剩余预算内的 2 个进入读取与账本
        assert counts["hits"] == 4
        assert counts["new_entries"] == 4
        assert counts["entries_added"] == 2


@pytest.mark.asyncio
async def test_investigation_query_counts_are_per_query_increments(
    monkeypatch,
) -> None:
    """同一轮多条查询分别记录自身增量，Round 再汇总，不写成累计值。"""
    from app.core.config import get_settings

    async with async_session_factory() as db:
        user = await create_user(db, "逐查询计数")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "计数项目")
        entry_a = None
        entry_b = None
        entry_c = None
        for index in range(3):
            node = await create_child_node(db, project, f"计数节点{index}")
            source, attachment = await create_source_attachment(
                db,
                workspace,
                project,
                text_content=f"计数记录 {index}：闭水试验持续 24 小时。",
            )
            entry = await create_entry_with_evidence(
                db,
                project,
                node,
                source,
                attachment,
                title=f"计数条目 {index}",
                content=f"计数记录 {index}：闭水试验持续 24 小时。",
                quote=f"计数记录 {index}：闭水试验持续 24 小时",
            )
            if index == 0:
                entry_a = entry
            elif index == 1:
                entry_b = entry
            else:
                entry_c = entry
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["查询一", "查询二"],
                )
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {
                    "查询一": [_search_result(entry_a), _search_result(entry_b)],
                    "查询二": [_search_result(entry_c)],
                }
            ),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        settings = get_settings()
        monkeypatch.setattr(settings, "knowledge_agent_investigation_max_entries", 30)
        monkeypatch.setattr(
            settings, "knowledge_agent_investigation_max_total_queries", 6
        )
        await execute_run(db, run)
        await db.commit()
        investigation, rounds, queries = await _load_investigation(db, run.id)
        assert investigation.distinct_entries_found == 3
        assert len(queries) == 2
        first = json.loads(queries[0].result_counts_json)
        second = json.loads(queries[1].result_counts_json)
        # 第一条新增 2、第二条新增 1：不能把第二条写成累计 3
        assert first["entries_added"] == 2
        assert second["entries_added"] == 1
        assert rounds[0].entries_added == 3
        assert rounds[0].queries_executed == 2


@pytest.mark.asyncio
async def test_investigation_insufficient_keeps_gaps_and_partial(monkeypatch) -> None:
    """控制器判断知识不足：保留未解决缺口，回答带已有证据与缺口说明。"""
    async with async_session_factory() as db:
        user = await create_user(db, "缺口调查")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "缺口项目")
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
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验持续多久"],
                    coverage=["时长"],
                    gaps=["放水时机"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_INSUFFICIENT,
                    coverage=["时长"],
                    gaps=["放水时机无来源"],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search({"闭水试验持续多久": [_search_result(entry)]}),
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_INSUFFICIENT
        # 搜索前控制器的缺口不是终态事实；最终综合只保留已校验答案的摘要。
        assert json.loads(investigation.gaps_summary) == []
        summary = json.loads(run.investigation_summary)
        assert summary["gaps"] == []
        answer = json.loads(run.answer_json)
        assert answer["citations"]


@pytest.mark.asyncio
async def test_investigation_conflicts_kept_with_both_evidence(monkeypatch) -> None:
    """冲突：不同有效 Evidence 支持的矛盾 Entry 并列展示，不替用户裁决。"""
    async with async_session_factory() as db:
        user = await create_user(db, "冲突调查")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "冲突项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验持续 48 小时。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="说法甲",
            content="闭水试验持续 24 小时。",
            quote="闭水试验持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="说法乙",
            content="闭水试验持续 48 小时。",
            quote="闭水试验持续 48 小时",
        )
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验时长"],
                    conflicts=["时长说法矛盾"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_ANSWER,
                    conflicts=["时长说法矛盾"],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {"闭水试验时长": [_search_result(entry_a), _search_result(entry_b)]}
            ),
        )

        async def _conflict_synthesis(
            db,
            workspace_id,
            query,
            scope_label,
            entries,
            *,
            purpose=None,
            synthesis_context=None,
        ):
            handles = []
            for item in entries:
                for evidence in item.get("evidences", []):
                    handles.append(evidence["handle"])
            return (
                KnowledgeAnswerDraft(
                    answer="双方说法并存。",
                    citations=[
                        KnowledgeCitationDraft(evidence_handle=handle)
                        for handle in handles
                    ],
                    conflicts=[
                        KnowledgeConflictDraft(
                            evidence_handle_a=handles[0],
                            evidence_handle_b=handles[1],
                            summary="时长说法矛盾",
                        )
                    ]
                    if len(handles) >= 2
                    else [],
                ),
                StageMeta(
                    purpose="synthesis",
                    provider="llm",
                    model="fake-synthesis",
                    is_fallback=False,
                    error=None,
                    duration_ms=1,
                ),
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _conflict_synthesis,
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        investigation, _rounds, _queries = await _load_investigation(db, run.id)
        assert investigation.stop_reason == STOP_REASON_CONTROLLER_COMPLETE
        assert json.loads(investigation.conflicts_summary) == ["时长说法矛盾"]
        answer = json.loads(run.answer_json)
        assert len(answer["conflicts"]) == 1
        assert answer["conflicts"][0]["summary"] == "时长说法矛盾"
        assert len(answer["citations"]) == 2
        assert run.status == RUN_COMPLETED


@pytest.mark.asyncio
async def test_investigation_working_set_only_cited_entries(monkeypatch) -> None:
    """输出工作集只含最终有效引用使用的 Entry；仅搜索发现的 Entry 不加入。"""
    async with async_session_factory() as db:
        user = await create_user(db, "工作集过滤")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "过滤项目")
        node_a = await create_child_node(db, project, "施工")
        node_b = await create_child_node(db, project, "验收")
        source_a, attachment_a = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
        )
        source_b, attachment_b = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="庭院树木冬季养护要点。",
        )
        entry_a = await create_entry_with_evidence(
            db,
            project,
            node_a,
            source_a,
            attachment_a,
            title="闭水试验",
            content="闭水试验通常持续 24 小时。",
            quote="闭水试验通常持续 24 小时",
        )
        entry_b = await create_entry_with_evidence(
            db,
            project,
            node_b,
            source_b,
            attachment_b,
            title="庭院养护",
            content="庭院树木冬季养护要点。",
            quote="庭院树木冬季养护要点",
        )
        _conversation, run = await _investigation_run(
            db, user, workspace, "闭水试验持续多久？"
        )
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["闭水试验"],
                ),
                __import__(
                    "app.agents.investigation", fromlist=["InvestigationControllerDraft"]
                ).InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_ANSWER,
                    coverage=["时长"],
                ),
            ]
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _scripted_search(
                {"闭水试验": [_search_result(entry_a), _search_result(entry_b)]}
            ),
        )
        # 综合回答只引用 entry_a
        async def _cite_first_only(
            db,
            workspace_id,
            query,
            scope_label,
            entries,
            *,
            purpose=None,
            synthesis_context=None,
        ):
            handle_a = ""
            for item in entries:
                if item["entry_id"] == entry_a.id and item.get("evidences"):
                    handle_a = item["evidences"][0]["handle"]
                    break
            return (
                KnowledgeAnswerDraft(
                    answer="只引用闭水试验。",
                    citations=[KnowledgeCitationDraft(evidence_handle=handle_a)]
                    if handle_a
                    else [],
                ),
                StageMeta(
                    purpose="synthesis",
                    provider="llm",
                    model="fake-synthesis",
                    is_fallback=False,
                    error=None,
                    duration_ms=1,
                ),
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _cite_first_only,
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        assert run.status == RUN_COMPLETED
        assert run.output_context_version_id is not None
        items = (
            await db.execute(
                select(KnowledgeWorkingSetItem).where(
                    KnowledgeWorkingSetItem.context_version_id
                    == run.output_context_version_id
                )
            )
        ).scalars().all()
        entry_ids = {item.entry_id for item in items}
        assert entry_ids == {entry_a.id}
        assert entry_b.id not in entry_ids


@pytest.mark.asyncio
async def test_quick_path_does_not_create_investigation(monkeypatch) -> None:
    """quick 路径保持单轮：不创建 Investigation，也不写调查摘要。"""
    async with async_session_factory() as db:
        user = await create_user(db, "快速路径")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "快速项目")
        node = await create_child_node(db, project, "施工")
        source, attachment = await create_source_attachment(
            db,
            workspace,
            project,
            text_content="闭水试验通常持续 24 小时。",
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
        _conversation, run = await _conversation_and_run(
            db, user, workspace, "闭水试验持续多久？"
        )
        run.status = RUN_PROCESSING
        await db.commit()

        from app.services.knowledge_agent.investigation import AnswerModeResolution

        async def _quick_mode(db, *, workspace_id, request_mode, objective, topic_summary):
            return AnswerModeResolution(mode="quick")

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.resolve_answer_mode",
            _quick_mode,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        run = await db.get(KnowledgeAgentRun, run.id)
        assert run.status == RUN_COMPLETED
        assert run.actual_answer_mode == "quick"
        assert run.investigation_summary is None
        investigation = (
            await db.execute(
                select(KnowledgeInvestigation).where(
                    KnowledgeInvestigation.run_id == run.id
                )
            )
        ).scalar_one_or_none()
        assert investigation is None
        answer = json.loads(run.answer_json)
        assert answer["citations"][0]["quote"] == "闭水试验通常持续 24 小时"


@pytest.mark.asyncio
async def test_investigation_search_uses_original_query_not_normalized(
    monkeypatch,
) -> None:
    """检索使用清理后的原文（保留空格），规范化文本只用于指纹去重。"""
    async with async_session_factory() as db:
        user = await create_user(db, "原文检索")
        workspace = await create_workspace(db, user)
        project = await create_project(db, workspace, "原文项目")
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
        _conversation, run = await _investigation_run(db, user, workspace)
        await db.commit()

        controller, _calls = _controller_sequence(
            [
                InvestigationControllerDraft(
                    action=INVESTIGATION_ACTION_SEARCH,
                    queries=["  water   test  "],
                ),
                InvestigationControllerDraft(action=INVESTIGATION_ACTION_ANSWER),
            ]
        )
        received_queries: list[str] = []

        async def _capturing_search(
            db,
            ctx,
            query,
            *,
            recall_limit,
            context_limit,
            seed_entries=None,
        ):
            received_queries.append(query)
            ctx.discovered_entry_ids.add(entry.id)
            return SearchToolOutput(items=[_search_result(entry)])

        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_investigation_controller",
            controller,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.search_confirmed_knowledge",
            _capturing_search,
        )
        monkeypatch.setattr(
            "app.services.knowledge_agent.investigation_runner.run_knowledge_answer_agent",
            _synthesis_agent(),
        )

        await execute_run(db, run)
        await db.commit()
        # 控制器查询经校验去空白后为 "water test"，检索必须收到原文而非 "watertest"
        assert received_queries == ["water test"]
