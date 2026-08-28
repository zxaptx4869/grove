"""知识 Agent 连续追问决策服务测试：自动/显式/澄清/降级与历史限长。"""


import pytest
from pydantic_ai.models.test import TestModel

from app.agents.knowledge_context import (
    ContextDecisionDraft,
)
from app.db.session import async_session_factory
from app.models import KnowledgeConversation, KnowledgeMessage
from app.models.knowledge_agent import (
    CONTEXT_DECISION_CLARIFY,
    CONTEXT_DECISION_CONTINUE,
    CONTEXT_DECISION_NEW_TOPIC,
    CONTEXT_MODE_AUTO,
    CONTEXT_MODE_CONTINUE,
    CONTEXT_MODE_NEW_TOPIC,
    MESSAGE_ROLE_ASSISTANT,
    MESSAGE_ROLE_USER,
    SCOPE_WORKSPACE,
)
from app.services.knowledge_agent.follow_up import (
    DEFAULT_CLARIFY_QUESTION,
    NO_ACTIVE_TOPIC_CLARIFY,
    decide_context,
    select_decision_history,
)
from tests._knowledge_agent_fixtures import create_user, create_workspace


async def _conversation(db, user, workspace) -> KnowledgeConversation:
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="追问决策测试",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def _message(
    db,
    conversation: KnowledgeConversation,
    role: str,
    content: str,
) -> KnowledgeMessage:
    message = KnowledgeMessage(
        conversation_id=conversation.id,
        role=role,
        message_type=role,
        content=content,
        scope_type=SCOPE_WORKSPACE,
    )
    db.add(message)
    await db.flush()
    return message


def _fake_agent(draft: ContextDecisionDraft, *, fallback: bool = False):
    """构造决策 Agent 替身。"""

    async def _fake(
        db,
        workspace_id,
        *,
        current_message,
        active_topic_label,
        working_set_titles,
        history,
    ):
        return (
            draft,
            __import__(
                "app.services.knowledge_agent.observability",
                fromlist=["StageMeta"],
            ).StageMeta(
                purpose="context_decision",
                provider="offline" if fallback else "llm",
                model=None if fallback else "fake-context",
                is_fallback=fallback,
                error="模型不可用" if fallback else None,
                duration_ms=1,
            ),
        )

    return _fake


@pytest.mark.asyncio
async def test_auto_continue_rewrites_standalone_query(monkeypatch) -> None:
    """自动识别继续追问：补全独立查询并保留活动主题。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="continue",
                standalone_query="闭水试验为什么不能提前放水？",
                topic_label="",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "自动继续")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        first_user = await _message(db, conversation, MESSAGE_ROLE_USER, "闭水试验持续多久？")
        first_assistant = await _message(
            db, conversation, MESSAGE_ROLE_ASSISTANT, "通常 24 小时。"
        )
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "为什么不能提前放水？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
            user_message_id=current.id,
        )
        assert result.decision == CONTEXT_DECISION_CONTINUE
        assert result.standalone_query == "闭水试验为什么不能提前放水？"
        assert result.topic_label == "闭水试验"
        assert result.degraded is False
        assert result.history_message_ids == [first_user.id, first_assistant.id]


@pytest.mark.asyncio
async def test_auto_new_topic_ignores_old_working_set(monkeypatch) -> None:
    """自动识别新话题：不携带旧工作集主题。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="new_topic",
                standalone_query="庭院树木冬季养护要点",
                topic_label="庭院养护",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "自动新话题")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "庭院树木冬季怎么养护？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_NEW_TOPIC
        assert result.standalone_query == "庭院树木冬季养护要点"
        assert result.topic_label == "庭院养护"


@pytest.mark.asyncio
async def test_auto_clarify_uses_specific_question(monkeypatch) -> None:
    """自动判断需要澄清：返回具体澄清问题且不推进主题。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="clarify",
                standalone_query="",
                clarify_question="你指的是哪个方案的验收标准？",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "澄清")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "它的验收标准是什么？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CLARIFY
        assert result.clarify_question == "你指的是哪个方案的验收标准？"
        assert result.standalone_query == current.content


@pytest.mark.asyncio
async def test_explicit_new_topic_bypasses_classifier(monkeypatch) -> None:
    """显式 new_topic：不调用分类模型，直接以当前消息开始。"""
    called = False

    async def _should_not_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("new_topic 不应调用分类模型")

    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _should_not_call,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "显式新话题")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "讨论新的主题")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_NEW_TOPIC,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_NEW_TOPIC
        assert result.standalone_query == current.content
        assert result.topic_label == "讨论新的主题"
        assert called is False


@pytest.mark.asyncio
async def test_explicit_continue_keeps_semantics_even_if_classifier_disagrees(
    monkeypatch,
) -> None:
    """显式 continue：模型改判 new_topic/clarify 也不改变语义。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="new_topic",
                standalone_query="改判成新话题的查询",
                topic_label="被改判",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "显式继续")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "那另一个方案呢？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_CONTINUE,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CONTINUE
        assert result.standalone_query == "改判成新话题的查询"
        assert result.topic_label == "闭水试验"


@pytest.mark.asyncio
async def test_continue_without_active_working_set_clarifies(monkeypatch) -> None:
    """强制 continue 但没有活动工作集：不猜测历史主题，改为澄清。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="continue",
                standalone_query="补全的查询",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "无工作集继续")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "继续说说")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_CONTINUE,
            active_topic_label=None,
            working_set_titles=[],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CLARIFY
        assert result.clarify_question == NO_ACTIVE_TOPIC_CLARIFY
        assert result.topic_label is None


@pytest.mark.asyncio
async def test_auto_continue_without_active_working_set_clarifies(monkeypatch) -> None:
    """auto 判 continue 但无活动工作集：同样归一化为澄清。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(
            ContextDecisionDraft(
                action="continue",
                standalone_query="补全的查询",
            )
        ),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "自动无工作集")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "继续")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label=None,
            working_set_titles=[],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CLARIFY


@pytest.mark.asyncio
async def test_history_selection_limit_and_truncation() -> None:
    """有限历史：只取最近配置条数并截断内容，保存实际消息 ID。"""
    async with async_session_factory() as db:
        user = await create_user(db, "历史限长")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        for index in range(5):
            await _message(db, conversation, MESSAGE_ROLE_USER, f"问题 {index}")
            await _message(db, conversation, MESSAGE_ROLE_ASSISTANT, f"回答 {index}")
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "最新问题")
        long_message = "长" * 1200
        await _message(db, conversation, MESSAGE_ROLE_USER, long_message)
        await _message(db, conversation, MESSAGE_ROLE_ASSISTANT, "长回答")
        await db.commit()

        history, ids = await select_decision_history(
            db,
            conversation.id,
            exclude_message_id=current.id,
            limit=3,
            message_chars=100,
        )
        assert len(history) == 3
        assert len(ids) == 3
        # 最新 3 条（排除 current 后是长回答、长问题、回答 4）
        assert history[-1]["role"] == MESSAGE_ROLE_ASSISTANT
        assert history[-1]["content"] == "长回答"
        assert history[1]["role"] == MESSAGE_ROLE_USER
        assert len(history[1]["content"]) == 100
        assert current.id not in ids


@pytest.mark.asyncio
async def test_auto_model_failure_falls_back_to_new_topic(monkeypatch) -> None:
    """auto 分类模型不可用：显式降级为 new_topic 并标记 degraded。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(ContextDecisionDraft(action="continue"), fallback=True),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "分类降级")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "为什么？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_NEW_TOPIC
        assert result.degraded is True
        assert result.meta.is_fallback is True
        assert result.topic_label == "为什么？"


@pytest.mark.asyncio
async def test_forced_continue_model_failure_uses_topic_plus_message(
    monkeypatch,
) -> None:
    """强制 continue 改写失败：用主题 + 原问题形成确定性查询并标记降级。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(ContextDecisionDraft(action="continue"), fallback=True),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "继续降级")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "为什么不能提前放水？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_CONTINUE,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CONTINUE
        assert result.standalone_query == "闭水试验：为什么不能提前放水？"
        assert result.degraded is True


@pytest.mark.asyncio
async def test_offline_model_auto_falls_back_to_new_topic(monkeypatch) -> None:
    """未配置模型密钥：决策阶段记录降级并安全回退 new_topic。"""
    from app.agents.knowledge_context import run_context_decision_agent

    async def _fake_offline_model(db, workspace_id):
        return TestModel()

    monkeypatch.setattr(
        "app.agents.knowledge_context.get_text_model",
        _fake_offline_model,
    )
    async with async_session_factory() as db:
        user = await create_user(db, "离线分类")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "新问题")
        await db.commit()

        draft, meta = await run_context_decision_agent(
            db,
            workspace.id,
            current_message=current.content,
            active_topic_label="闭水试验",
            working_set_titles=["闭水试验"],
            history=[],
        )
        assert meta.is_fallback is True
        assert draft.action == CONTEXT_DECISION_NEW_TOPIC


@pytest.mark.asyncio
async def test_clarify_without_question_uses_deterministic_text(monkeypatch) -> None:
    """澄清没有具体问题时使用确定性澄清文案。"""
    monkeypatch.setattr(
        "app.services.knowledge_agent.follow_up.run_context_decision_agent",
        _fake_agent(ContextDecisionDraft(action="clarify", clarify_question="  ")),
    )
    async with async_session_factory() as db:
        user = await create_user(db, "空澄清")
        workspace = await create_workspace(db, user)
        conversation = await _conversation(db, user, workspace)
        current = await _message(db, conversation, MESSAGE_ROLE_USER, "那个呢？")
        await db.commit()

        result = await decide_context(
            db,
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            current_message=current.content,
            request_mode=CONTEXT_MODE_AUTO,
            active_topic_label="闭水试验",
            working_set_titles=[],
            history_limit=8,
            history_message_chars=500,
        )
        assert result.decision == CONTEXT_DECISION_CLARIFY
        assert result.clarify_question == DEFAULT_CLARIFY_QUESTION
