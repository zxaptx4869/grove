"""Grove 后端应用入口。

提供应用工厂 create_app；ASGI 入口为 main:app。
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.me import router as me_router
from app.api.project_context import router as project_context_router
from app.api.projects import router as projects_router
from app.api.sources import router as sources_router
from app.context.worker import run_context_worker
from app.core.config import get_settings
from app.processing.worker import run_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：按配置启动/停止进程内处理与上下文 Worker。"""
    settings = get_settings()
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.processing_worker_enabled:
        tasks.append(asyncio.create_task(run_worker(stop_event)))
    if settings.context_worker_enabled:
        tasks.append(asyncio.create_task(run_context_worker(stop_event)))
    yield
    stop_event.set()
    for task in tasks:
        await task


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例（应用工厂模式）。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="知林 Grove 个人知识管家后端 API",
        lifespan=lifespan,
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
    app.include_router(project_context_router)
    app.include_router(projects_router)
    app.include_router(sources_router)

    return app


app = create_app()
