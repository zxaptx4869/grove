"""基于真实文本模型的项目上下文生成器。"""

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.context.base import (
    ProjectContextCorrections,
    ProjectContextDraft,
    ProjectContextGenerator,
)
from app.models import Node, Project
from app.services.ai_models import get_text_model

CONTEXT_SYSTEM_PROMPT = """你是 Grove 的项目上下文生成器。请基于给定输入生成结构化项目上下文。

要求：
1. 用户项目说明是最高优先级输入，不得覆盖或改写其意图。
2. directory_topics 必须原样使用给定的顶级目录节点名称，不得新增、删改或改写。
3. project_summary 用一两句话概括这个项目总体在做什么，避免罗列目录名称或统计数字。
4. current_focus 概括当前最值得关注的方向，不超过两句话。
5. recent_themes 基于近期 Entry 标题提炼 3-5 个简短主题短语，不要直接复制完整标题。
6. AI 输出只是候选上下文，不得修改任何正式数据。"""


def _format_context(
    project: Project,
    nodes: list[Node],
    entries_summary: dict | None,
    top_level_nodes: list[dict] | None,
    corrections: ProjectContextCorrections | None,
) -> str:
    """把项目上下文生成所需的实时数据组装为模型输入。"""
    parts = [f"项目：{project.name}"]
    parts.append(f"项目说明：{project.description or '（未填写）'}")

    parts.append("顶级目录节点：")
    for item in top_level_nodes or []:
        description = item.get("description") or "无说明"
        parts.append(f"- {item['name']}：{description}（{item.get('entry_count', 0)} 条知识）")

    summary = entries_summary or {}
    parts.append(f"已确认 Entry 总数：{summary.get('total', 0)}")
    by_type = summary.get("by_type") or {}
    if by_type:
        parts.append("类型分布：" + "、".join(f"{key} {value}" for key, value in by_type.items()))
    else:
        parts.append("类型分布：无")

    parts.append("近期 Entry：")
    for item in (summary.get("recent") or [])[:20]:
        parts.append(f"- {item.get('title', '')}（{item.get('node_name', '')}）")

    if corrections:
        if corrections.project_summary:
            parts.append(f"用户纠正的项目概要（最高优先级）：{corrections.project_summary}")
        if corrections.current_focus:
            parts.append(f"用户纠正的当前关注（最高优先级）：{corrections.current_focus}")
    return "\n".join(parts)


def _offline_draft(
    project: Project,
    nodes: list[Node],
    entries_summary: dict | None,
    top_level_nodes: list[dict] | None,
    corrections: ProjectContextCorrections | None,
) -> ProjectContextDraft:
    """无可用密钥时的确定性回退输出。"""
    corrections = corrections or ProjectContextCorrections()
    description = (project.description or "").strip() or "未填写项目说明"
    topics = (
        [item["name"] for item in top_level_nodes]
        if top_level_nodes
        else [node.name for node in nodes if node.parent_id is None]
    )
    total_entries = int((entries_summary or {}).get("total", 0))
    recent_titles: list[str] = []
    for item in (entries_summary or {}).get("recent", []):
        title = str(item.get("title", "")).strip()
        if title and title not in recent_titles:
            recent_titles.append(title)
        if len(recent_titles) >= 5:
            break
    return ProjectContextDraft(
        project_summary=corrections.project_summary
        or (
            f"围绕「{description}」进行知识整理，当前目录包含 {len(nodes)} 个节点，"
            f"已确认 {total_entries} 条知识。"
        ),
        current_focus=corrections.current_focus or "继续建立正式目录并采集原始材料。",
        directory_topics=topics,
        recent_themes=recent_titles,
    )


class LLMProjectContextGenerator(ProjectContextGenerator):
    """调用真实文本模型生成项目上下文草稿；无密钥时回退为确定性输出。"""

    provider_name = "llm"

    async def generate(
        self,
        db,
        project: Project,
        nodes: list[Node],
        entries_summary: dict | None = None,
        top_level_nodes: list[dict] | None = None,
        corrections: ProjectContextCorrections | None = None,
    ) -> ProjectContextDraft:
        text_model = await get_text_model(db, project.workspace_id)
        if isinstance(text_model, TestModel):
            return _offline_draft(
                project,
                nodes,
                entries_summary,
                top_level_nodes,
                corrections,
            )

        context = _format_context(
            project,
            nodes,
            entries_summary,
            top_level_nodes,
            corrections,
        )
        agent = Agent(
            text_model,
            output_type=ProjectContextDraft,
            system_prompt=CONTEXT_SYSTEM_PROMPT,
            retries=1,
        )
        result = await agent.run(context)
        if result.output is None:
            raise RuntimeError("项目上下文生成器未返回结构化结果")
        return result.output
