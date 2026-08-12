"""AI Provider 抽象接口与候选结果模型。"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AIMessage(BaseModel):
    """一次补全请求中的单条消息。"""

    role: str = Field(description="角色：system / user / assistant")
    content: str = Field(description="消息内容")


class AICandidate(BaseModel):
    """AI 补全的候选结果。

    is_candidate 恒为 True：AI 输出永远是候选，正式记录只能由人确认后创建。
    """

    content: str = Field(description="生成内容")
    provider: str = Field(description="提供方标识，如 demo")
    model: str = Field(description="模型标识")
    is_candidate: bool = Field(default=True, description="是否为候选（恒为 True）")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AIProvider(ABC):
    """AI 供应商抽象基类。

    后续真实供应商（deepseek / doubao）实现本接口，消费方不感知具体实现。
    """

    provider_name: str = "abstract"

    @abstractmethod
    async def complete(self, messages: list[AIMessage]) -> AICandidate:
        """执行一次补全，返回结构化候选结果。"""
