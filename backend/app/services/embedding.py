"""embedding 编码服务：豆包多模态向量化端点与离线确定性降级。"""

import hashlib
import logging

import httpx
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Entry, EntryEmbedding, Project
from app.models.entry_embedding import (
    EMBEDDING_FAILED,
    EMBEDDING_PENDING,
    EMBEDDING_READY,
)
from app.schemas.ai_settings import (
    ConnectionTestOut,
    EmbeddingIndexStatusItem,
    EmbeddingIndexStatusOut,
)
from app.services.ai_models import get_settings_row
from app.services.secret_store import get_secret_store, secret_key

logger = logging.getLogger(__name__)

# embedding 固定复用豆包 Provider 的密钥（与视觉模型同账号、同 base_url）
EMBEDDING_PROVIDER = "doubao"

# 离线确定性 demo embedding 的维度；仅测试/未配置链路使用，与真实模型维度无关
_DEMO_DIMENSION = 256


class EmbeddingResult(BaseModel):
    """一次 embedding 编码的结果与可观测信息。"""

    vector: list[float] | None
    provider: str
    model: str
    is_fallback: bool
    error: str | None


def _demo_vector(text: str) -> list[float]:
    """离线确定性 demo embedding：字符 bigram 哈希到固定维度并归一化。"""
    normalized = "".join(ch for ch in text.casefold() if ch.isalnum())
    vector = [0.0] * _DEMO_DIMENSION
    for i in range(max(0, len(normalized) - 1)):
        gram = normalized[i : i + 2]
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % _DEMO_DIMENSION
        vector[index] += 1.0
    norm = sum(value * value for value in vector) ** 0.5
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


async def _get_embedding_secret(db: AsyncSession, workspace_id: int) -> str | None:
    """读取豆包密钥（与视觉模型共用）。"""
    return get_secret_store().get(secret_key(workspace_id, EMBEDDING_PROVIDER))


async def encode_text(
    db: AsyncSession,
    workspace_id: int,
    text: str,
) -> EmbeddingResult:
    """把纯文本编码为稠密向量；未配置密钥或调用失败时返回降级结果。"""
    row = await get_settings_row(db, workspace_id)
    model = row.embedding_model
    secret = await _get_embedding_secret(db, workspace_id)
    if not secret:
        return EmbeddingResult(
            vector=None,
            provider=EMBEDDING_PROVIDER,
            model=model,
            is_fallback=True,
            error="未配置豆包密钥",
        )
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{settings.doubao_base_url}/embeddings/multimodal",
                headers={"Authorization": f"Bearer {secret}"},
                json={"model": model, "input": [{"type": "text", "text": text}]},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or {}
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            items = []
        if not items or "embedding" not in items[0]:
            raise RuntimeError("embedding 响应缺少向量数据")
        vector = [float(value) for value in items[0]["embedding"]]
        if not vector:
            raise RuntimeError("embedding 向量为空")
        return EmbeddingResult(
            vector=vector,
            provider=EMBEDDING_PROVIDER,
            model=model,
            is_fallback=False,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("embedding 编码失败，降级确定性召回：%s", exc)
        return EmbeddingResult(
            vector=None,
            provider=EMBEDDING_PROVIDER,
            model=model,
            is_fallback=True,
            error=f"编码失败：{exc}",
        )


async def test_embedding_connection(db: AsyncSession, workspace_id: int) -> ConnectionTestOut:
    """用最小纯文本编码测试 embedding 连接并返回结果。"""
    result = await encode_text(db, workspace_id, "测试")
    if result.vector is not None:
        return ConnectionTestOut(
            ok=True,
            message=f"embedding 可用（{result.model}，{len(result.vector)} 维）",
        )
    return ConnectionTestOut(ok=False, message=result.error or "embedding 不可用")


async def get_embedding_index_status(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None = None,
) -> EmbeddingIndexStatusOut:
    """统计当前 Workspace（或指定项目）的语义索引状态。"""
    row = await get_settings_row(db, workspace_id)
    model = row.embedding_model

    total_stmt = (
        select(func.count(Entry.id))
        .join(Project, Entry.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    )
    if project_id is not None:
        total_stmt = total_stmt.where(Entry.project_id == project_id)
    total = (await db.execute(total_stmt)).scalar_one()

    count_stmt = (
        select(EntryEmbedding.status, func.count())
        .where(
            EntryEmbedding.workspace_id == workspace_id,
            EntryEmbedding.model == model,
        )
        .group_by(EntryEmbedding.status)
    )
    if project_id is not None:
        count_stmt = count_stmt.where(EntryEmbedding.project_id == project_id)
    counts = {status: count for status, count in (await db.execute(count_stmt)).all()}
    ready = counts.get(EMBEDDING_READY, 0)
    pending = counts.get(EMBEDDING_PENDING, 0)
    failed = counts.get(EMBEDDING_FAILED, 0)
    missing = max(0, total - ready - pending - failed)

    items_stmt = (
        select(EntryEmbedding, Entry.title)
        .join(Entry, EntryEmbedding.entry_id == Entry.id)
        .where(
            EntryEmbedding.workspace_id == workspace_id,
            EntryEmbedding.model == model,
            EntryEmbedding.status == EMBEDDING_FAILED,
        )
        .order_by(EntryEmbedding.updated_at.desc())
        .limit(20)
    )
    if project_id is not None:
        items_stmt = items_stmt.where(EntryEmbedding.project_id == project_id)
    failed_items = [
        EmbeddingIndexStatusItem(entry_id=embedding.entry_id, title=title, error=embedding.error)
        for embedding, title in (await db.execute(items_stmt)).all()
    ]
    return EmbeddingIndexStatusOut(
        total=total,
        ready=ready,
        pending=pending,
        failed=failed,
        missing=missing,
        failed_items=failed_items,
    )


async def retry_failed_embeddings(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None = None,
) -> int:
    """把失败向量标记为待重建并清零重试计数，返回受影响行数。"""
    row = await get_settings_row(db, workspace_id)
    stmt = update(EntryEmbedding).where(
        EntryEmbedding.workspace_id == workspace_id,
        EntryEmbedding.model == row.embedding_model,
        EntryEmbedding.status == EMBEDDING_FAILED,
    )
    if project_id is not None:
        stmt = stmt.where(EntryEmbedding.project_id == project_id)
    result = await db.execute(
        stmt.values(status=EMBEDDING_PENDING, error=None, retry_count=0)
    )
    return result.rowcount or 0


async def rebuild_all_embeddings(
    db: AsyncSession,
    workspace_id: int,
    project_id: int | None = None,
) -> int:
    """把当前模型全部向量标记为待重建（换模型或全量重试用）。"""
    row = await get_settings_row(db, workspace_id)
    stmt = update(EntryEmbedding).where(
        EntryEmbedding.workspace_id == workspace_id,
        EntryEmbedding.model == row.embedding_model,
    )
    if project_id is not None:
        stmt = stmt.where(EntryEmbedding.project_id == project_id)
    result = await db.execute(
        stmt.values(status=EMBEDDING_PENDING, error=None, retry_count=0)
    )
    return result.rowcount or 0
