"""项目上下文生成器工厂。"""

from functools import lru_cache

from app.context.base import (
    ProjectContextCorrections,
    ProjectContextDraft,
    ProjectContextGenerator,
)
from app.context.demo import DemoProjectContextGenerator
from app.context.llm import LLMProjectContextGenerator
from app.core.config import get_settings
from app.models import Node, Project


class UnavailableProjectContextGenerator(ProjectContextGenerator):
    """未接入的真实生成器占位：调用时明确报错。"""

    provider_name = "unavailable"

    async def generate(
        self,
        db,
        project: Project,
        nodes: list[Node],
        entries_summary: dict | None = None,
        top_level_nodes: list[dict] | None = None,
        corrections: ProjectContextCorrections | None = None,
    ) -> ProjectContextDraft:
        del db, project, nodes, entries_summary, top_level_nodes, corrections
        raise NotImplementedError(
            "项目上下文生成 Provider 尚未接入，请在后续 change 完成实现后再使用。"
        )


@lru_cache
def get_project_context_generator() -> ProjectContextGenerator:
    """返回配置的项目上下文生成器；llm 使用真实模型，demo 为确定性实现。"""
    settings = get_settings()
    if settings.context_generator == "llm":
        return LLMProjectContextGenerator()
    if settings.context_generator == "demo":
        return DemoProjectContextGenerator()
    return UnavailableProjectContextGenerator()
