"""项目与目录节点的请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """创建项目：模板可选装修（decoration）或空目录（empty）。"""

    name: str = Field(min_length=1, max_length=64)
    template: Literal["decoration", "empty"] = "empty"


class ProjectUpdate(BaseModel):
    """重命名项目。"""

    name: str = Field(min_length=1, max_length=64)


class ProjectOut(BaseModel):
    """项目摘要（含节点数）。"""

    id: int
    name: str
    template: str
    node_count: int
    created_at: datetime


class NodeOut(BaseModel):
    """目录树节点（递归结构）。"""

    id: int
    name: str
    description: str | None
    position: int
    children: list["NodeOut"] = []


NodeOut.model_rebuild()


class NodeCreate(BaseModel):
    """创建节点：不传 parent_id 时为根节点。"""

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: int | None = None


class NodeUpdate(BaseModel):
    """更新节点名称/描述。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)


class NodeReorderRequest(BaseModel):
    """同级节点排序：parent_id 为空表示根级，ordered_ids 为新的顺序。"""

    parent_id: int | None = None
    ordered_ids: list[int] = Field(default_factory=list)
