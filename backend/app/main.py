"""Grove 后端应用入口。

提供应用工厂 create_app；ASGI 入口为 main:app。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.projects import router as projects_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例（应用工厂模式）。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="知林 Grove 个人知识管家后端 API",
    )

    # CORS：默认放行本地前端开发源，生产来源通过 FRONTEND_ORIGINS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(projects_router)

    return app


app = create_app()
