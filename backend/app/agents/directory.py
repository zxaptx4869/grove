"""Directory Agent：从零起草目录，先问卷式澄清再生成候选树。"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.context.base import GenerationMeta
from app.models import Project
from app.services.ai_models import get_text_model


class ClarifyQuestionDraft(BaseModel):
    """一道澄清问题。"""

    id: str
    text: str
    options: list[str] = Field(default_factory=list)
    multiple: bool = False


class ClarifyResultDraft(BaseModel):
    """信息充分性判断与澄清问题。"""

    needs_more: bool = False
    questions: list[ClarifyQuestionDraft] = Field(default_factory=list)


class DirectoryNodeDraft(BaseModel):
    """候选目录节点。"""

    name: str = Field(min_length=1)
    description: str | None = None
    children: list["DirectoryNodeDraft"] = Field(default_factory=list)


DirectoryNodeDraft.model_rebuild()


class DirectoryDraftDraft(BaseModel):
    """一次从零起草的候选树。"""

    nodes: list[DirectoryNodeDraft] = Field(default_factory=list)


CLARIFY_SYSTEM_PROMPT = """你是 Grove 的 Directory Agent 澄清步骤。请判断是否需要向用户澄清。

要求：
1. 一次返回 3-5 道结构化问题，不要逐题追问。
2. 每道问题包含 id、text、options（选项列表）与 multiple（是否多选）。
3. 问题必须能让用户通过点选选项或自由输入回答。
4. 信息足够时 needs_more 为 false 且不返回问题。"""


DRAFT_SYSTEM_PROMPT = """你是 Grove 的 Directory Agent 起草步骤。
请基于项目说明、项目上下文与用户澄清答案生成候选目录树。

要求：
1. 节点名称简洁（2-8 字），description 用一句话说明该节点用途。
2. 层级控制在 2-3 层，总节点数不超过 30。
3. 输出始终是候选草稿，不创建或修改正式目录。"""


def _offline_clarify(clarify_batches: int) -> ClarifyResultDraft:
    """离线确定性澄清：首次返回两道固定问题。"""
    if clarify_batches > 0:
        return ClarifyResultDraft(needs_more=False)
    return ClarifyResultDraft(
        needs_more=True,
        questions=[
            ClarifyQuestionDraft(
                id="dimension",
                text="目录按什么维度组织？",
                options=["按阶段", "按空间", "按主题"],
                multiple=False,
            ),
            ClarifyQuestionDraft(
                id="modules",
                text="希望覆盖哪些重点模块？",
                options=["规划与预算", "施工管理", "材料采购", "验收与入住"],
                multiple=True,
            ),
        ],
    )


def _offline_draft(project: Project) -> DirectoryDraftDraft:
    """离线确定性候选树。"""
    return DirectoryDraftDraft(
        nodes=[
            DirectoryNodeDraft(
                name="项目规划",
                description=f"围绕「{project.name}」的目标与范围规划",
                children=[
                    DirectoryNodeDraft(name="需求确认", description="明确目标与优先级"),
                    DirectoryNodeDraft(name="预算框架", description="预算分配与边界"),
                ],
            ),
            DirectoryNodeDraft(
                name="实施执行",
                description="执行过程中的知识与经验",
                children=[
                    DirectoryNodeDraft(name="施工管理", description="进度、质量与沟通"),
                    DirectoryNodeDraft(name="材料采购", description="选型、比价与验收"),
                ],
            ),
            DirectoryNodeDraft(
                name="验收归档",
                description="验收、交付与知识归档",
                children=[
                    DirectoryNodeDraft(name="验收标准", description="检查清单与标准"),
                    DirectoryNodeDraft(name="入住准备", description="入住前注意事项"),
                ],
            ),
        ]
    )


async def run_directory_clarify(
    db,
    workspace_id: int,
    project: Project,
    context_text: str,
    clarify_batches: int,
) -> tuple[ClarifyResultDraft, GenerationMeta]:
    """运行澄清步骤，返回结构化问题与生成来源。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            _offline_clarify(clarify_batches),
            GenerationMeta(provider="offline", model=None, is_fallback=True),
        )

    agent = Agent(
        text_model,
        output_type=ClarifyResultDraft,
        system_prompt=CLARIFY_SYSTEM_PROMPT,
        retries=1,
    )
    result = await agent.run(context_text)
    if result.output is None:
        raise RuntimeError("Directory Agent 澄清步骤未返回结构化结果")
    model_name = getattr(text_model, "model_name", None) or "unknown"
    return result.output, GenerationMeta(provider="llm", model=str(model_name), is_fallback=False)


async def run_directory_draft(
    db,
    workspace_id: int,
    project: Project,
    context_text: str,
) -> tuple[DirectoryDraftDraft, GenerationMeta]:
    """运行起草步骤，返回候选树与生成来源。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            _offline_draft(project),
            GenerationMeta(provider="offline", model=None, is_fallback=True),
        )

    agent = Agent(
        text_model,
        output_type=DirectoryDraftDraft,
        system_prompt=DRAFT_SYSTEM_PROMPT,
        retries=1,
    )
    result = await agent.run(context_text)
    if result.output is None:
        raise RuntimeError("Directory Agent 起草步骤未返回结构化结果")
    model_name = getattr(text_model, "model_name", None) or "unknown"
    return result.output, GenerationMeta(provider="llm", model=str(model_name), is_fallback=False)
