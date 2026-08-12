"""AI 层骨架：Provider 抽象、确定性 Demo 实现与工厂。

铁律：AI 输出永远是候选（AICandidate.is_candidate 恒为 True），
不得直接写入或覆盖正式记录。
"""

from app.ai.factory import get_ai_provider

__all__ = ["get_ai_provider"]
