"""Entry 向量重建进程内异步 Worker。"""

import asyncio
import logging

import httpx
from sqlalchemy import exists, func, select, text, update

from app.db.session import async_session_factory
from app.models import AIProviderSettings, Entry, EntryEmbedding, Project
from app.models.ai_settings import DEFAULT_EMBEDDING_MODEL
from app.models.entry_embedding import (
    EMBEDDING_FAILED,
    EMBEDDING_PENDING,
    EMBEDDING_READY,
)
from app.services.ai_models import get_settings_row
from app.services.embedding import EmbeddingResult, encode_text
from app.services.vector_store import entry_text, serialize_vector

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.5
BATCH_LIMIT = 10
STALE_RETRY_SECONDS = 60
MAX_AUTO_RETRIES = 3
# 连续失败达到该条数即触发熔断，停止处理剩余待重建向量
CIRCUIT_FAIL_THRESHOLD = 5
PAUSE_ERROR = "模型不可用，已停止自动重建（请检查模型配置后手动重试）"


def _stale_failed_expr(dialect: str):
    """数据库侧的过期失败判定表达式，避免 Python 时区与数据库服务器时区不一致。"""
    if dialect == "sqlite":
        return EntryEmbedding.updated_at < func.datetime("now", f"-{STALE_RETRY_SECONDS} seconds")
    return EntryEmbedding.updated_at < func.date_sub(
        func.now(), text(f"INTERVAL {STALE_RETRY_SECONDS} SECOND")
    )


async def _promote_stale_failed(db) -> int:
    """把超过重试间隔且未触顶的失败记录重新置为待重建，返回数量。"""
    stale_expr = _stale_failed_expr(db.bind.dialect.name)
    rows = (
        await db.execute(
            select(EntryEmbedding).where(
                EntryEmbedding.status == EMBEDDING_FAILED,
                EntryEmbedding.retry_count < MAX_AUTO_RETRIES,
                stale_expr,
            )
        )
    ).scalars().all()
    promoted = 0
    for row in rows:
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

    # 按「不同的模型」合并工作区，减少启动时的 UPDATE 次数
    workspace_ids_by_model: dict[str, list[int]] = {}
    for workspace_id, model in model_by_workspace.items():
        workspace_ids_by_model.setdefault(model, []).append(workspace_id)
    for model, workspace_ids in workspace_ids_by_model.items():
        await db.execute(
            update(EntryEmbedding)
            .where(
                EntryEmbedding.workspace_id.in_(workspace_ids),
                EntryEmbedding.model != model,
            )
            .values(status=EMBEDDING_PENDING, error=None)
        )
    await db.commit()
    return created


async def pause_remaining_pending(db, model: str) -> int:
    """熔断：把指定模型的剩余待处理向量标记为失败并触顶重试计数，防止继续逐条撞墙。"""
    result = await db.execute(
        update(EntryEmbedding)
        .where(
            EntryEmbedding.status == EMBEDDING_PENDING,
            EntryEmbedding.model == model,
        )
        .values(
            status=EMBEDDING_FAILED,
            error=PAUSE_ERROR,
            retry_count=MAX_AUTO_RETRIES,
        )
    )
    return result.rowcount or 0


async def process_pending_embeddings() -> tuple[int, int, str | None]:
    """处理一批待重建向量，返回 (处理条数, 本批失败条数, 最后失败模型)。

    分三段执行：先认领批次并提交（避免在持有写锁期间做网络调用），再统一编码，
    最后单独写回结果。
    """
    # 第一阶段：认领批次（含失败重试提升与 settings 行补齐），提交释放写锁
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
            return 0, 0, None
        entry_ids = {row.entry_id for row in rows}
        entries = {
            entry.id: entry
            for entry in (
                await db.execute(select(Entry).where(Entry.id.in_(entry_ids)))
            )
            .scalars()
            .all()
        }
        for workspace_id in {row.workspace_id for row in rows}:
            await get_settings_row(db, workspace_id)
        batch = [
            (row.id, row.workspace_id, entries.get(row.entry_id)) for row in rows
        ]
        await db.commit()

    # 第二阶段：网络编码（不持有任何写事务）
    results: list[tuple[int, EmbeddingResult]] = []
    async with async_session_factory() as db:
        async with httpx.AsyncClient(timeout=30) as http_client:
            for row_id, workspace_id, entry in batch:
                if entry is None:
                    continue
                result = await encode_text(
                    db,
                    workspace_id,
                    entry_text(entry),
                    client=http_client,
                )
                results.append((row_id, result))

    # 第三阶段：写回结果
    failed_in_batch = 0
    failed_model: str | None = None
    async with async_session_factory() as db:
        for row_id, result in results:
            row = await db.get(EntryEmbedding, row_id)
            if row is None:
                continue
            if result.vector is not None:
                row.embedding = serialize_vector(result.vector)
                row.dimension = len(result.vector)
                row.model = result.model
                row.status = EMBEDDING_READY
                row.error = None
                row.retry_count = 0
            else:
                row.status = EMBEDDING_FAILED
                row.error = result.error
                row.retry_count += 1
                failed_in_batch += 1
                failed_model = result.model
        await db.commit()
    return len(results), failed_in_batch, failed_model


async def run_embedding_worker(stop_event: asyncio.Event) -> None:
    """常驻轮询循环，直到 stop_event 被设置。"""
    try:
        async with async_session_factory() as db:
            created = await backfill_missing_embedding_rows(db)
            if created:
                logger.info("向量回填：为 %d 条历史 Entry 创建待重建记录", created)
    except Exception:  # noqa: BLE001
        logger.exception("向量回填失败，继续进入轮询")
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            handled, failed_in_batch, failed_model = await process_pending_embeddings()
            if handled > 0 and failed_in_batch == handled:
                consecutive_failures += handled
            else:
                consecutive_failures = 0
            if consecutive_failures >= CIRCUIT_FAIL_THRESHOLD and failed_model is not None:
                async with async_session_factory() as db:
                    paused = await pause_remaining_pending(db, failed_model)
                    await db.commit()
                logger.warning(
                    "向量编码连续失败 %d 条（模型 %s），熔断并暂停该模型剩余 %d 条待重建",
                    consecutive_failures,
                    failed_model,
                    paused,
                )
                consecutive_failures = 0
        except Exception:  # noqa: BLE001
            logger.exception("处理待重建向量发生未预期错误")
            handled = 0

        if not handled:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass
