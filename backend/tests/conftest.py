"""pytest 共享夹具。"""

import os

# 测试使用独立数据库，避免与开发服务数据/Worker 相互干扰
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_grove.db")
# 测试环境关闭后台 Worker，避免与测试写入产生竞态
os.environ.setdefault("PROCESSING_WORKER_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient

from app.db.session import Base, engine
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    """会话级夹具：确保测试库存在全部表结构（幂等）。"""

    import asyncio
    from pathlib import Path

    # 每次测试会话从干净数据库开始，避免残留数据影响结果
    db_file = Path("test_grove.db")
    if db_file.exists():
        db_file.unlink()

    async def _create_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())


@pytest.fixture
def client() -> TestClient:
    """提供 FastAPI TestClient 实例。"""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
