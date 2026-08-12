"""未接入的真实供应商占位实现。

deepseek / doubao 仅定义类与构造，不接真实 API；调用时抛出明确错误，
避免静默行为。
"""

from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.providers.doubao import DoubaoProvider

__all__ = ["DeepSeekProvider", "DoubaoProvider"]
