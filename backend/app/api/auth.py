"""认证路由：注册、登录、登出。"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, create_session, get_current_user
from app.core.config import get_settings
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.models import Session, User, Workspace, WorkspaceMember
from app.schemas.auth import LoginRequest, RegisterRequest, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _set_session_cookie(response: Response, session: Session, token: str) -> None:
    """写入会话 Cookie（HttpOnly + SameSite=Lax，生产 Secure）。"""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
async def register(payload: RegisterRequest, response: Response, db: DbSession) -> User:
    """注册：创建用户 + 默认 Workspace + owner 成员关系，注册即登录。"""
    existing = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该账号已被占用")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    await db.flush()

    workspace = Workspace(name=f"{payload.username} 的空间")
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))

    token = generate_session_token()
    session = create_session(user.id)
    session.token_hash = hash_session_token(token)
    db.add(session)

    try:
        await db.commit()
    except IntegrityError as exc:
        # 并发注册撞唯一约束时兜底
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该账号已被占用") from exc

    await db.refresh(user)
    _set_session_cookie(response, session, token)
    return user


@router.post("/login", response_model=UserOut)
async def login(payload: LoginRequest, response: Response, db: DbSession) -> User:
    """登录：校验账号密码，成功创建会话并写 Cookie。"""
    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

    token = generate_session_token()
    session = create_session(user.id)
    session.token_hash = hash_session_token(token)
    db.add(session)
    await db.commit()
    await db.refresh(user)

    _set_session_cookie(response, session, token)
    return user


@router.post("/logout")
async def logout(
    response: Response,
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    session_cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> dict[str, bool]:
    """登出：删除当前会话并使 Cookie 失效。"""
    if session_cookie:
        stmt = select(Session).where(
            Session.token_hash == hash_session_token(session_cookie),
            Session.user_id == user.id,
        )
        session = (await db.execute(stmt)).scalar_one_or_none()
        if session is not None:
            await db.delete(session)
            await db.commit()
    response.delete_cookie(settings.session_cookie_name)
    return {"ok": True}
