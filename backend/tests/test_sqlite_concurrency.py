"""SQLite 开发库的并发写保护：WAL 与写锁等待。

背景（2026-09-24 真机验收）：处理 Worker 在 Provider 执行期间持有读事务时，
回滚日志模式会让采集请求的提交等待到超时，前端报「上传失败（HTTP 500）」。
这里固定住修复后的行为，避免回退。
"""

import asyncio
import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.session import (
    SQLITE_BUSY_TIMEOUT_SECONDS,
    async_session_factory,
    configure_sqlite_engine,
)
from app.main import create_app
from app.models import Candidate
from app.models.extraction import ROUTING_PENDING
from app.processing import worker


def _upload(client: TestClient) -> tuple[int, str]:
    registered = client.post(
        "/api/auth/register",
        json={"username": f"wal_{uuid.uuid4().hex[:10]}", "password": "password123"},
    )
    assert registered.status_code == 201
    response = client.post(
        "/api/sources",
        data={"capture_key": f"wal-{uuid.uuid4()}", "title": "并发写保护"},
        files={"files": ("grove.jpg", b"\xff\xd8\xff\xe0fake-jpeg", "image/jpeg")},
    )
    return response.status_code, response.text[:200]


def test_sqlite_连接启用_wal_与更长写锁等待(tmp_path: Path) -> None:
    """新连接 MUST 直接生效，不依赖手工执行 PRAGMA。"""
    target = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pragma.db")
    configure_sqlite_engine(target)

    async def _read() -> tuple[str, int]:
        async with target.connect() as connection:
            journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar()
            busy_timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar()
        await target.dispose()
        return str(journal_mode), int(busy_timeout)

    journal_mode, busy_timeout = asyncio.run(_read())

    assert journal_mode == "wal"
    assert busy_timeout == SQLITE_BUSY_TIMEOUT_SECONDS * 1000


def test_他人持有长事务时采集仍能提交(client: TestClient) -> None:
    """另一连接持有读事务期间，采集请求 MUST NOT 变成 500。

    修复前（回滚日志模式 + 5 秒等待）该请求会在读锁上超时，返回 500
    「database is locked」；WAL 下读不挡写，请求立即成功。
    """
    db_file = Path("test_grove.db")
    reader = sqlite3.connect(db_file, isolation_level=None)
    try:
        reader.execute("BEGIN")
        assert reader.execute("SELECT count(*) FROM sources").fetchone() is not None

        status_code, body = _upload(client)
    finally:
        reader.execute("COMMIT")
        reader.close()

    assert status_code == 201, body


def _assert_他人可立即写入() -> None:
    """另开连接抢一次写锁：当前连接若仍持有写事务，这里会立刻报 database is locked。"""
    probe = sqlite3.connect(Path("test_grove.db"), isolation_level=None, timeout=0.2)
    try:
        probe.execute("CREATE TABLE IF NOT EXISTS _lock_probe (id INTEGER PRIMARY KEY)")
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("INSERT INTO _lock_probe DEFAULT VALUES")
        probe.execute("ROLLBACK")
    finally:
        probe.close()


@pytest.fixture
async def api_client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_模型调用期间不持有写事务(api_client: httpx.AsyncClient, monkeypatch) -> None:
    """处理 Worker 等待模型返回时 MUST NOT 持有写事务，否则并发采集会 500。

    修复前 save_success_extraction 先 flush 再调路由与关系 Agent，整个模型调用
    期间都持着写锁；这里在两次模型调用处各探测一次「他人能否立即写入」。
    """
    from app.agents import organizing as organizing_agent
    from app.processing import organizing as organizing_provider
    from app.services import routing as routing_service

    username = f"lock_{uuid.uuid4().hex[:10]}"
    registered = await api_client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert registered.status_code == 201
    project = await api_client.post("/api/projects", json={"name": "写锁项目"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    uploaded = await api_client.post(
        "/api/sources",
        data={"text": "闭水试验至少持续 24 小时", "project_id": str(project_id)},
    )
    assert uploaded.status_code == 201

    probed: list[str] = []
    original_organizing = organizing_agent.run_organizing_agent
    original_routing = organizing_agent.run_routing_agent

    async def probed_organizing(*args, **kwargs):
        _assert_他人可立即写入()
        probed.append("organizing")
        return await original_organizing(*args, **kwargs)

    async def probed_routing(*args, **kwargs):
        _assert_他人可立即写入()
        probed.append("routing")
        return await original_routing(*args, **kwargs)

    monkeypatch.setattr(organizing_provider, "run_organizing_agent", probed_organizing)
    monkeypatch.setattr(routing_service, "run_routing_agent", probed_routing)

    triggered = await api_client.post(f"/api/sources/{uploaded.json()['id']}/process")
    assert triggered.status_code in {200, 202}
    assert await worker.process_one_task() is True

    # 路由与关系判断是两次独立模型调用，路由那次的写锁边界必须已经释放
    assert probed == ["organizing", "routing"]

    # 分段提交不能吃掉结果：路由推荐与关系判断都应落库
    async with async_session_factory() as db:
        routed = (
            await db.execute(
                select(func.count())
                .select_from(Candidate)
                .where(
                    Candidate.source_id == uploaded.json()["id"],
                    Candidate.routing_status != ROUTING_PENDING,
                )
            )
        ).scalar_one()

    assert routed > 0
