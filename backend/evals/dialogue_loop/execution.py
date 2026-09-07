"""隔离子进程中的身份校验、新旧路径执行与真实审计收集。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from sqlalchemy import select

from evals.dialogue_loop.core import PER_TURN_SECONDS, SCENARIOS, BudgetLedger
from evals.dialogue_loop.instrumentation import Instrumentation, install_instrumentation
from evals.dialogue_loop.isolation import assert_isolated, domain_fingerprint, provider_snapshot


async def authenticate_demo(password: str) -> dict:
    """在副本中复用应用密码校验并从成员关系取得唯一可信身份。"""
    from app.core.security import verify_password
    from app.db.session import async_session_factory
    from app.models import User, WorkspaceMember

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.username == "demo"))).scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            raise ValueError("demo 账号或密码错误")
        memberships = (
            (await db.execute(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)))
            .scalars()
            .all()
        )
        if len(memberships) != 1:
            raise ValueError("demo 账号必须恰好属于一个可验证 Workspace")
        member = memberships[0]
        return {"user_id": user.id, "workspace_id": member.workspace_id, "role": member.role}


async def secret_preflight(workspace_id: int) -> dict:
    """只检查密钥存在性，不发请求、不读取或输出密钥值。"""
    from app.db.session import async_session_factory
    from app.services.ai_models import get_settings_row, get_text_secret
    from app.services.embedding import EMBEDDING_PROVIDER
    from app.services.secret_store import get_secret_store, secret_key

    async with async_session_factory() as db:
        row = await get_settings_row(db, workspace_id)
        text_ready = bool(await get_text_secret(db, workspace_id))
        embedding_ready = bool(get_secret_store().get(secret_key(workspace_id, EMBEDDING_PROVIDER)))
        summary = {
            "text_secret_available": text_ready,
            "embedding_secret_available": embedding_ready,
            "text_provider": row.text_provider,
            "text_model": row.text_model,
            "embedding_provider": row.embedding_provider,
            "embedding_model": row.embedding_model,
        }
        await db.rollback()
    return summary


async def child_preflight(db_path: Path, original_path: Path, password: str) -> dict:
    assert_isolated(db_path, original_path)
    identity = await authenticate_demo(password)
    providers = provider_snapshot(db_path, identity["workspace_id"])
    secrets = await secret_preflight(identity["workspace_id"])
    registry = _registry_preflight()
    state = Instrumentation(BudgetLedger())
    coverage = install_instrumentation(state)
    blockers = []
    if not secrets["text_secret_available"]:
        blockers.append("文本模型密钥不可用")
    if not secrets["embedding_secret_available"]:
        blockers.append("向量模型密钥不可用")
    if not providers.get("text_available"):
        blockers.append("文本模型配置标记为不可用")
    if not registry["ok"]:
        blockers.append("只读工具白名单不完整")
    required_text_modules = {
        "app.agents.knowledge_agent",
        "app.agents.knowledge_context",
        "app.agents.semantic",
    }
    if not required_text_modules.issubset(set(coverage["text_modules"])):
        blockers.append("旧流程文本模型调用无法完整纳入实验计数")
    if "app.services.vector_search" not in coverage["embedding_modules"]:
        blockers.append("向量调用无法纳入实验计数")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "identity": identity,
        "provider": secrets,
        "registry": registry,
        "instrumentation": coverage,
        "model_calls": 0,
    }


def _registry_preflight() -> dict:
    from app.services.knowledge_agent.read_tool_adapters import (
        KNOWLEDGE_AGENT_READ_TOOL_REGISTRY,
    )

    required = {
        "query_entries",
        "aggregate_entries",
        "search_knowledge",
        "read_entries",
        "read_evidence",
    }
    available = set(KNOWLEDGE_AGENT_READ_TOOL_REGISTRY)
    versions = {
        name: spec.version
        for name, spec in KNOWLEDGE_AGENT_READ_TOOL_REGISTRY.items()
        if name in required
    }
    return {"ok": required <= available and set(versions.values()) == {"v1"}, "versions": versions}


async def _create_conversation(workspace_id: int, user_id: int):
    from app.db.session import async_session_factory
    from app.schemas.knowledge_agent import KnowledgeConversationCreate
    from app.services.knowledge_agent.conversations import create_conversation

    async with async_session_factory() as db:
        conversation = await create_conversation(
            db, workspace_id, user_id, KnowledgeConversationCreate(scope_type="workspace")
        )
        await db.commit()
        await db.refresh(conversation)
        return conversation.id


async def _submit_turn(conversation_id: int, message: str, turn_number: int):
    from app.db.session import async_session_factory
    from app.models import KnowledgeConversation
    from app.models.knowledge_agent import RUN_PROCESSING
    from app.schemas.knowledge_agent import KnowledgeRunSubmitRequest
    from app.services.knowledge_agent.runs import submit_message

    async with async_session_factory() as db:
        conversation = await db.get(KnowledgeConversation, conversation_id)
        _, run = await submit_message(
            db,
            conversation,
            KnowledgeRunSubmitRequest(
                client_message_id=f"dialogue-loop-{conversation_id}-{turn_number}",
                message=message,
                basis_mode="auto",
            ),
        )
        run.status = RUN_PROCESSING
        run.current_step = "dialogue_loop"
        run.claimed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(run)
        return run.id


async def _finish_new_run(run_id: int, answer: str, failed: str | None) -> None:
    from app.db.session import async_session_factory
    from app.models import KnowledgeAgentRun
    from app.models.knowledge_agent import RUN_COMPLETED
    from app.schemas.knowledge_agent import KnowledgeAnswerOut
    from app.services.knowledge_agent.runs import finalize_run, mark_run_failed

    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        if failed:
            await mark_run_failed(db, run, failed)
        else:
            await finalize_run(
                db,
                run,
                answer=KnowledgeAnswerOut(answer=answer, status="completed"),
                status=RUN_COMPLETED,
                fallback_summary={"has_fallback": False, "stages": []},
            )
        await db.commit()


async def run_new_scenario(
    scenario_id: str,
    identity: dict,
    ledger: BudgetLedger,
    instrumentation: Instrumentation,
    checkpoint: Callable[[dict], None] | None = None,
) -> dict:
    from app.db.session import async_session_factory
    from app.services.ai_models import get_text_model
    from evals.dialogue_loop.loop import LoopState, build_agent, run_turn

    scenario = next(item for item in SCENARIOS if item.id == scenario_id)
    conversation_id = await _create_conversation(identity["workspace_id"], identity["user_id"])
    async with async_session_factory() as db:
        model = await get_text_model(db, identity["workspace_id"])
    state = LoopState(
        workspace_id=identity["workspace_id"],
        user_id=identity["user_id"],
        conversation_id=conversation_id,
        ledger=ledger,
        instrumentation=instrumentation,
    )
    agent = build_agent(model)
    history = []
    turns = []
    list_ready = True
    for turn_number, message in enumerate(scenario.turns, 1):
        dependency = scenario_id == "C" and turn_number in {2, 4}
        if dependency and not list_ready:
            turns.append(
                {
                    "message": message,
                    "status": "blocked",
                    "answer": "",
                    "blocks": [],
                    "error": "依赖的首轮列表未产生",
                    "duration_ms": 0,
                    "usage": None,
                    "tool_calls": [],
                    "model_calls": [],
                }
            )
            if checkpoint:
                checkpoint(
                    {
                        "arm": "new",
                        "scenario": scenario_id,
                        "title": scenario.title,
                        "turns": turns,
                    }
                )
            continue
        run_id = await _submit_turn(conversation_id, message, turn_number)
        state.begin_turn(run_id, message)
        turn, history = await run_turn(agent, state, message, history)
        await _finish_new_run(run_id, turn["answer"], turn["error"])
        turns.append(turn)
        if checkpoint:
            checkpoint(
                {
                    "arm": "new",
                    "scenario": scenario_id,
                    "title": scenario.title,
                    "turns": turns,
                }
            )
        if scenario_id == "C" and turn_number == 1:
            list_ready = any(block.get("kind") == "list" for block in turn["blocks"])
    return {"arm": "new", "scenario": scenario_id, "title": scenario.title, "turns": turns}


async def _old_turn(
    conversation_id: int, message: str, turn_number: int, instrumentation: Instrumentation
) -> dict:
    from app.db.session import async_session_factory
    from app.models import KnowledgeAgentModelInvocation, KnowledgeAgentRun, KnowledgeAgentToolCall
    from app.services.knowledge_agent.runner import execute_run
    from app.services.knowledge_agent.runs import mark_run_failed, run_out

    run_id = await _submit_turn(conversation_id, message, turn_number)
    before = len(instrumentation.logs)
    started = perf_counter()
    error = None
    try:
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            async with asyncio.timeout(PER_TURN_SECONDS):
                await execute_run(db, run)
            await db.commit()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            await mark_run_failed(db, run, error)
            await db.commit()
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        public = run_out(run).model_dump(mode="json")
        tools = (
            (
                await db.execute(
                    select(KnowledgeAgentToolCall)
                    .where(KnowledgeAgentToolCall.run_id == run_id)
                    .order_by(KnowledgeAgentToolCall.sequence, KnowledgeAgentToolCall.id)
                )
            )
            .scalars()
            .all()
        )
        invocations = (
            (
                await db.execute(
                    select(KnowledgeAgentModelInvocation)
                    .where(KnowledgeAgentModelInvocation.run_id == run_id)
                    .order_by(KnowledgeAgentModelInvocation.id)
                )
            )
            .scalars()
            .all()
        )
    answer = (public.get("answer") or {}).get("answer") or ""
    tool_rows = [
        {
            "tool": item.tool_name,
            "status": item.status,
            "params_summary": item.params_summary,
            "result_summary": item.result_summary,
            "error": item.error,
            "duration_ms": item.duration_ms,
        }
        for item in tools
    ]
    model_rows = [
        {
            "purpose": item.purpose,
            "provider": item.provider,
            "model": item.model,
            "is_fallback": item.is_fallback,
            "error": item.error,
            "duration_ms": item.duration_ms,
            "usage": json.loads(item.usage_json) if item.usage_json else None,
        }
        for item in invocations
    ]
    model_rows.extend(asdict(item) for item in instrumentation.logs[before:])
    return {
        "message": message,
        "status": public["status"] if error is None else "failed",
        "answer": answer,
        "public_run": public,
        "error": error or public.get("error"),
        "duration_ms": int((perf_counter() - started) * 1000),
        "usage": None,
        "budget": instrumentation.ledger.snapshot(),
        "tool_calls": tool_rows,
        "model_calls": model_rows,
    }


async def run_old_scenario(
    scenario_id: str,
    identity: dict,
    ledger: BudgetLedger,
    instrumentation: Instrumentation,
    checkpoint: Callable[[dict], None] | None = None,
) -> dict:
    scenario = next(item for item in SCENARIOS if item.id == scenario_id)
    conversation_id = await _create_conversation(identity["workspace_id"], identity["user_id"])
    turns = []
    list_ready = True
    for turn_number, message in enumerate(scenario.turns, 1):
        dependency = scenario_id == "C" and turn_number in {2, 4}
        if dependency and not list_ready:
            turns.append(
                {
                    "message": message,
                    "status": "blocked",
                    "answer": "",
                    "error": "依赖的首轮列表未产生",
                    "duration_ms": 0,
                    "usage": None,
                    "tool_calls": [],
                    "model_calls": [],
                }
            )
            if checkpoint:
                checkpoint(
                    {
                        "arm": "old",
                        "scenario": scenario_id,
                        "title": scenario.title,
                        "turns": turns,
                    }
                )
            continue
        ledger.start_turn()
        turn = await _old_turn(conversation_id, message, turn_number, instrumentation)
        turns.append(turn)
        if checkpoint:
            checkpoint(
                {
                    "arm": "old",
                    "scenario": scenario_id,
                    "title": scenario.title,
                    "turns": turns,
                }
            )
        if scenario_id == "C" and turn_number == 1:
            snapshot = (turn.get("public_run") or {}).get("entry_result") or {}
            list_ready = bool(snapshot.get("items"))
    return {"arm": "old", "scenario": scenario_id, "title": scenario.title, "turns": turns}


async def child_run(
    db_path: Path,
    original_path: Path,
    password: str,
    arm: str,
    scenario_id: str,
    text_used: int,
    embedding_used: int,
    checkpoint_path: Path | None = None,
) -> dict:
    assert_isolated(db_path, original_path)
    identity = await authenticate_demo(password)
    before = domain_fingerprint(
        db_path, identity["workspace_id"], attachment_root=original_path.parent
    )
    ledger = BudgetLedger(text_used, embedding_used)
    instrumentation = Instrumentation(ledger)
    coverage = install_instrumentation(instrumentation)

    def checkpoint(partial: dict) -> None:
        if checkpoint_path is None:
            return
        partial.update(
            {
                "partial": True,
                "batch_text_requests": ledger.batch_text_requests,
                "batch_embedding_requests": ledger.batch_embedding_requests,
            }
        )
        checkpoint_path.write_text(
            json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        checkpoint_path.chmod(0o600)

    if arm == "new":
        result = await run_new_scenario(scenario_id, identity, ledger, instrumentation, checkpoint)
    else:
        result = await run_old_scenario(scenario_id, identity, ledger, instrumentation, checkpoint)
    after = domain_fingerprint(
        db_path, identity["workspace_id"], attachment_root=original_path.parent
    )
    result.update(
        {
            "identity": identity,
            "instrumentation": coverage,
            "business_data_unchanged": before == after,
            "business_fingerprint_before": before,
            "business_fingerprint_after": after,
            "batch_text_requests": ledger.batch_text_requests,
            "batch_embedding_requests": ledger.batch_embedding_requests,
        }
    )
    return result
