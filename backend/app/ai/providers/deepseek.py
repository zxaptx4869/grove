"""DeepSeek 供应商占位实现（未接入真实 API）。"""

from app.ai.base import AICandidate, AIMessage, AIProvider


class DeepSeekProvider(AIProvider):
    """DeepSeek 占位实现。

    骨架阶段仅定义接口形状；真实接入由后续 change 完成。
    """

    provider_name = "deepseek"
    model = "deepseek-chat"

    async def complete(self, messages: list[AIMessage]) -> AICandidate:
        raise NotImplementedError(
            "DeepSeek 尚未接入真实 API，请在后续 change 中完成实现后再使用。"
        )
