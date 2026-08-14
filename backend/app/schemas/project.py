"""项目与目录节点的请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    """创建项目：新路径默认空目录，template 仅兼容旧客户端。"""

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    template: Literal["decoration", "empty"] | None = None


class ProjectUpdate(BaseModel):
    """修改项目名称与可选说明。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=4000)


ProjectStatus = Literal["active", "paused", "completed", "archived"]


class ProjectStatusUpdate(BaseModel):
    """修改项目生命周期状态。"""

    status: ProjectStatus


class ProjectOut(BaseModel):
    """项目摘要（含节点数）。"""

    id: int
    name: str
    description: str | None
    status: str
    template: str
    node_count: int
    created_at: datetime


class NodeOut(BaseModel):
    """目录树节点（递归结构）。"""

    id: int
    name: str
    description: str | None
    position: int
    entry_count: int = 0
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
    parent_id: int | None = None


class NodeReorderRequest(BaseModel):
    """同级节点排序：parent_id 为空表示根级，ordered_ids 为新的顺序。"""

    parent_id: int | None = None
    ordered_ids: list[int] = Field(default_factory=list)
