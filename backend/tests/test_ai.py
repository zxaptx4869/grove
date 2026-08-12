"""AI 层骨架测试。"""

import pytest

from app.ai.base import AIMessage
from app.ai.demo import DemoProvider
from app.ai.factory import get_ai_provider


@pytest.mark.asyncio
async def test_demo_provider_is_deterministic() -> None:
    """相同输入应产生完全一致的候选内容。"""
    provider = DemoProvider()
    messages = [AIMessage(role="user", content="你好")]

    first = await provider.complete(messages)
    second = await provider.complete(messages)

    assert first.content == second.content
    assert first.is_candidate is True


def test_factory_returns_demo_by_default() -> None:
    """默认配置应返回 DemoProvider。"""
    provider = get_ai_provider()
    assert isinstance(provider, DemoProvider)


@pytest.mark.asyncio
async def test_deepseek_placeholder_raises() -> None:
    """未接入的供应商调用时应明确报错，而不是静默行为。"""
    from app.ai.providers.deepseek import DeepSeekProvider

    provider = DeepSeekProvider()
    with pytest.raises(NotImplementedError, match="尚未接入"):
        await provider.complete([AIMessage(role="user", content="你好")])
