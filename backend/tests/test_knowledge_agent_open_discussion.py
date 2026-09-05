"""开放讨论代表性评估与安全硬门禁测试。

覆盖模型优先、知识优先、混合依据、仅我的知识库、当前陈述冲突、
时效/高风险、外部材料缺口与同义表达；硬门禁保证伪造 Citation、
突破 knowledge_only、跨 Workspace/项目读取、静默降级和伪装实时外部
结果的数量均为零。
"""

import json

import pytest
from sqlalchemy import select

from app.agents.knowledge_agent import (
    OPEN_ANSWER_PROMPT_SUFFIX,
    KnowledgeAnswerDraft,
    KnowledgeAnswerPointDraft,
    KnowledgeCitationDraft,
)
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentModelInvocation,
    KnowledgeAgentRun,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    ANSWER_MODE_QUICK,
    PURPOSE_ANSWER,
    PURPOSE_BASIS_ROUTE,
    RUN_COMPLETED,
    RUN_PROCESSING,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.basis import BasisPlan
from app.services.knowledge_agent.follow_up import ContextDecisionResult
from app.services.knowledge_agent.observability import StageMeta
from app.services.knowledge_agent.runner import execute_run
from app.services.knowledge_agent.tools import RunToolContext
from tests._knowledge_agent_fixtures import (
    create_child_node,
    create_entry_with_evidence,
    create_project,
    create_source_attachment,
    create_user,
    create_workspace,
)
from tests.test_knowledge_agent_runner import (
    _conversation_and_run,
    _evidence_for_run,
)


@pytest.fixture(autouse=True)
def _fixed_context_and_modes(monkeypatch):
    """固定上下文决策与 quick 回答模式，评估只关注依据行为。"""

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
            topic_label="开放讨论",
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
        from app.services.knowledge_agent.investigation import (
            AnswerModeResolution,
        )

        return AnswerModeResolution(mode="quick")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_answer_mode",
        _resolve_mode,
    )

    async def _resolve_result_mode(
        db,
        *,
        workspace_id,
        request_mode,
        objective,
        scope_label,
        topic_summary,
    ):
        from app.services.knowledge_agent.result_mode import ResultModeResolution

        return ResultModeResolution(mode="answer")

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_result_mode",
        _resolve_result_mode,
    )


def _plan_meta(strategy: str) -> StageMeta:
    return StageMeta(
        purpose=PURPOSE_BASIS_ROUTE,
        provider="llm",
        model="fake-basis",
        is_fallback=False,
        error=None,
        duration_ms=1,
    )


def _patch_plan(monkeypatch, strategy: str):
    """固定规划策略；候选用户陈述取全部允许消息（评估需要）。"""

    async def _plan(
        db,
        *,
        workspace_id,
        request_basis_mode,
        objective,
        scope_label,
        topic_summary,
        context_decision,
        current_message,
        allowed_statements,
        feature_enabled,
    ):
        from app.services.knowledge_agent.basis import (
            basis_strategy_needs_grove,
            basis_strategy_uses_user_statements,
        )

        return BasisPlan(
            strategy=strategy,
            needs_grove=basis_strategy_needs_grove(strategy),
            requires_external_material=strategy == "external_needed",
            candidate_statement_ids=(
                [item.message_id for item in allowed_statements]
                if basis_strategy_uses_user_statements(strategy)
                else []
            ),
            degraded=False,
            meta=_plan_meta(strategy),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.runner.resolve_basis_plan",
        _plan,
    )


def _general_answer_agent():
    """返回无引用开放要点（模型优先/外部一般框架）。"""

    async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
        return (
            KnowledgeAnswerDraft(
                lead="一般框架。",
                points=[
                    KnowledgeAnswerPointDraft(
                        text="先明确边界，再核对可验证信息。",
                        evidence_handles=[],
                    )
                ],
                core_question_answered=True,
                coverage_complete=True,
            ),
            StageMeta(
                purpose=PURPOSE_ANSWER,
                provider="llm",
                model="fake-answer",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    return _fake


def _cited_answer_agent(with_text: str | None = None, *, with_model: bool = False):
    """引用回答上下文里第一个 Evidence 句柄的替身。"""

    async def _fake(db, workspace_id, query, scope_label, entries, **kwargs):
        handle = ""
        for item in entries:
            if item.get("evidences"):
                handle = item["evidences"][0]["handle"]
                break
        return (
            KnowledgeAnswerDraft(
                answer=with_text or "闭水试验通常持续 24 小时。",
                points=[
                    KnowledgeAnswerPointDraft(text="闭水试验通常持续 24 小时。",
                                              evidence_handles=[handle]),
                    KnowledgeAnswerPointDraft(text="可先按你提供的预算预留验收时间。"),
                ] if with_model else [],
                citations=[KnowledgeCitationDraft(evidence_handle=handle)]
                if handle
                else [],
                core_question_answered=True,
                coverage_complete=True,
            ),
            StageMeta(
                purpose=PURPOSE_ANSWER,
                provider="llm",
                model="fake-answer",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    return _fake


async def _seeded_context(db, workspace):
    """创建一条带真实 Evidence 的正式知识（评估 Grove 路径）。"""
    project = await create_project(db, workspace, "评估项目")
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
    return entry


async def _run_fixture(db, user, workspace, message: str, *, basis_mode: str):
    """提交带明确依据模式的评估 Run。"""
    conversation, run = await _conversation_and_run(db, user, workspace, message)
    run.request_basis_mode = basis_mode
    run.status = RUN_PROCESSING
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_model_first_general_question_skips_grove(monkeypatch) -> None:
    """评估：模型优先通用问题不调用 Grove，直接开放回答。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估模型优先")
        workspace = await create_workspace(db, user)
        run = await _run_fixture(
            db, user, workspace, "什么是闭水试验？", basis_mode="auto"
        )
        _patch_plan(monkeypatch, "model_first")
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _general_answer_agent(),
        )
        await execute_run(db, run)
        await db.commit()
        assert run.status == RUN_COMPLETED
        basis = json.loads(run.answer_basis_json)
        assert basis["grove"]["used"] is False
        assert basis["model_knowledge"]["used"] is True
        assert run.actual_answer_mode == ANSWER_MODE_QUICK


@pytest.mark.asyncio
async def test_knowledge_first_personal_question_uses_grove(monkeypatch) -> None:
    """评估：知识优先读取 Grove 并生成带引用回答。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估知识优先")
        workspace = await create_workspace(db, user)
        await _seeded_context(db, workspace)
        run = await _run_fixture(
            db,
            user,
            workspace,
            "我的项目闭水试验通常要多久？",
            basis_mode="auto",
        )
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        handle = verified[0].evidence_handle
        await db.commit()
        _patch_plan(monkeypatch, "knowledge_first")
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _cited_answer_agent(),
        )
        await execute_run(db, run)
        await db.commit()
        assert run.status == RUN_COMPLETED
        answer = json.loads(run.answer_json)
        assert answer["citations"][0]["evidence_handle"] == handle
        basis = json.loads(run.answer_basis_json)
        assert basis["grove"]["used"] is True


@pytest.mark.asyncio
async def test_hybrid_uses_statements_grove_and_model(monkeypatch) -> None:
    """评估：混合依据三类信息都可追溯。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估混合")
        workspace = await create_workspace(db, user)
        await _seeded_context(db, workspace)
        run = await _run_fixture(
            db,
            user,
            workspace,
            "预算上限 30 万，闭水试验怎么排？",
            basis_mode="auto",
        )
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        assert verified
        await db.commit()
        _patch_plan(monkeypatch, "hybrid")
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _cited_answer_agent(with_model=True),
        )
        await execute_run(db, run)
        await db.commit()
        basis = json.loads(run.answer_basis_json)
        assert basis["grove"]["citation_count"] >= 1
        assert basis["user_statements"]["message_ids"]
        assert basis["model_knowledge"]["used"] is True


@pytest.mark.asyncio
async def test_knowledge_only_without_evidence_is_insufficient(monkeypatch) -> None:
    """评估：仅我的知识库无证据时严格不足，不用模型通用知识补齐。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估仅知识")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空评估项目")
        run = await _run_fixture(
            db,
            user,
            workspace,
            "不存在的主题",
            basis_mode="knowledge_only",
        )
        async def _forbidden(*args, **kwargs):  # pragma: no cover
            raise AssertionError("knowledge_only 不得调用回答模型")

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _forbidden,
        )
        await execute_run(db, run)
        await db.commit()
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"
        basis = json.loads(run.answer_basis_json)
        assert basis["model_knowledge"]["used"] is False


@pytest.mark.asyncio
async def test_statement_conflict_presented_without_verdict(monkeypatch) -> None:
    """评估：用户陈述与 Grove 冲突时并列说明，不静默覆盖或裁决。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估冲突")
        workspace = await create_workspace(db, user)
        entry = await _seeded_context(db, workspace)
        run = await _run_fixture(
            db,
            user,
            workspace,
            "我上次只做了 12 小时，规范怎么说？",
            basis_mode="auto",
        )
        ctx = RunToolContext(
            run_id=run.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            project_name=None,
        )
        verified = await _evidence_for_run(db, ctx)
        handle = verified[0].evidence_handle
        await db.commit()
        _patch_plan(monkeypatch, "hybrid")
        async def _conflict_answer(db, workspace_id, query, scope_label, entries, **kwargs):
            assert kwargs.get("user_statements")
            assert entries, "混合依据不应走到空 Grove 分支"
            return (
                KnowledgeAnswerDraft(
                    lead="你提到上次只做 12 小时，而验收手册写的是 24 小时。",
                    citations=[KnowledgeCitationDraft(evidence_handle=handle)],
                    conflicts=[],
                    core_question_answered=True,
                    coverage_complete=True,
                ),
                StageMeta(
                    purpose=PURPOSE_ANSWER,
                    provider="llm",
                    model="fake-answer",
                    is_fallback=False,
                    error=None,
                    duration_ms=1,
                ),
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _conflict_answer,
        )
        await execute_run(db, run)
        await db.commit()
        assert entry is not None
        from app.models import KnowledgeAgentEvidence

        rows = (
            await db.execute(
                select(KnowledgeAgentEvidence).where(
                    KnowledgeAgentEvidence.run_id == run.id,
                    KnowledgeAgentEvidence.handle == handle,
                )
            )
        ).scalars().all()
        assert rows
        assert rows[0].is_citable is True
        from app.services.knowledge_agent.evidence import resolve_evidence_handles

        resolved = await resolve_evidence_handles(db, run.id, [handle])
        assert handle in resolved
        answer = json.loads(run.answer_json)
        assert "24 小时" in answer["answer"]
        assert len(answer["citations"]) == 1
        basis = json.loads(run.answer_basis_json)
        assert basis["user_statements"]["message_ids"]
        assert basis["grove"]["used"] is True


@pytest.mark.asyncio
async def test_external_needed_time_sensitive_question_keeps_boundary(
    monkeypatch,
) -> None:
    """评估：时效/高风险问题只给一般框架并显示外部材料缺口。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估外部")
        workspace = await create_workspace(db, user)
        run = await _run_fixture(
            db,
            user,
            workspace,
            "现在的防水验收规范是什么？",
            basis_mode="auto",
        )
        _patch_plan(monkeypatch, "external_needed")
        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _general_answer_agent(),
        )
        await execute_run(db, run)
        await db.commit()
        basis = json.loads(run.answer_basis_json)
        assert basis["external_material"]["status"] == "required_unavailable"
        assert basis["model_knowledge"]["used"] is True
        assert basis["grove"]["used"] is False


@pytest.mark.asyncio
async def test_natural_language_knowledge_only_synonym_skips_planner(
    monkeypatch,
) -> None:
    """评估：自然语言同义表达（只用我的知识库）直接固化限制。"""
    async with async_session_factory() as db:
        user = await create_user(db, "评估同义")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空项目")
        run = await _run_fixture(
            db,
            user,
            workspace,
            "只用我的知识库说说闭水试验，别加通用知识",
            basis_mode="auto",
        )
        from app.core.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(
            settings,
            "knowledge_agent_open_discussion_enabled",
            True,
        )
        await execute_run(db, run)
        await db.commit()
        assert run.planned_basis_strategy == "knowledge_only"
        invocations = (
            await db.execute(
                select(KnowledgeAgentModelInvocation).where(
                    KnowledgeAgentModelInvocation.run_id == run.id,
                    KnowledgeAgentModelInvocation.purpose == PURPOSE_BASIS_ROUTE,
                )
            )
        ).scalars().all()
        assert invocations == []


@pytest.mark.asyncio
async def test_guardrail_forged_citation_dropped() -> None:
    """硬门禁：伪造/越权 Citation 不会进入最终回答。"""
    from app.agents.knowledge_agent import KnowledgeCitationDraft
    from app.services.knowledge_agent.evidence import build_validated_answer

    async with async_session_factory() as db:
        user = await create_user(db, "门禁伪造")
        workspace = await create_workspace(db, user)
        conversation = KnowledgeConversation(
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            title="门禁伪造测试",
        )
        db.add(conversation)
        await db.flush()
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot="active",
            max_retries=1,
        )
        db.add(run)
        await db.flush()
        await db.commit()
        draft = KnowledgeAnswerDraft(
            answer="伪造引用。",
            citations=[KnowledgeCitationDraft(evidence_handle="ev_forged_handle")],
            core_question_answered=True,
            coverage_complete=True,
        )
        answer, _stats = await build_validated_answer(
            db,
            run.id,
            draft,
            allow_unreferenced=True,
        )
        assert answer.citations == []
        assert answer.status == "partial"
        assert "forged" not in json.dumps(answer.model_dump())


@pytest.mark.asyncio
async def test_guardrail_knowledge_only_cannot_be_broadened(monkeypatch) -> None:
    """硬门禁：knowledge_only 不允许规划器/回答器引入通用知识。"""
    async with async_session_factory() as db:
        user = await create_user(db, "门禁限制")
        workspace = await create_workspace(db, user)
        await create_project(db, workspace, "空项目")
        run = await _run_fixture(
            db,
            user,
            workspace,
            "解释一个概念",
            basis_mode="knowledge_only",
        )
        async def _answer_broadened(*args, **kwargs):  # pragma: no cover
            raise AssertionError("knowledge_only 不得调用开放回答器")

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.run_knowledge_answer_agent",
            _answer_broadened,
        )
        await execute_run(db, run)
        await db.commit()
        assert run.planned_basis_strategy == "knowledge_only"
        answer = json.loads(run.answer_json)
        assert answer["status"] == "insufficient"


@pytest.mark.asyncio
async def test_guardrail_cross_workspace_statement_rejected() -> None:
    """硬门禁：跨 Workspace/项目的消息不能作为用户陈述。"""
    from app.services.knowledge_agent.basis import load_allowed_user_statements

    async with async_session_factory() as db:
        owner = await create_user(db, "门禁A")
        workspace_a = await create_workspace(db, owner)
        outsider = await create_user(db, "门禁B")
        workspace_b = await create_workspace(db, outsider)
        conversation_a = KnowledgeConversation(
            workspace_id=workspace_a.id,
            owner_user_id=owner.id,
            scope_type=SCOPE_WORKSPACE,
            title="A 对话",
        )
        db.add(conversation_a)
        await db.flush()
        outsider_message = KnowledgeMessage(
            conversation_id=conversation_a.id,
            role="user",
            message_type="user",
            content="预算 30 万",
            scope_type=SCOPE_WORKSPACE,
        )
        db.add(outsider_message)
        await db.flush()
        allowed = await load_allowed_user_statements(
            db,
            workspace_id=workspace_b.id,
            owner_user_id=outsider.id,
            conversation_id=conversation_a.id,
            scope_type=SCOPE_WORKSPACE,
            project_id=None,
            context_decision="continue",
            current_message_id=outsider_message.id,
            input_context_version_id=None,
            limit=6,
            message_chars=800,
        )
        assert allowed == []


@pytest.mark.asyncio
async def test_guardrail_no_silent_degradation_and_no_realtime_disguise(
    monkeypatch,
) -> None:
    """硬门禁：规划降级可见；外部材料缺口不伪装联网结果。"""
    async with async_session_factory() as db:
        user = await create_user(db, "门禁降级")
        workspace = await create_workspace(db, user)
        run = await _run_fixture(
            db,
            user,
            workspace,
            "解释概念",
            basis_mode="auto",
        )
        async def _fallback_plan(
            db,
            *,
            workspace_id,
            request_basis_mode,
            objective,
            scope_label,
            topic_summary,
            context_decision,
            current_message,
            allowed_statements,
            feature_enabled,
        ):
            return BasisPlan(
                strategy="knowledge_only",
                needs_grove=True,
                candidate_statement_ids=[],
                degraded=True,
                meta=StageMeta(
                    purpose=PURPOSE_BASIS_ROUTE,
                    provider="offline",
                    model=None,
                    is_fallback=True,
                    error="依据规划模型不可用",
                    duration_ms=1,
                ),
            )

        monkeypatch.setattr(
            "app.services.knowledge_agent.runner.resolve_basis_plan",
            _fallback_plan,
        )
        await execute_run(db, run)
        await db.commit()
        summary = json.loads(run.fallback_summary)
        assert summary["has_fallback"] is True
        assert any(
            stage["purpose"] == PURPOSE_BASIS_ROUTE for stage in summary["stages"]
        )
        # 展示与提示层面：不把模型训练知识描述为实时外部结果
        assert "不得声称已经联网" in OPEN_ANSWER_PROMPT_SUFFIX
        assert run.planned_basis_strategy == "knowledge_only"
