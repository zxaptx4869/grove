"""项目上下文进程内异步 Worker：领取到期的防抖刷新并生成。"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.models import ProjectContext
from app.services.project_context import refresh_project_context

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5


async def process_due_context() -> bool:
    """认领并刷新一个到期的项目上下文，返回是否有任务被处理。"""
    async with async_session_factory() as db:
        now = datetime.now(UTC)
        context = (
            await db.execute(
                select(ProjectContext)
                .where(
                    ProjectContext.refresh_due_at.is_not(None),
                    ProjectContext.refresh_due_at <= now,
                )
                .order_by(ProjectContext.updated_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if context is None:
            return False

        claimed = (
            await db.execute(
                update(ProjectContext)
                .where(
                    ProjectContext.id == context.id,
                    ProjectContext.refresh_due_at.is_not(None),
                )
                .values(refresh_due_at=None)
            )
        ).rowcount
        if claimed != 1:
            await db.rollback()
            return False

        project_id = context.project_id
        await db.commit()

    async with async_session_factory() as db:
        await refresh_project_context(db, project_id)
        await db.commit()
    return True


async def run_context_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    while not stop_event.is_set():
        try:
            handled = await process_due_context()
        except Exception:  # noqa: BLE001
            logger.exception("刷新项目上下文发生未预期错误")
            handled = False

        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
