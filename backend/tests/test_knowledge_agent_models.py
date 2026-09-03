"""知识 Agent 数据模型、枚举与迁移约束测试。"""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.basis import (
    BASIS_ROUTE_PROMPT_VERSION,
    BASIS_ROUTE_SYSTEM_PROMPT,
    BasisRouteDraft,
    run_basis_planner,
)
from app.agents.composite_answer import (
    COMPOSITE_ANSWER_PLAN_SYSTEM_PROMPT,
    CompositeAnswerPlanDraft,
    run_composite_answer_planner,
)
from app.agents.knowledge_agent import (
    OPEN_ANSWER_PROMPT_SUFFIX,
    KnowledgeAnswerDraft,
    KnowledgeAnswerPointDraft,
    run_knowledge_answer_agent,
)
from app.agents.structured_query import (
    STRUCTURED_QUERY_PLAN_PROMPT_VERSION,
    StructuredQueryPlanDraft,
    run_structured_query_planner,
)
from app.db.session import async_session_factory
from app.models import (
    KnowledgeAgentEvidence,
    KnowledgeAgentRun,
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeWorkingSetItem,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.knowledge_agent import (
    ACTIVE_SLOT,
    BASIS_MODE_AUTO,
    BASIS_MODE_KNOWLEDGE_ONLY,
    BASIS_STRATEGIES,
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_MODEL_FIRST,
    CONTEXT_CLOSE_REASON_NEW_TOPIC,
    CONTEXT_STATUS_ACTIVE,
    CONTEXT_STATUS_CLOSED,
    PURPOSE_BASIS_ROUTE,
    PURPOSE_STRUCTURED_QUERY_PLAN,
    RUN_ACTIVE_STATUSES,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PROCESSING,
    RUN_TERMINAL_STATUSES,
    RUN_WAITING,
    SCOPE_WORKSPACE,
    STEP_BASIS_ROUTE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerOut,
    KnowledgeRunOut,
    KnowledgeRunSubmitRequest,
)
from app.services.knowledge_agent.basis import (
    BasisPlan,
    UserStatementCandidate,
    dump_basis_plan,
    resolve_basis_plan,
    restore_basis_plan,
    validate_statement_ids,
)
from app.services.knowledge_agent.runs import run_out


def test_structured_query_plan_rejects_unknown_scope_fields() -> None:
    """模型候选协议不接受 Workspace/项目或任意未知字段。"""
    with pytest.raises(ValidationError):
        StructuredQueryPlanDraft.model_validate(
            {
                "schema_version": "v1",
                "entry_set": {"schema_version": "v1", "project_id": 123},
                "outputs": [{"kind": "count"}],
            }
        )


@pytest.mark.asyncio
async def test_structured_query_planner_reports_offline_fallback() -> None:
    """未配置模型时规划失败可观测，且不生成伪造的确定性计划。"""
    async with async_session_factory() as db:
        _user, workspace = await _user_and_workspace(db, "结构化规划")
        plan, meta = await run_structured_query_planner(
            db,
            workspace.id,
            objective="最近半年有多少条经验",
            scope_label="全部知识",
        )

    assert plan is None
    assert meta.purpose == PURPOSE_STRUCTURED_QUERY_PLAN
    assert meta.is_fallback is True
    assert meta.provider == "offline"
    assert meta.error
    assert STRUCTURED_QUERY_PLAN_PROMPT_VERSION == "v1"


async def _user_and_workspace(db, prefix: str = "模型") -> tuple[User, Workspace]:
    """创建独立用户与 Workspace，避免测试间数据干扰。"""
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
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="模型测试对话",
    )
    db.add(conversation)
    await db.flush()
    return conversation


def test_run_status_contract() -> None:
    """Run 状态集合与合法路径关系保持稳定。"""
    assert RUN_ACTIVE_STATUSES == {RUN_WAITING, RUN_PROCESSING}
    assert RUN_TERMINAL_STATUSES == {RUN_COMPLETED, RUN_FAILED, "partial", "cancelled"}
    assert RUN_ACTIVE_STATUSES.isdisjoint(RUN_TERMINAL_STATUSES)


@pytest.mark.asyncio
async def test_message_client_id_idempotency_key() -> None:
    """同一对话重复 client_message_id 触发唯一约束，不同对话互不影响。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)

        for conversation in (first, second):
            db.add(
                KnowledgeMessage(
                    conversation_id=conversation.id,
                    role="user",
                    message_type="user",
                    content="问题",
                    client_message_id="client-1",
                    scope_type=SCOPE_WORKSPACE,
                )
            )
        await db.flush()

        db.add(
            KnowledgeMessage(
                conversation_id=first.id,
                role="user",
                message_type="user",
                content="重试问题",
                client_message_id="client-1",
                scope_type=SCOPE_WORKSPACE,
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_active_slot_unique_and_terminal_null() -> None:
    """同一对话只有一个活动槽；终态 active_slot 置空后允许多个终态 Run。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)

        def _run(status: str, active_slot: str | None) -> KnowledgeAgentRun:
            return KnowledgeAgentRun(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                scope_type=SCOPE_WORKSPACE,
                status=status,
                active_slot=active_slot,
                max_retries=1,
            )

        db.add(_run(RUN_WAITING, ACTIVE_SLOT))
        await db.flush()
        db.add(_run(RUN_WAITING, ACTIVE_SLOT))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 冲突 flush 已回滚；终态置空后允许同一对话出现多个终态 Run
        db.add(_run(RUN_COMPLETED, None))
        await db.flush()
        db.add(_run(RUN_FAILED, None))
        await db.flush()
        rows = (
            await db.execute(
                select(KnowledgeAgentRun).where(
                    KnowledgeAgentRun.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(row.active_slot is None for row in rows)


@pytest.mark.asyncio
async def test_evidence_handle_unique() -> None:
    """Evidence 句柄全局唯一，防止句柄复用。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot=ACTIVE_SLOT,
            max_retries=1,
        )
        db.add(run)
        await db.flush()

        def _evidence(handle: str) -> KnowledgeAgentEvidence:
            return KnowledgeAgentEvidence(
                run_id=run.id,
                handle=handle,
                quote="原文",
                content_fingerprint="fp",
                purpose="answer",
            )

        db.add(_evidence("ev_abc"))
        await db.flush()
        db.add(_evidence("ev_abc"))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_context_version_active_slot_unique_and_terminal_null() -> None:
    """同一对话最多一个活动上下文版本；终态置空后允许多个历史版本。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)

        def _version(
            status: str,
            active_slot: str | None,
            version_number: int = 1,
        ) -> KnowledgeContextVersion:
            return KnowledgeContextVersion(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                version_number=version_number,
                scope_type=SCOPE_WORKSPACE,
                topic_label="闭水试验",
                status=status,
                active_slot=active_slot,
            )

        db.add(_version(CONTEXT_STATUS_ACTIVE, ACTIVE_SLOT))
        await db.flush()
        db.add(_version(CONTEXT_STATUS_ACTIVE, ACTIVE_SLOT))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        db.add(_version(CONTEXT_STATUS_CLOSED, None, version_number=1))
        await db.flush()
        db.add(_version(CONTEXT_STATUS_CLOSED, None, version_number=2))
        await db.flush()
        rows = (
            await db.execute(
                select(KnowledgeContextVersion).where(
                    KnowledgeContextVersion.conversation_id == conversation.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(row.active_slot is None for row in rows)


@pytest.mark.asyncio
async def test_context_version_number_unique_per_conversation() -> None:
    """同一对话版本号唯一；不同对话允许相同版本号。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        first = await _conversation(db, user, workspace)
        second = await _conversation(db, user, workspace)

        def _version(conversation_id: int) -> KnowledgeContextVersion:
            return KnowledgeContextVersion(
                conversation_id=conversation_id,
                workspace_id=workspace.id,
                owner_user_id=user.id,
                version_number=1,
                scope_type=SCOPE_WORKSPACE,
                topic_label="主题",
                status=CONTEXT_STATUS_CLOSED,
                close_reason=CONTEXT_CLOSE_REASON_NEW_TOPIC,
                active_slot=None,
            )

        db.add(_version(first.id))
        await db.flush()
        db.add(_version(first.id))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        # 不同对话可以使用相同版本号
        db.add(_version(first.id))
        await db.flush()
        db.add(_version(second.id))
        await db.flush()


@pytest.mark.asyncio
async def test_working_set_item_unique_per_version() -> None:
    """同一版本内 Entry 线索不重复；entry_id 可空允许多个空版本项。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        version = KnowledgeContextVersion(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            version_number=1,
            scope_type=SCOPE_WORKSPACE,
            topic_label="闭水试验",
            status=CONTEXT_STATUS_ACTIVE,
            active_slot=ACTIVE_SLOT,
        )
        db.add(version)
        await db.flush()

        def _item(entry_id: int | None) -> KnowledgeWorkingSetItem:
            return KnowledgeWorkingSetItem(
                context_version_id=version.id,
                entry_id=entry_id,
                include_reason="cited",
                sort_order=0,
            )

        db.add(_item(100))
        await db.flush()
        db.add(_item(100))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

        db.add(_item(None))
        await db.flush()
        db.add(_item(None))
        await db.flush()


@pytest.mark.asyncio
async def test_run_context_fields_and_serialization() -> None:
    """Run 上下文契约字段可空且可序列化；旧 Run 无上下文不报错。"""
    async with async_session_factory() as db:
        user, workspace = await _user_and_workspace(db)
        conversation = await _conversation(db, user, workspace)
        run = KnowledgeAgentRun(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            owner_user_id=user.id,
            scope_type=SCOPE_WORKSPACE,
            status=RUN_PROCESSING,
            active_slot=ACTIVE_SLOT,
            max_retries=1,
        )
        db.add(run)
        await db.flush()
        await db.commit()

        out = run_out(run)
        assert isinstance(out, KnowledgeRunOut)
        assert out.request_context_mode is None
        assert out.context_decision is None
        assert out.context_degraded is False

        run.request_context_mode = "continue"
        run.context_decision = "continue"
        run.standalone_query = "闭水试验为什么不能提前放水？"
        run.topic_label = "闭水试验"
        run.context_meta_json = (
            '{"provider":"llm","model":"fake","is_fallback":true,"error":"失败"}'
        )
        await db.flush()
        await db.refresh(run)
        out = run_out(run)
        assert out.request_context_mode == "continue"
        assert out.context_decision == "continue"
        assert out.standalone_query == "闭水试验为什么不能提前放水？"
        assert out.topic_label == "闭水试验"
        assert out.context_degraded is True


def test_submit_request_defaults_and_answer_status() -> None:
    """context_mode 默认 auto；回答状态支持 clarification。"""
    request = KnowledgeRunSubmitRequest(client_message_id="x", message="问题")
    assert request.context_mode == "auto"
    assert (
        KnowledgeRunSubmitRequest(
            client_message_id="x", message="问题", context_mode="continue"
        ).context_mode
        == "continue"
    )
    answer = KnowledgeAnswerOut(answer="请补充主题", status="clarification")
    assert answer.status == "clarification"


def test_open_answer_prompt_contract() -> None:
    """开放回答提示允许无引用要点，但禁止伪造引用与实时结果。"""
    assert "允许使用模型通用知识" in OPEN_ANSWER_PROMPT_SUFFIX
    assert "不得生成 Citation" in OPEN_ANSWER_PROMPT_SUFFIX
    assert "不得声称已经联网" in OPEN_ANSWER_PROMPT_SUFFIX
    # 草稿要点本就允许零句柄；是否保留由服务端按依据模式校验
    point = KnowledgeAnswerPointDraft(text="一般解释")
    assert point.evidence_handles == []


def test_basis_contract_constants_and_request_defaults() -> None:
    """依据模式/策略常量与请求缺省语义保持稳定。"""
    assert BASIS_MODE_AUTO == "auto"
    assert BASIS_MODE_KNOWLEDGE_ONLY == "knowledge_only"
    assert BASIS_STRATEGY_KNOWLEDGE_ONLY in BASIS_STRATEGIES
    assert BASIS_STRATEGY_MODEL_FIRST in BASIS_STRATEGIES
    assert STEP_BASIS_ROUTE == "basis_route"
    assert PURPOSE_BASIS_ROUTE == "basis_route"
    assert BASIS_ROUTE_PROMPT_VERSION == "v2"

    # 新客户端显式提交 auto；旧客户端缺省 None（服务层按 knowledge_only 兼容）
    assert (
        KnowledgeRunSubmitRequest(
            client_message_id="x", message="问题", basis_mode="auto"
        ).basis_mode
        == BASIS_MODE_AUTO
    )
    assert (
        KnowledgeRunSubmitRequest(
            client_message_id="x", message="问题"
        ).basis_mode
        is None
    )
    with pytest.raises(ValidationError):
        KnowledgeRunSubmitRequest(
            client_message_id="x",
            message="问题",
            basis_mode="hybrid",
        )

    draft = BasisRouteDraft()
    assert draft.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
    assert draft.user_message_ids == []


@pytest.mark.asyncio
async def test_basis_planner_preserves_original_message(monkeypatch) -> None:
    """依据规划同时看到原始消息与独立问题，避免改写丢失依据要求。"""
    captured: dict[str, str] = {}

    class _Model:
        model_name = "fake-basis-model"

    class _Agent:
        def __init__(self, model, **kwargs):
            pass

        async def run(self, context: str):
            captured["context"] = context
            return type(
                "Result",
                (),
                {"output": BasisRouteDraft(strategy="knowledge_first")},
            )()

    async def _model(db, workspace_id):
        return _Model()

    monkeypatch.setattr("app.agents.basis.get_text_model", _model)
    monkeypatch.setattr("app.agents.basis.Agent", _Agent)

    draft, meta = await run_basis_planner(
        object(),
        1,
        objective="甲醛是什么，以及甲醛的来源和环保等级",
        current_message="结合我的知识库，先解释甲醛是什么，再说明来源和环保等级",
        scope_label="全部知识",
        topic_summary="甲醛",
        context_decision="continue",
        user_statements=[],
    )

    assert draft is not None and draft.strategy == "knowledge_first"
    assert meta.is_fallback is False
    assert "用户原始消息：结合我的知识库" in captured["context"]
    assert "独立问题：甲醛是什么" in captured["context"]
    assert "用户原始消息中的依据要求和限制必须优先" in BASIS_ROUTE_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_composite_answer_planner_preserves_raw_request_and_constraints(
    monkeypatch,
) -> None:
    """复合规划同时看到原始请求和检索改写，且不允许输出授权范围。"""
    from dataclasses import dataclass

    captured: dict[str, object] = {}

    class _Model:
        model_name = "fake-composite-model"

    @dataclass
    class _Usage:
        requests: int = 1

    class _Result:
        output = CompositeAnswerPlanDraft.model_validate(
            {
                "requirements": [
                    {
                        "id": "definition",
                        "order": 0,
                        "summary": "解释甲醛是什么",
                        "kind": "explain",
                        "basis_policy": "model_allowed",
                    },
                    {
                        "id": "sources",
                        "order": 1,
                        "summary": "说明个人知识中的来源",
                        "kind": "retrieve",
                        "basis_policy": "grove_required",
                    },
                ],
                "retrieval_requests": [
                    {
                        "id": "search",
                        "query": "甲醛来源",
                        "requirement_ids": ["sources"],
                    }
                ],
            }
        )
        @staticmethod
        def usage():
            return _Usage()

    class _Agent:
        def __init__(self, model, **kwargs):
            captured["system_prompt"] = kwargs["system_prompt"]

        async def run(self, context: str):
            captured["context"] = context
            return _Result()

    async def _model(db, workspace_id):
        return _Model()

    monkeypatch.setattr("app.agents.composite_answer.get_text_model", _model)
    monkeypatch.setattr("app.agents.composite_answer.Agent", _Agent)

    draft, meta = await run_composite_answer_planner(
        object(),
        1,
        current_message="结合我的知识库，先解释甲醛是什么，再说明来源",
        standalone_query="甲醛是什么以及来源",
        scope_label="全部知识",
        context_decision="new_topic",
        topic_summary="甲醛",
        user_statements=[],
        knowledge_only=False,
    )

    assert draft is not None and len(draft.requirements) == 2
    assert meta.is_fallback is False
    assert "用户原始消息：结合我的知识库" in str(captured["context"])
    assert "独立检索问题：甲醛是什么以及来源" in str(captured["context"])
    assert "不要按标点机械拆分" in COMPOSITE_ANSWER_PLAN_SYSTEM_PROMPT
    assert "Workspace" in str(captured["system_prompt"])

    with pytest.raises(ValidationError):
        CompositeAnswerPlanDraft.model_validate(
            {
                "requirements": [
                    {
                        "id": "r1",
                        "order": 0,
                        "summary": "越权",
                        "kind": "retrieve",
                        "basis_policy": "grove_only",
                    }
                ],
                "workspace_id": 999,
            }
        )


@pytest.mark.asyncio
async def test_composite_answer_model_receives_requirements_facts_and_both_queries(
    monkeypatch,
) -> None:
    """最终综合同时看到原始消息、检索改写、义务、Evidence 与工具事实。"""
    captured: dict[str, str] = {}

    class _Model:
        model_name = "fake-answer-model"

    class _Result:
        output = KnowledgeAnswerDraft(
            points=[
                KnowledgeAnswerPointDraft(
                    text="甲醛是一种化合物。",
                    requirement_ids=["r1"],
                )
            ]
        )

    class _Agent:
        def __init__(self, model, **kwargs):
            captured["system_prompt"] = kwargs["system_prompt"]

        async def run(self, context: str):
            captured["context"] = context
            return _Result()

    async def _model(db, workspace_id):
        return _Model()

    monkeypatch.setattr("app.agents.knowledge_agent.get_text_model", _model)
    monkeypatch.setattr("app.agents.knowledge_agent.Agent", _Agent)

    draft, meta = await run_knowledge_answer_agent(
        object(),
        1,
        "甲醛是什么，结合我的知识说明来源？",
        "全部知识",
        [],
        allow_model_knowledge=True,
        composite_context={
            "current_message": "甲醛是什么，结合我的知识说明来源？",
            "standalone_query": "甲醛定义与来源",
            "requirements": [
                {
                    "id": "r1",
                    "order": 0,
                    "basis_policy": "model_allowed",
                    "summary": "解释甲醛是什么",
                }
            ],
            "evidence_requirements": {"ev_" + "1" * 32: ["r1"]},
            "tool_facts": [
                {
                    "handle": "res_" + "2" * 24,
                    "requirement_ids": ["r1"],
                    "text": "符合条件的知识条目共 3 条。",
                }
            ],
            "execution_gaps": [],
            "retry_note": None,
        },
    )

    assert draft.points[0].requirement_ids == ["r1"]
    assert meta.is_fallback is False
    assert "用户原始消息：甲醛是什么" in captured["context"]
    assert "检索改写（只用于理解指代）：甲醛定义与来源" in captured["context"]
    assert "ev_" in captured["context"] and "res_" in captured["context"]
    assert "lead 必须留空" in captured["system_prompt"]


def test_basis_plan_explicit_and_natural_language_restriction(monkeypatch) -> None:
    """显式 knowledge_only 与自然语言限制跳过规划器并固化最严格策略。"""
    async def _forbidden_planner(*args, **kwargs):  # pragma: no cover
        raise AssertionError("显式限制不应调用规划器")

    monkeypatch.setattr(
        "app.services.knowledge_agent.basis.run_basis_planner",
        _forbidden_planner,
    )

    async def _resolve(
        mode: str | None,
        objective: str,
        message: str,
    ):
        return await resolve_basis_plan(
            object(),
            workspace_id=1,
            request_basis_mode=mode,
            objective=objective,
            scope_label="全部知识",
            topic_summary=None,
            context_decision="continue",
            current_message=message,
            allowed_statements=[
                UserStatementCandidate(message_id=10, content="预算上限是 30 万")
            ],
            feature_enabled=True,
        )

    import asyncio

    plan = asyncio.run(_resolve(BASIS_MODE_KNOWLEDGE_ONLY, "如何分配？", "如何分配？"))
    assert plan.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
    assert plan.meta is None
    assert plan.candidate_statement_ids == []

    # 自然语言明确限制：即使 auto 也直接固化 knowledge_only
    plan_nl = asyncio.run(
        _resolve(
            BASIS_MODE_AUTO,
            "只根据我的知识库回答，如何分配预算？",
            "只根据我的知识库回答，如何分配预算？",
        )
    )
    assert plan_nl.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
    assert plan_nl.meta is None

    # 等价的排除模型知识/仅限 Grove 表达同样是服务端硬门禁。
    restrictions = (
        "不要使用通用知识，只参考 Grove",
        "别用 AI 常识，按我的记录回答",
        "只看我已有的记录",
        "仅依据 Grove 里的内容",
    )
    for restriction in restrictions:
        plan_equivalent = asyncio.run(
            _resolve(BASIS_MODE_AUTO, restriction, restriction)
        )
        assert plan_equivalent.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
        assert plan_equivalent.meta is None


@pytest.mark.parametrize(
    "message",
    (
        "不要只根据我的知识库，也结合通用知识",
        "不要只使用通用知识，也结合我的知识库",
    ),
)
def test_basis_natural_language_broadening_is_not_misread(
    monkeypatch,
    message: str,
) -> None:
    """“不要只用某类依据”等放宽表达仍交给规划器，不误锁限制。"""
    import asyncio

    async def _model_first_planner(*args, **kwargs):
        return (
            BasisRouteDraft(strategy=BASIS_STRATEGY_MODEL_FIRST),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=1,
            ),
        )

    from app.services.knowledge_agent.observability import StageMeta

    monkeypatch.setattr(
        "app.services.knowledge_agent.basis.run_basis_planner",
        _model_first_planner,
    )
    plan = asyncio.run(
        resolve_basis_plan(
            object(),
            workspace_id=1,
            request_basis_mode=BASIS_MODE_AUTO,
            objective=message,
            scope_label="全部知识",
            topic_summary=None,
            context_decision="new_topic",
            current_message=message,
            allowed_statements=[],
            feature_enabled=True,
        )
    )
    assert plan.strategy == BASIS_STRATEGY_MODEL_FIRST


def test_basis_plan_snapshot_recovery_never_broadens_statement_subset() -> None:
    """恢复只重放原规划子集；新增、越界或快照缺失时均不得扩大。"""
    allowed = [
        UserStatementCandidate(message_id=10, content="旧前提"),
        UserStatementCandidate(message_id=11, content="当前问题"),
        UserStatementCandidate(message_id=12, content="后来消息"),
    ]
    original = BasisPlan(
        strategy="hybrid",
        needs_grove=True,
        candidate_statement_ids=[11],
    )
    snapshot = dump_basis_plan(original)
    restored = restore_basis_plan("hybrid", allowed, snapshot)
    assert restored.candidate_statement_ids == [11]

    # 原句柄已不在当前允许集合时只能收紧为空；缺少旧快照也不猜测全部消息。
    unavailable = restore_basis_plan("hybrid", allowed[:1], snapshot)
    assert unavailable.candidate_statement_ids == []
    legacy = restore_basis_plan("hybrid", allowed, None)
    assert legacy.candidate_statement_ids == []


def test_basis_plan_fallback_and_unknown_message_ids(monkeypatch) -> None:
    """规划失败回退 Grove-only；非法用户消息句柄被丢弃并记录异常。"""
    import asyncio

    from app.agents.basis import BasisRouteDraft
    from app.services.knowledge_agent.observability import StageMeta

    async def _fallback_planner(*args, **kwargs):
        return (
            BasisRouteDraft(strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=1,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.basis.run_basis_planner",
        _fallback_planner,
    )
    plan = asyncio.run(
        resolve_basis_plan(
            object(),
            workspace_id=1,
            request_basis_mode=BASIS_MODE_AUTO,
            objective="解释概念",
            scope_label="全部知识",
            topic_summary=None,
            context_decision="new_topic",
            current_message="解释概念",
            allowed_statements=[],
            feature_enabled=True,
        )
    )
    assert plan.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
    assert plan.degraded is True
    assert plan.meta is not None and plan.meta.is_fallback is True

    async def _dirty_planner(*args, **kwargs):
        return (
            BasisRouteDraft(
                strategy=BASIS_STRATEGY_MODEL_FIRST,
                user_message_ids=[11, 999],
            ),
            StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="llm",
                model="fake",
                is_fallback=False,
                error=None,
                duration_ms=2,
            ),
        )

    monkeypatch.setattr(
        "app.services.knowledge_agent.basis.run_basis_planner",
        _dirty_planner,
    )
    plan_dirty = asyncio.run(
        resolve_basis_plan(
            object(),
            workspace_id=1,
            request_basis_mode=BASIS_MODE_AUTO,
            objective="结合我的预算",
            scope_label="全部知识",
            topic_summary=None,
            context_decision="continue",
            current_message="结合我的预算说明",
            allowed_statements=[
                UserStatementCandidate(message_id=11, content="预算上限是 30 万")
            ],
            feature_enabled=True,
        )
    )
    assert plan_dirty.strategy == BASIS_STRATEGY_MODEL_FIRST
    assert plan_dirty.candidate_statement_ids == [11]
    assert plan_dirty.degraded is True
    assert plan_dirty.meta is not None
    assert "999" in (plan_dirty.meta.error or "")


def test_basis_feature_disabled_forces_grove_only(monkeypatch) -> None:
    """特性开关关闭时即使显式 auto 也固定 Grove-only。"""
    import asyncio

    async def _forbidden_planner(*args, **kwargs):  # pragma: no cover
        raise AssertionError("特性关闭不应调用规划器")

    monkeypatch.setattr(
        "app.services.knowledge_agent.basis.run_basis_planner",
        _forbidden_planner,
    )
    plan = asyncio.run(
        resolve_basis_plan(
            object(),
            workspace_id=1,
            request_basis_mode=BASIS_MODE_AUTO,
            objective="解释概念",
            scope_label="全部知识",
            topic_summary=None,
            context_decision="new_topic",
            current_message="解释概念",
            allowed_statements=[],
            feature_enabled=False,
        )
    )
    assert plan.strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY
    assert plan.meta is None


def test_validate_statement_ids_drops_unknown_handles() -> None:
    """句柄白名单：合法保留、未知丢弃、重复去重。"""
    valid, invalid = validate_statement_ids(
        [1, 2, 2, 999],
        {1, 2},
    )
    assert valid == [1, 2]
    assert invalid == [999]


def test_migration_upgrade_and_constraints(tmp_path: Path) -> None:
    """迁移链可完整升级，且唯一约束在迁移后的库上生效。"""
    db_path = tmp_path / "migration_test.db"
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
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"knowledge_conversations", "knowledge_messages", "knowledge_agent_runs"} <= tables
        assert {"knowledge_agent_tool_calls", "knowledge_agent_model_invocations"} <= tables
        assert "knowledge_agent_evidences" in tables
        assert "knowledge_context_versions" in tables
        assert "knowledge_working_set_items" in tables

        now = "2026-08-28 00:00:00"
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
            "INSERT INTO projects (id, workspace_id, name, template, status, created_at) "
            "VALUES (1, 1, '迁移项目', 'empty', 'active', ?)",
            (now,),
        )
        conn.execute(
            "INSERT INTO knowledge_conversations "
            "(id, workspace_id, owner_user_id, scope_type, project_id, title) "
            "VALUES (1, 1, 1, 'workspace', NULL, '迁移对话')"
        )

        def _insert_run(run_id: int, status: str, active_slot: str | None) -> None:
            conn.execute(
                "INSERT INTO knowledge_agent_runs "
                "(id, conversation_id, workspace_id, owner_user_id, scope_type, status, "
                " active_slot, retry_count, max_retries) "
                "VALUES (?, 1, 1, 1, 'workspace', ?, ?, 0, 1)",
                (run_id, status, active_slot),
            )

        _insert_run(1, "waiting", "active")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_run(2, "waiting", "active")
        conn.execute(
            "UPDATE knowledge_agent_runs SET status='completed', active_slot=NULL WHERE id=1"
        )
        _insert_run(2, "completed", None)
        _insert_run(3, "failed", None)

        # 上下文版本单活动约束
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(id, conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, active_slot) "
            "VALUES (1, 1, 1, 1, 1, 'workspace', '闭水试验', 'active', 'active')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_context_versions "
                "(id, conversation_id, workspace_id, owner_user_id, version_number, "
                " scope_type, topic_label, status, active_slot) "
                "VALUES (2, 1, 1, 1, 2, 'workspace', '新话题', 'active', 'active')"
            )
        conn.execute(
            "UPDATE knowledge_context_versions "
            "SET status='closed', active_slot=NULL WHERE id=1"
        )
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(id, conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, active_slot) "
            "VALUES (3, 1, 1, 1, 2, 'workspace', '新话题', 'active', 'active')"
        )

        # 工作集项唯一约束与空主题版本
        conn.execute(
            "INSERT INTO knowledge_working_set_items "
            "(id, context_version_id, entry_id, include_reason, sort_order) "
            "VALUES (1, 3, NULL, 'cited', 0)"
        )
        conn.execute(
            "INSERT INTO knowledge_working_set_items "
            "(id, context_version_id, entry_id, include_reason, sort_order) "
            "VALUES (2, 3, NULL, 'recent', 1)"
        )

        conn.execute(
            "INSERT INTO knowledge_messages "
            "(id, conversation_id, role, message_type, content, client_message_id, scope_type) "
            "VALUES (1, 1, 'user', 'user', '问题', 'client-1', 'workspace')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_messages "
                "(id, conversation_id, role, message_type, content, client_message_id, scope_type) "
                "VALUES (2, 1, 'user', 'user', '重试', 'client-1', 'workspace')"
            )

        # SQLite 自增回归：迁移创建的表（含知识 Agent 底座表）id 必须可自动生成
        conn.execute(
            "INSERT INTO knowledge_agent_runs "
            "(conversation_id, workspace_id, owner_user_id, scope_type, status, "
            " active_slot, retry_count, max_retries) "
            "VALUES (1, 1, 1, 'workspace', 'completed', NULL, 0, 1)"
        )
        auto_run_id = conn.execute(
            "SELECT id FROM knowledge_agent_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert auto_run_id is not None
        conn.execute(
            "INSERT INTO knowledge_context_versions "
            "(conversation_id, workspace_id, owner_user_id, version_number, "
            " scope_type, topic_label, status, close_reason, active_slot) "
            "VALUES (1, 1, 1, 5, 'workspace', '自增主题', 'closed', 'scope_change', NULL)"
        )
        auto_version_id = conn.execute(
            "SELECT id FROM knowledge_context_versions ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        assert auto_version_id is not None

        # 版本号唯一约束：同一对话重复 version_number 被拒绝
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO knowledge_context_versions "
                "(conversation_id, workspace_id, owner_user_id, version_number, "
                " scope_type, topic_label, status, close_reason, active_slot) "
                "VALUES (1, 1, 1, 1, 'workspace', '重复版本号', 'closed', 'scope_change', NULL)"
            )
        conn.commit()
    finally:
        conn.close()
