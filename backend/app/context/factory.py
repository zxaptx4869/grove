"""项目上下文生成器工厂。"""

from functools import lru_cache

from app.context.base import (
    ProjectContextCorrections,
    ProjectContextDraft,
    ProjectContextGenerator,
)
from app.context.demo import DemoProjectContextGenerator
from app.core.config import get_settings
from app.models import Node, Project


class UnavailableProjectContextGenerator(ProjectContextGenerator):
    """未接入的真实生成器占位：调用时明确报错。"""

    provider_name = "unavailable"

    async def generate(
        self,
        project: Project,
        nodes: list[Node],
        corrections: ProjectContextCorrections | None = None,
    ) -> ProjectContextDraft:
        del project, nodes, corrections
        raise NotImplementedError(
            "项目上下文生成 Provider 尚未接入，请在后续 change 完成实现后再使用。"
        )


@lru_cache
def get_project_context_generator() -> ProjectContextGenerator:
    """返回配置的项目上下文生成器；非 demo 一律返回未接入占位。"""
    settings = get_settings()
    if settings.context_generator == "demo":
        return DemoProjectContextGenerator()
    return UnavailableProjectContextGenerator()
