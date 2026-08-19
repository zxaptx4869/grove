"""目录起草请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class ClarifyQuestionOut(BaseModel):
    """一道澄清问题（选项 + 是否多选）。"""

    id: str
    text: str
    options: list[str] = []
    multiple: bool = False


class DraftNodeOut(BaseModel):
    """草稿节点（扁平，parent_id 组成树）。"""

    id: int
    parent_id: int | None
    name: str
    description: str | None
    position: int
    selected: bool


class DraftDiffNodeOut(BaseModel):
    """节点拓展差异快照：新增 / 保留 / 建议移除（递归）。"""

    kind: str
    node_id: int | None
    real_node_id: int | None
    name: str
    description: str | None
    blocked: bool = False
    blocker_count: int = 0
    children: list["DraftDiffNodeOut"] = []


DraftDiffNodeOut.model_rebuild()


class DraftOut(BaseModel):
    """目录草稿响应。"""

    id: int
    project_id: int
    kind: str = "draft"
    target_node_id: int | None = None
    status: str
    next_action: str
    clarify_batches: int
    clarify: list[ClarifyQuestionOut] = []
    nodes: list[DraftNodeOut] = []
    diff: list[DraftDiffNodeOut] = []
    messages: list["DraftMessageOut"] = []
    provider: str | None
    model: str | None
    is_fallback: bool
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class DraftMessageOut(BaseModel):
    """草稿会话消息。"""

    id: int
    role: str
    content: str
    created_at: datetime


DraftOut.model_rebuild()


class DraftCreateRequest(BaseModel):
    """创建草稿的可选背景说明。"""

    background: str | None = Field(default=None, max_length=2000)


class ExpandRequest(BaseModel):
    """发起节点拓展的请求体。"""

    node_id: int


class ClarifySubmitRequest(BaseModel):
    """一次提交全部澄清答案。"""

    answers: dict[str, str | list[str]] = Field(default_factory=dict)


class DraftNodeInput(BaseModel):
    """用户编辑草稿时提交的节点（嵌套树）。"""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    selected: bool = True
    children: list["DraftNodeInput"] = []


DraftNodeInput.model_rebuild()


class DraftNodesUpdateRequest(BaseModel):
    """全量替换草稿节点树。"""

    nodes: list[DraftNodeInput] = []


class DraftMessageSubmitRequest(BaseModel):
    """发送一条对话调整消息。"""

    content: str = Field(min_length=1, max_length=2000)
