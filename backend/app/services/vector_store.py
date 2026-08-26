"""Entry 向量持久化：序列化、写入、失效与余弦相似度。"""

import math
import struct

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, EntryEmbedding, Project
from app.models.entry_embedding import EMBEDDING_PENDING, EMBEDDING_READY
from app.services.ai_models import get_settings_row


def serialize_vector(vector: list[float]) -> bytes:
    """把 float32 向量序列化为 BLOB。"""
    return struct.pack(f"<{len(vector)}f", *vector)


def deserialize_vector(data: bytes | None, dimension: int) -> list[float]:
    """从 BLOB 反序列化向量；数据缺失或维度不符时返回空列表。"""
    if not data:
        return []
    if len(data) != dimension * 4:
        return []
    return list(struct.unpack(f"<{dimension}f", data))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度；维度不符或零向量返回 0。"""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def entry_text(entry: Entry) -> str:
    """组装 Entry 的向量编码文本（标题 + 内容 + 适用条件 + 备注）。"""
    parts = [entry.title or "", entry.content or ""]
    if entry.applicable_condition:
        parts.append(entry.applicable_condition)
    if entry.note:
        parts.append(entry.note)
    return "\n".join(parts)


async def mark_entry_embedding_pending(db: AsyncSession, entry: Entry) -> None:
    """把 Entry 向量标记为待重建；不存在时插入待处理记录。"""
    project = await db.get(Project, entry.project_id)
    if project is None:
        return
    settings_row = await get_settings_row(db, project.workspace_id)
    model = settings_row.embedding_model
    existing = (
        await db.execute(
            select(EntryEmbedding).where(
                EntryEmbedding.entry_id == entry.id,
                EntryEmbedding.model == model,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            EntryEmbedding(
                workspace_id=project.workspace_id,
                project_id=entry.project_id,
                entry_id=entry.id,
                model=model,
                dimension=0,
                status=EMBEDDING_PENDING,
            )
        )
    else:
        existing.status = EMBEDDING_PENDING
        existing.error = None


async def load_ready_vectors(
    db: AsyncSession,
    workspace_id: int,
    *,
    project_id: int | None = None,
    entry_ids: set[int] | None = None,
) -> list[tuple[int, list[float]]]:
    """加载当前 Workspace（可限定项目/Entry）内已就绪的向量，返回 (entry_id, vector)。"""
    stmt = select(EntryEmbedding).where(
        EntryEmbedding.workspace_id == workspace_id,
        EntryEmbedding.status == EMBEDDING_READY,
        EntryEmbedding.embedding.is_not(None),
    )
    if project_id is not None:
        stmt = stmt.where(EntryEmbedding.project_id == project_id)
    if entry_ids is not None:
        stmt = stmt.where(EntryEmbedding.entry_id.in_(entry_ids))
    rows = (await db.execute(stmt)).scalars().all()
    result: list[tuple[int, list[float]]] = []
    for row in rows:
        vector = deserialize_vector(row.embedding, row.dimension)
        if vector:
            result.append((row.entry_id, vector))
    return result
