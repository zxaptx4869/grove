"""豆包供应商占位实现（未接入真实 API）。"""

from app.ai.base import AICandidate, AIMessage, AIProvider


class DoubaoProvider(AIProvider):
    """豆包占位实现。

    骨架阶段仅定义接口形状；真实接入由后续 change 完成。
    """

    provider_name = "doubao"
    model = "doubao-pro"

    async def complete(self, messages: list[AIMessage]) -> AICandidate:
        raise NotImplementedError(
            "豆包尚未接入真实 API，请在后续 change 中完成实现后再使用。"
        )
