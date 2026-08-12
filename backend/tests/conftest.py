"""pytest 共享夹具。"""

import pytest
from fastapi.testclient import TestClient

from app.db.session import Base, engine
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def prepare_database() -> None:
    """会话级夹具：确保测试库存在全部表结构（幂等）。"""

    import asyncio

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
