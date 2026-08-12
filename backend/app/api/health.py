"""健康检查路由。"""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """存活探针：返回服务状态与版本，不依赖数据库。"""
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}
