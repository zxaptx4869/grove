"""认证相关的请求与响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """注册请求：账号 + 密码。"""

    username: str = Field(min_length=2, max_length=64, pattern=r"^\w+$", description="登录账号")
    password: str = Field(min_length=8, max_length=128, description="密码（至少 8 位）")


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """用户公开信息。"""

    id: int
    username: str
    created_at: datetime


class WorkspaceOut(BaseModel):
    """Workspace 公开信息。"""

    id: int
    name: str


class MeResponse(BaseModel):
    """当前用户与默认空间信息（/api/me）。"""

    user: UserOut
    workspace: WorkspaceOut
