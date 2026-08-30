"""知识 Agent 进程内异步 Worker：原子领取、租约恢复、重试上限与取消。"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update

from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.models import KnowledgeAgentRun, KnowledgeInvestigation
from app.models.knowledge_agent import (
    INVESTIGATION_STATUS_ACTIVE,
    INVESTIGATION_STATUS_CANCELLED,
    RUN_KIND_DRAFT_CANDIDATE,
    RUN_KIND_ENTRY_REVISION,
    RUN_PROCESSING,
    RUN_WAITING,
    STOP_REASON_CANCELLED,
)
from app.services.knowledge_agent.candidate import execute_draft_candidate_run
from app.services.knowledge_agent.entry_revision import execute_entry_revision_run
from app.services.knowledge_agent.runner import RunCancelled, execute_run
from app.services.knowledge_agent.runs import (
    finalize_cancelled,
    mark_run_failed,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5


async def claim_next_run() -> int | None:
    """原子领取一个 waiting Run；两个 Worker 竞争时只有一个成功。"""
    async with async_session_factory() as db:
        run = (
            await db.execute(
                select(KnowledgeAgentRun)
                .where(KnowledgeAgentRun.status == RUN_WAITING)
                .order_by(KnowledgeAgentRun.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            return None
        claimed = (
            await db.execute(
                update(KnowledgeAgentRun)
                .where(
                    KnowledgeAgentRun.id == run.id,
                    KnowledgeAgentRun.status == RUN_WAITING,
                )
                .values(
                    status=RUN_PROCESSING,
                    claimed_at=datetime.now(UTC),
                    current_step="claim",
                    error=None,
                )
            )
        ).rowcount
        if claimed != 1:
            await db.rollback()
            return None
        run_id = run.id
        await db.commit()
        return run_id


async def _requeue_or_fail(run_id: int, error: str) -> None:
    """执行失败后的恢复：重试上限内重新入队一次，超过则失败终态。"""
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        if run is None or run.status != RUN_PROCESSING:
            return
        if run.retry_count < run.max_retries:
            run.retry_count += 1
            run.status = RUN_WAITING
            run.claimed_at = None
            run.current_step = "recovered"
            logger.warning(
                "知识 Agent Run %d 执行失败，重新入队（第 %d 次）：%s",
                run_id,
                run.retry_count,
                error,
            )
        else:
            await mark_run_failed(db, run, f"执行失败且超过恢复上限：{error}")
            logger.error("知识 Agent Run %d 超过恢复上限：%s", run_id, error)
        await db.commit()


async def process_one_run() -> bool:
    """领取并执行一个 Run，返回是否有任务被处理。"""
    run_id = await claim_next_run()
    if run_id is None:
        return False
    try:
        async with async_session_factory() as db:
            run = await db.get(KnowledgeAgentRun, run_id)
            if run is None:
                return True
            if run.cancel_requested:
                await finalize_cancelled(db, run)
            elif run.run_kind == RUN_KIND_DRAFT_CANDIDATE:
                await execute_draft_candidate_run(db, run)
            elif run.run_kind == RUN_KIND_ENTRY_REVISION:
                await execute_entry_revision_run(db, run)
            else:
                await execute_run(db, run)
            await db.commit()
    except RunCancelled:
        await _finalize_cancelled_after_interrupt(run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("知识 Agent Run %d 执行发生未预期错误", run_id)
        await _requeue_or_fail(run_id, str(exc))
    return True


async def _finalize_cancelled_after_interrupt(run_id: int) -> None:
    """取消请求在步骤边界命中：丢弃模型结果，把 Run 标为取消。"""
    async with async_session_factory() as db:
        run = await db.get(KnowledgeAgentRun, run_id)
        if run is not None and run.status == RUN_PROCESSING:
            await finalize_cancelled(db, run, "运行中被取消")
            # 已提交轮次保留审计；活动调查进入取消终态
            investigation = (
                await db.execute(
                    select(KnowledgeInvestigation).where(
                        KnowledgeInvestigation.run_id == run_id
                    )
                )
            ).scalar_one_or_none()
            if (
                investigation is not None
                and investigation.status == INVESTIGATION_STATUS_ACTIVE
            ):
                investigation.status = INVESTIGATION_STATUS_CANCELLED
                investigation.stop_reason = STOP_REASON_CANCELLED
            await db.commit()


def _stale_claimed_expr(lease_seconds: int):
    """数据库侧过期租约判定表达式，兼容 SQLite 与 MySQL 8。"""
    if engine.dialect.name == "sqlite":
        return KnowledgeAgentRun.claimed_at <= func.datetime(
            "now", f"-{lease_seconds} seconds"
        )
    return KnowledgeAgentRun.claimed_at <= func.date_sub(
        func.now(), text(f"INTERVAL {lease_seconds} SECOND")
    )


async def recover_stale_runs() -> int:
    """恢复超过租约的 processing Run：重试上限内重新入队，超过则失败。"""
    settings = get_settings()
    recovered = 0
    async with async_session_factory() as db:
        stale_expr = _stale_claimed_expr(settings.knowledge_agent_lease_seconds)
        rows = (
            await db.execute(
                select(KnowledgeAgentRun).where(
                    KnowledgeAgentRun.status == RUN_PROCESSING,
                    stale_expr,
                )
            )
        ).scalars().all()
        for run in rows:
            if run.retry_count < run.max_retries:
                run.retry_count += 1
                run.status = RUN_WAITING
                run.claimed_at = None
                run.current_step = "recovered"
                recovered += 1
            else:
                await mark_run_failed(db, run, "处理租约超时且超过恢复上限")
        if rows:
            await db.commit()
    return recovered


async def run_knowledge_agent_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    while not stop_event.is_set():
        try:
            handled = await process_one_run()
            await recover_stale_runs()
        except Exception:  # noqa: BLE001
            logger.exception("知识 Agent Worker 发生未预期错误")
            handled = False
        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
