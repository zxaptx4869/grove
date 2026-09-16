"""当前知识 Agent 测试共用的确定性数据与终态辅助。"""

from app.models import KnowledgeAgentRun, KnowledgeConversation
from app.models.knowledge_agent import RUN_COMPLETED, RUN_PARTIAL, RUN_PROCESSING, SCOPE_WORKSPACE
from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
from app.services.knowledge_agent.answer_draft import (
    KnowledgeAnswerDraft,
    KnowledgeAnswerPointDraft,
    KnowledgeCitationDraft,
    KnowledgeConflictDraft,
)
from app.services.knowledge_agent.evidence import build_validated_answer
from app.services.knowledge_agent.runs import finalize_run, submit_message
from app.services.knowledge_agent.tools import (
    RunToolContext,
    read_entries,
    read_source_evidence,
    search_confirmed_knowledge,
)

__all__ = [
    "KnowledgeAnswerDraft",
    "KnowledgeAnswerPointDraft",
    "KnowledgeCitationDraft",
    "KnowledgeConflictDraft",
    "complete_answer_run",
    "conversation_and_run",
    "evidence_for_run",
    "run_id_counter",
]

_counter = 0


def run_id_counter() -> str:
    global _counter
    _counter += 1
    return str(_counter)


async def conversation_and_run(db, user, workspace, message: str = "闭水试验通常持续多久？"):
    conversation = KnowledgeConversation(
        workspace_id=workspace.id,
        owner_user_id=user.id,
        scope_type=SCOPE_WORKSPACE,
        title="执行测试",
    )
    db.add(conversation)
    await db.flush()
    _message, run = await submit_message(
        db,
        conversation,
        KnowledgeRunSubmitRequest(
            client_message_id=f"run-{run_id_counter()}",
            message=message,
        ),
    )
    return conversation, run


async def evidence_for_run(db, ctx: RunToolContext, query: str = "闭水试验") -> list:
    search = await search_confirmed_knowledge(
        db,
        ctx,
        query,
        recall_limit=10,
        context_limit=5,
    )
    entries = await read_entries(
        db,
        ctx,
        [item.entry_id for item in search.items],
    )
    verified: list = []
    for item in entries.items:
        result = await read_source_evidence(
            db,
            ctx,
            item.entry_id,
            [source["source_id"] for source in item.sources],
        )
        verified.extend(row for row in result.items if row.citable)
    return verified


async def complete_answer_run(db, run: KnowledgeAgentRun, draft: KnowledgeAnswerDraft) -> None:
    """用真实 Evidence 校验和现行终态服务完成测试 Run，不调用旧执行器。"""
    run.status = RUN_PROCESSING
    run.active_slot = "active"
    answer, _stats = await build_validated_answer(db, run.id, draft)
    status = RUN_COMPLETED if answer.status == "completed" else RUN_PARTIAL
    await finalize_run(
        db,
        run,
        answer=answer,
        status=status,
        fallback_summary={"has_fallback": False, "items": []},
    )
