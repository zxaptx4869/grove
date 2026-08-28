"""FastAPI 依赖：当前用户与当前 Workspace。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_session_token
from app.db.session import get_db_session
from app.models import Session, User, Workspace, WorkspaceMember

settings = get_settings()
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或会话已失效",
    )


async def get_current_user(
    db: DbSession,
    session_cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """解析 Bearer 或 Cookie 会话；Bearer 存在时严格优先。"""
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token or token.strip() != token:
            raise _unauthorized()
    else:
        token = session_cookie
    if not token:
        raise _unauthorized()

    token_hash = hash_session_token(token)
    stmt = select(Session).where(
        Session.token_hash == token_hash,
        Session.expires_at > datetime.now(UTC),
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        raise _unauthorized()

    user = await db.get(User, session.user_id)
    if user is None:
        raise _unauthorized()
    return user


async def get_current_workspace(
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> Workspace:
    """解析当前用户的默认 Workspace；v1 注册时必然存在。"""
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )
    workspace = (await db.execute(stmt)).scalar_one_or_none()
    if workspace is None:
        raise _unauthorized()
    return workspace


def create_session(user_id: int) -> Session:
    """构造新会话（由路由负责入库与写 Cookie）。"""
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.session_max_age_days)
    return Session(user_id=user_id, expires_at=expires_at)
