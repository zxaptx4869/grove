"""一次性阈值标定脚本：用现有候选的历史关系判定与 top-1 向量相似度，输出 T_high / T_low 建议值。

用法（在 backend 目录）：
    .venv/bin/python tools/embedding-threshold-calibration.py

前置条件：
- 已配置豆包视觉密钥（系统钥匙串），已开通 doubao-embedding-vision；
- 直接实时编码，不依赖已完成的向量重建。
"""

import asyncio
from statistics import median, quantiles

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import async_session_factory
from app.models import Candidate, Entry, Project
from app.services.embedding import encode_text
from app.services.vector_store import cosine_similarity

# 当前默认阈值（与 services/entry_relation.py 保持一致）
DEFAULT_HIGH = 0.85
DEFAULT_LOW = 0.45


async def _entry_vectors(
    db, workspace_id: int, entries: list[Entry]
) -> dict[int, list[float]]:
    """实时编码某 Workspace 下全部 Entry 并缓存向量。"""
    vectors: dict[int, list[float]] = {}
    for entry in entries:
        result = await encode_text(db, workspace_id, _entry_text(entry))
        if result.vector is not None:
            vectors[entry.id] = result.vector
        else:
            print(f"警告：Entry {entry.id} 编码失败：{result.error}")
    return vectors


def _entry_text(entry: Entry) -> str:
    parts = [entry.title or "", entry.content or ""]
    if entry.applicable_condition:
        parts.append(entry.applicable_condition)
    if entry.note:
        parts.append(entry.note)
    return "\n".join(parts)


async def main() -> None:
    """输出各关系状态下 top-1 相似度分布与阈值建议。"""
    async with async_session_factory() as db:
        candidates = (
            await db.execute(
                select(Candidate)
                .options(selectinload(Candidate.source))
                .where(Candidate.relation_status.in_(["duplicate", "supplement", "new"]))
            )
        ).scalars().all()
        if not candidates:
            print("没有可标定的候选（需要已判定 duplicate/supplement/new 的记录）")
            return

        scores: dict[str, list[float]] = {"duplicate": [], "supplement": [], "new": []}
        by_project: dict[int, list[Candidate]] = {}
        for candidate in candidates:
            project_id = candidate.source.project_id
            if project_id is not None:
                by_project.setdefault(project_id, []).append(candidate)

        for project_id, project_candidates in by_project.items():
            project = await db.get(Project, project_id)
            if project is None:
                continue
            entries = (
                await db.execute(select(Entry).where(Entry.project_id == project_id))
            ).scalars().all()
            vectors = await _entry_vectors(db, project.workspace_id, entries)
            if not vectors:
                print(f"项目 {project_id} 没有任何 Entry 编码成功，跳过")
                continue
            for candidate in project_candidates:
                result = await encode_text(
                    db,
                    project.workspace_id,
                    f"{candidate.title or ''}\n{candidate.content or ''}",
                )
                if result.vector is None:
                    continue
                top1 = 0.0
                for entry in entries:
                    if entry.id == candidate.entry_id:
                        continue
                    entry_vector = vectors.get(entry.id)
                    if entry_vector:
                        top1 = max(top1, cosine_similarity(result.vector, entry_vector))
                if candidate.relation_status in scores:
                    scores[candidate.relation_status].append(top1)

        print("top-1 向量相似度分布（按历史关系判定分组）：")
        for status, values in scores.items():
            if not values:
                print(f"  {status}: 无样本")
                continue
            p25, p50, p75 = quantiles(values, n=4, method="inclusive")
            print(
                f"  {status}: n={len(values)} median={median(values):.3f} "
                f"p25={p25:.3f} p75={p75:.3f} min={min(values):.3f} max={max(values):.3f}"
            )

        dup_scores = scores["duplicate"]
        new_scores = scores["new"]
        if dup_scores:
            print(
                f"建议 T_high ≥ {max(DEFAULT_HIGH, median(dup_scores)):.3f}"
                "（取 duplicate 中位数与默认值较大者）"
            )
        else:
            print(f"缺少 duplicate 样本，T_high 暂保持 {DEFAULT_HIGH}")
        if new_scores:
            print(
                f"建议 T_low ≤ {min(DEFAULT_LOW, median(new_scores)):.3f}"
                "（取 new 中位数与默认值较小者）"
            )
        else:
            print(f"缺少 new 样本，T_low 暂保持 {DEFAULT_LOW}")


if __name__ == "__main__":
    asyncio.run(main())
