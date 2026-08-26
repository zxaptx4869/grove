"""Entry 向量重建进程内异步 Worker。"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update

from app.db.session import async_session_factory
from app.models import AIProviderSettings, Entry, EntryEmbedding, Project
from app.models.ai_settings import DEFAULT_EMBEDDING_MODEL
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


async def backfill_missing_embedding_rows(db) -> int:
    """启动时补齐缺少向量记录的 Entry，并把旧模型向量标记为待重建。"""
    settings_rows = (await db.execute(select(AIProviderSettings))).scalars().all()
    model_by_workspace = {row.workspace_id: row.embedding_model for row in settings_rows}

    missing = (
        await db.execute(
            select(Entry, Project.workspace_id)
            .join(Project, Entry.project_id == Project.id)
            .where(
                ~exists(
                    select(EntryEmbedding.id).where(
                        EntryEmbedding.entry_id == Entry.id
                    )
                )
            )
        )
    ).all()
    created = 0
    for entry, workspace_id in missing:
        db.add(
            EntryEmbedding(
                workspace_id=workspace_id,
                project_id=entry.project_id,
                entry_id=entry.id,
                model=model_by_workspace.get(workspace_id, DEFAULT_EMBEDDING_MODEL),
                dimension=0,
                status=EMBEDDING_PENDING,
            )
        )
        created += 1

    for workspace_id, model in model_by_workspace.items():
        await db.execute(
            update(EntryEmbedding)
            .where(
                EntryEmbedding.workspace_id == workspace_id,
                EntryEmbedding.model != model,
            )
            .values(status=EMBEDDING_PENDING, error=None)
        )
    await db.commit()
    return created


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
    try:
        async with async_session_factory() as db:
            created = await backfill_missing_embedding_rows(db)
            if created:
                logger.info("向量回填：为 %d 条历史 Entry 创建待重建记录", created)
    except Exception:  # noqa: BLE001
        logger.exception("向量回填失败，继续进入轮询")
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
