"""行为信号只读查询 API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbSession, get_current_workspace
from app.models import BehaviorSignal, Workspace
from app.schemas.behavior_signal import BehaviorSignalOut

router = APIRouter(prefix="/api", tags=["behavior-signals"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


@router.get("/behavior-signals", response_model=list[BehaviorSignalOut])
async def list_behavior_signals(
    db: DbSession,
    workspace: CurrentWorkspace,
    signal_type: Annotated[str | None, Query(max_length=32)] = None,
    project_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BehaviorSignal]:
    """返回当前 Workspace 的行为信号（只读，无写端点）。"""
    stmt = (
        select(BehaviorSignal)
        .where(BehaviorSignal.workspace_id == workspace.id)
        .order_by(BehaviorSignal.created_at.desc(), BehaviorSignal.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if signal_type is not None:
        stmt = stmt.where(BehaviorSignal.signal_type == signal_type)
    if project_id is not None:
        stmt = stmt.where(BehaviorSignal.project_id == project_id)
    return list((await db.execute(stmt)).scalars().all())
