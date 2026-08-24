"""行为信号记录服务：把「AI 推荐 vs 用户决定」写入信号表。"""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BehaviorSignal


def _json_snapshot(value: dict[str, Any] | None) -> str | None:
    """把推荐/最终值快照序列化为 JSON 文本。"""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def acceptance(recommended_value: Any, final_value: Any) -> bool | None:
    """推荐接受度：无推荐返回 None，有推荐时按最终值是否一致判定。"""
    if recommended_value is None:
        return None
    return final_value == recommended_value


async def record_behavior_signal(
    db: AsyncSession,
    *,
    workspace_id: int,
    user_id: int | None,
    signal_type: str,
    recommended: dict[str, Any] | None = None,
    final: dict[str, Any] | None = None,
    accepted: bool | None = None,
    detail: str | None = None,
    project_id: int | None = None,
    source_id: int | None = None,
    candidate_id: int | None = None,
) -> BehaviorSignal:
    """写入一条行为信号；仅 flush，跟随业务事务一起提交或回滚。"""
    signal = BehaviorSignal(
        workspace_id=workspace_id,
        user_id=user_id,
        signal_type=signal_type,
        recommended=_json_snapshot(recommended),
        final=_json_snapshot(final),
        accepted=accepted,
        detail=detail,
        project_id=project_id,
        source_id=source_id,
        candidate_id=candidate_id,
    )
    db.add(signal)
    await db.flush()
    return signal
