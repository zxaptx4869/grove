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


class ChatRoundResultDraft(BaseModel):
    """一轮对话调整的结果：回复文字 + 可选完整候选树。"""

    reply_text: str = ""
    tree: list[DirectoryNodeDraft] | None = None


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


EXPAND_SYSTEM_PROMPT = """你是 Grove 的 Directory Agent 节点拓展步骤。
请基于目标节点、现有子树、项目上下文与相关 Entry，输出目标节点下的完整目标子树。

要求：
1. 输出的是目标节点下的子节点数组（嵌套 children），代表拓展后的完整目标子树。
2. 现有子节点必须按原名原样保留，禁止改名；如确需改名，保留原名并在回复中说明需手动操作。
3. 只新增更细的结构：新增节点名称简洁（2-8 字），description 用一句话说明用途。
4. 新增层级不超过 5 层，新增节点数不超过 30。
5. 目标节点自身的名称与说明由系统固定，不得出现在输出中。
6. 输出始终是候选草稿，不创建或修改正式目录。"""


REFINE_SYSTEM_PROMPT = """你是 Grove 的 Directory Agent 调整步骤。
请基于当前候选树与对话调整目录草稿。

要求：
1. reply_text 是对用户说的自然回复，直接说明理解和处理结果；
   严禁提及内部字段或机制（如 tree、JSON、null、结构、输出格式等）。
2. 如果对话要求修改目录，返回完整的更新后候选树；
   未要求改动或纯讨论时不返回树，并用自然语言告知用户草稿保持不变。
3. 返回完整树时，未涉及的部分必须原样保留，避免节点漂移。
4. 输出始终是候选草稿，不创建或修改正式目录。"""


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


def _offline_refine() -> ChatRoundResultDraft:
    """离线确定性调整回复：纯讨论，不改树。"""
    return ChatRoundResultDraft(reply_text="已收到你的消息，当前草稿保持不变。")


def _offline_expand(target_name: str) -> DirectoryDraftDraft:
    """离线确定性节点拓展：返回三级通用细化结构。"""
    return DirectoryDraftDraft(
        nodes=[
            DirectoryNodeDraft(
                name="细化目标",
                description=f"围绕「{target_name}」梳理具体目标与边界",
                children=[
                    DirectoryNodeDraft(name="目标拆解", description="把大目标拆成可执行子项"),
                    DirectoryNodeDraft(name="范围界定", description="明确做什么与不做什么"),
                ],
            ),
            DirectoryNodeDraft(
                name="关键要点",
                description="执行过程中的关键注意事项",
                children=[
                    DirectoryNodeDraft(name="步骤要点", description="按顺序记录关键动作"),
                    DirectoryNodeDraft(name="易错提醒", description="常见错误与规避"),
                ],
            ),
            DirectoryNodeDraft(
                name="相关经验",
                description="沉淀与目标节点相关的经验教训",
                children=[
                    DirectoryNodeDraft(name="成功做法", description="已验证有效的做法"),
                    DirectoryNodeDraft(name="失败教训", description="踩坑记录与反思"),
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


async def run_directory_expand(
    db,
    workspace_id: int,
    project: Project,
    context_text: str,
    target_name: str,
) -> tuple[DirectoryDraftDraft, GenerationMeta]:
    """运行节点拓展步骤，返回完整目标子树与生成来源。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            _offline_expand(target_name),
            GenerationMeta(provider="offline", model=None, is_fallback=True),
        )

    agent = Agent(
        text_model,
        output_type=DirectoryDraftDraft,
        system_prompt=EXPAND_SYSTEM_PROMPT,
        retries=1,
    )
    result = await agent.run(context_text)
    if result.output is None:
        raise RuntimeError("Directory Agent 节点拓展步骤未返回结构化结果")
    model_name = getattr(text_model, "model_name", None) or "unknown"
    return result.output, GenerationMeta(provider="llm", model=str(model_name), is_fallback=False)


async def run_directory_refine(
    db,
    workspace_id: int,
    project: Project,
    context_text: str,
    tree_json: str,
    messages: list[dict],
) -> tuple[ChatRoundResultDraft, GenerationMeta]:
    """运行一轮对话调整，返回回复与可选新树。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            _offline_refine(),
            GenerationMeta(provider="offline", model=None, is_fallback=True),
        )

    convo_text = "\n".join(
        f"{item['role']}：{item['content']}" for item in messages
    )
    prompt = (
        f"{context_text}\n\n当前候选树：\n{tree_json}\n\n最近对话：\n{convo_text}"
    )
    agent = Agent(
        text_model,
        output_type=ChatRoundResultDraft,
        system_prompt=REFINE_SYSTEM_PROMPT,
        retries=1,
    )
    result = await agent.run(prompt)
    if result.output is None:
        raise RuntimeError("Directory Agent 调整步骤未返回结构化结果")
    model_name = getattr(text_model, "model_name", None) or "unknown"
    return result.output, GenerationMeta(provider="llm", model=str(model_name), is_fallback=False)
