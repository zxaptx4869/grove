"""进程内处理 Worker。"""

import asyncio
import logging

from sqlalchemy import select, update

from app.db.session import async_session_factory
from app.models import ProcessingTask, Source
from app.models.processing import DONE, FAILED, PROCESSING, WAITING
from app.processing.factory import get_processing_provider

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5


async def process_one_task() -> bool:
    """认领并处理一个等待任务，返回是否有任务被处理。"""
    async with async_session_factory() as db:
        task = (
            await db.execute(
                select(ProcessingTask)
                .where(ProcessingTask.status == WAITING)
                .order_by(ProcessingTask.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if task is None:
            return False

        claimed = (
            await db.execute(
                update(ProcessingTask)
                .where(ProcessingTask.id == task.id, ProcessingTask.status == WAITING)
                .values(status=PROCESSING, step="process", error=None)
            )
        ).rowcount
        if claimed != 1:
            await db.rollback()
            return False

        source = await db.get(Source, task.source_id)
        if source is None:
            await db.rollback()
            return False
        source.status = PROCESSING
        await db.commit()

    await _finish_task(task.id, task.source_id)
    return True


async def _finish_task(task_id: int, source_id: int) -> None:
    """执行 Provider 并把最终状态写回任务与 Source。"""
    async with async_session_factory() as db:
        source = await db.get(Source, source_id)
        if source is None:
            task = await db.get(ProcessingTask, task_id)
            if task is not None:
                task.status = FAILED
                task.error = "来源不存在"
            await db.commit()
            return

        try:
            await get_processing_provider().process(db, source)
            new_status = DONE
            error = None
        except Exception as exc:  # noqa: BLE001
            logger.exception("处理 Source 失败")
            new_status = FAILED
            error = str(exc)

        task = await db.get(ProcessingTask, task_id)
        if task is not None:
            task.status = new_status
            task.error = error
        refreshed_source = await db.get(Source, source_id)
        if refreshed_source is not None:
            refreshed_source.status = new_status
        await db.commit()


async def run_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    while not stop_event.is_set():
        try:
            handled = await process_one_task()
        except Exception:  # noqa: BLE001
            logger.exception("处理任务发生未预期错误")
            handled = False

        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
