"""Entry 向量重建进程内异步 Worker。"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import Entry, EntryEmbedding
from app.models.entry_embedding import (
    EMBEDDING_FAILED,
    EMBEDDING_PENDING,
    EMBEDDING_READY,
)
from app.services.embedding import encode_text
from app.services.vector_store import entry_text, serialize_vector

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5
BATCH_LIMIT = 10
STALE_RETRY_SECONDS = 60


async def _promote_stale_failed(db) -> int:
    """把超过重试间隔的失败记录重新置为待重建，返回数量。"""
    rows = (
        await db.execute(select(EntryEmbedding).where(EntryEmbedding.status == EMBEDDING_FAILED))
    ).scalars().all()
    threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        seconds=STALE_RETRY_SECONDS
    )
    promoted = 0
    for row in rows:
        if row.updated_at is None or row.updated_at < threshold:
            row.status = EMBEDDING_PENDING
            row.error = None
            promoted += 1
    return promoted


async def process_pending_embeddings() -> int:
    """处理一批待重建向量，返回处理条数（含失败重试提升）。"""
    async with async_session_factory() as db:
        await _promote_stale_failed(db)
        rows = (
            await db.execute(
                select(EntryEmbedding)
                .where(EntryEmbedding.status == EMBEDDING_PENDING)
                .order_by(EntryEmbedding.created_at)
                .limit(BATCH_LIMIT)
            )
        ).scalars().all()
        if not rows:
            await db.commit()
            return 0
        for row in rows:
            entry = await db.get(Entry, row.entry_id)
            if entry is None:
                await db.delete(row)
                continue
            result = await encode_text(db, row.workspace_id, entry_text(entry))
            if result.vector is not None:
                row.embedding = serialize_vector(result.vector)
                row.dimension = len(result.vector)
                row.model = result.model
                row.status = EMBEDDING_READY
                row.error = None
            else:
                row.status = EMBEDDING_FAILED
                row.error = result.error
        await db.commit()
    return len(rows)


async def run_embedding_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    while not stop_event.is_set():
        try:
            handled = await process_pending_embeddings()
        except Exception:  # noqa: BLE001
            logger.exception("处理待重建向量发生未预期错误")
            handled = False

        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
