"""确定性 Demo 项目上下文生成器。"""

from app.context.base import (
    ProjectContextCorrections,
    ProjectContextDraft,
    ProjectContextGenerator,
)
from app.models import Node, Project


class DemoProjectContextGenerator(ProjectContextGenerator):
    """确定性实现：不依赖外部服务，纠正字段优先于默认生成。"""

    provider_name = "demo"

    async def generate(
        self,
        project: Project,
        nodes: list[Node],
        corrections: ProjectContextCorrections | None = None,
    ) -> ProjectContextDraft:
        """根据项目说明与正式目录生成固定格式的上下文草稿。"""
        corrections = corrections or ProjectContextCorrections()
        description = (project.description or "").strip() or "未填写项目说明"
        topics = [node.name for node in nodes if node.parent_id is None]

        project_summary = corrections.project_summary or (
            f"围绕「{description}」进行知识整理，当前目录包含 {len(nodes)} 个节点。"
        )
        current_focus = corrections.current_focus or "继续建立正式目录并采集原始材料。"

        return ProjectContextDraft(
            project_summary=project_summary,
            current_focus=current_focus,
            directory_topics=topics,
        )
