"""当前用户信息路由（受保护业务路由示例）。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_current_workspace
from app.models import User, Workspace
from app.schemas.auth import MeResponse, UserOut, WorkspaceOut

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=MeResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
    workspace: Annotated[Workspace, Depends(get_current_workspace)],
) -> MeResponse:
    """返回当前用户与其默认 Workspace。"""
    return MeResponse(
        user=UserOut(id=user.id, username=user.username, created_at=user.created_at),
        workspace=WorkspaceOut(id=workspace.id, name=workspace.name),
    )
