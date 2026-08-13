"""处理 Provider 工厂：按配置返回实现。"""

from functools import lru_cache

from app.core.config import get_settings
from app.models import Source
from app.processing.base import ProcessingProvider
from app.processing.demo import DemoProcessingProvider


class UnavailableProcessingProvider(ProcessingProvider):
    """未接入的真实 Provider 占位：调用时明确报错。"""

    provider_name = "unavailable"

    async def process(self, source: Source) -> None:
        raise NotImplementedError("真实处理 Provider 尚未接入，请在后续 change 完成实现后再使用。")


@lru_cache
def get_processing_provider() -> ProcessingProvider:
    """返回配置的处理 Provider；非 demo 一律返回未接入占位。"""
    settings = get_settings()
    if settings.processing_provider == "demo":
        return DemoProcessingProvider()
    return UnavailableProcessingProvider()
