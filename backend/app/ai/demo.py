"""DemoProvider：确定性实现，不依赖任何外部 API 或网络。"""

from app.ai.base import AICandidate, AIMessage, AIProvider


class DemoProvider(AIProvider):
    """确定性 Demo 供应商。

    相同输入必然产生相同输出，用于离线验收与联调占位。
    """

    provider_name = "demo"
    model = "grove-demo-1"

    async def complete(self, messages: list[AIMessage]) -> AICandidate:
        """拼接消息后返回固定格式的候选内容。"""
        parts = [f"[{message.role}] {message.content}" for message in messages]
        content = "【Demo 候选】" + " | ".join(parts)
        return AICandidate(content=content, provider=self.provider_name, model=self.model)
