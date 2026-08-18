"""目录起草进程内异步 Worker。"""

import asyncio
import logging

from app.services.directory_draft import process_next_draft_step

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5


async def run_directory_draft_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    while not stop_event.is_set():
        try:
            handled = await process_next_draft_step()
        except Exception:  # noqa: BLE001
            logger.exception("处理目录草稿步骤发生未预期错误")
            handled = False

        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
