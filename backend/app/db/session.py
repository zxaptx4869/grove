"""async SQLAlchemy 2 基础设施：引擎、会话工厂、声明式 Base。

本骨架阶段只建立机制（供后续业务 change 使用），不定义业务模型。
"""

from collections.abc import AsyncGenerator

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

# 异步引擎：SQLite 使用 aiosqlite，MySQL 8 通过 DATABASE_URL 切换（驱动 asyncmy）
engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

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
