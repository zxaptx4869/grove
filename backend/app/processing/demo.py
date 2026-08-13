"""确定性 Demo 处理 Provider。"""

import asyncio

from app.models import Source
from app.processing.base import ProcessingProvider


class DemoProcessingProvider(ProcessingProvider):
    """确定性实现：短暂延迟后成功，不依赖外部服务。"""

    provider_name = "demo"

    async def process(self, source: Source) -> None:
        del source  # 当前无需读取内容，仅走通流程
        await asyncio.sleep(0.05)
