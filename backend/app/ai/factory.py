"""AI Provider 工厂：按配置返回对应实现。"""

from functools import lru_cache

from app.ai.base import AIProvider
from app.ai.demo import DemoProvider
from app.ai.providers import DeepSeekProvider, DoubaoProvider
from app.core.config import get_settings


@lru_cache
def get_ai_provider() -> AIProvider:
    """根据 Settings.ai_provider 返回对应 Provider。

    - demo：确定性实现，默认值；
    - deepseek / doubao：占位实现，调用时明确报「未接入」。
    """
    settings = get_settings()
    providers: dict[str, type[AIProvider]] = {
        "demo": DemoProvider,
        "deepseek": DeepSeekProvider,
        "doubao": DoubaoProvider,
    }

    try:
        provider_cls = providers[settings.ai_provider]
    except KeyError as exc:
        raise ValueError(
            f"未知的 AI 供应商: {settings.ai_provider!r}，可选值为 {', '.join(providers)}"
        ) from exc

    return provider_cls()
