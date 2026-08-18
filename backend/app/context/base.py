"""项目上下文生成器抽象与结构化输出。"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.models import Node, Project


class GenerationMeta(BaseModel):
    """一次上下文生成的来源元数据，用于可观测性。"""

    provider: str
    model: str | None = None
    is_fallback: bool = False


class ProjectContextCorrections(BaseModel):
    """用户对 AI 生成字段的高优先级纠正（部分覆盖）。"""

    project_summary: str | None = Field(default=None, description="用户纠正后的项目概要")
    current_focus: str | None = Field(default=None, description="用户纠正后的当前关注方向")


class ProjectContextDraft(BaseModel):
    """一次项目上下文生成的候选结果。"""

    project_summary: str = Field(description="AI 项目概要")
    current_focus: str = Field(description="当前关注方向")
    directory_topics: list[str] = Field(description="目录主题列表")
    recent_themes: list[str] = Field(default_factory=list, description="近期主题列表")


class ProjectContextGenerator(ABC):
    """负责基于项目说明与正式目录生成项目上下文草稿。"""

    provider_name: str = "abstract"

    @abstractmethod
    async def generate(
        self,
        db,
        project: Project,
        nodes: list[Node],
        entries_summary: dict | None = None,
        top_level_nodes: list[dict] | None = None,
        corrections: ProjectContextCorrections | None = None,
    ) -> tuple[ProjectContextDraft, GenerationMeta]:
        """生成结构化项目上下文草稿；失败时抛出异常。"""
