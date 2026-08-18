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


class DraftOut(BaseModel):
    """目录草稿响应。"""

    id: int
    project_id: int
    status: str
    next_action: str
    clarify_batches: int
    clarify: list[ClarifyQuestionOut] = []
    nodes: list[DraftNodeOut] = []
    provider: str | None
    model: str | None
    is_fallback: bool
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class DraftCreateRequest(BaseModel):
    """创建草稿的可选背景说明。"""

    background: str | None = Field(default=None, max_length=2000)


class ClarifySubmitRequest(BaseModel):
    """一次提交全部澄清答案。"""

    answers: dict[str, str | list[str]] = Field(default_factory=dict)


class DraftNodeInput(BaseModel):
    """用户编辑草稿时提交的节点（嵌套树）。"""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    children: list["DraftNodeInput"] = []


DraftNodeInput.model_rebuild()


class DraftNodesUpdateRequest(BaseModel):
    """全量替换草稿节点树。"""

    nodes: list[DraftNodeInput] = []
