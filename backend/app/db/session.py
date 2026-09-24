"""async SQLAlchemy 2 基础设施：引擎、会话工厂、声明式 Base。

本骨架阶段只建立机制（供后续业务 change 使用），不定义业务模型。
"""

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


settings = get_settings()

# SQLite 写锁等待上限（秒）：默认 5 秒挡不住「处理任务还在跑时又提交采集」的场景，
# 会直接抛 database is locked 变成 500；生产 MySQL 不受影响
SQLITE_BUSY_TIMEOUT_SECONDS = 15

# 异步引擎：SQLite 使用 aiosqlite，MySQL 8 通过 DATABASE_URL 切换（驱动 asyncmy）
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def configure_sqlite_engine(target_engine) -> None:  # noqa: ANN001
    """给 SQLite 引擎挂连接级 PRAGMA：WAL 让读不挡写、写不挡读。

    回滚日志模式下，处理 Worker 在 Provider（模型调用）期间持有的读事务会把采集
    请求的提交挡到超时，前端表现为「上传失败（HTTP 500）」；busy_timeout 同时把
    写-写等待上限从默认 5 秒抬高到 15 秒。
    """

    @event.listens_for(target_engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        finally:
            cursor.close()


if _is_sqlite(settings.database_url):
    configure_sqlite_engine(engine)

# 异步会话工厂：业务代码通过依赖注入获取 AsyncSession
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：为每个请求提供一个数据库会话。"""
    async with async_session_factory() as session:
        yield session
