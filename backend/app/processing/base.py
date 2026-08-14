"""处理 Provider 抽象接口。"""

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source


class ProcessingProvider(ABC):
    """负责处理一个 Source；失败时抛出异常。"""

    provider_name: str = "abstract"

    @abstractmethod
    async def process(self, db: AsyncSession, source: Source) -> None:
        """处理 Source；真实解析由后续 change 接入。"""
