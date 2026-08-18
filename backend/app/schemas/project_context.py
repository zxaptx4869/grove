"""项目上下文请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class EntryRecentOut(BaseModel):
    """知识覆盖摘要中的近期 Entry。"""

    entry_id: int
    title: str
    node_name: str
    updated_at: datetime | None


class EntryTopNodeCoverageOut(BaseModel):
    """按顶级目录节点的 Entry 覆盖数。"""

    node_id: int
    name: str
    count: int


class EntrySummaryOut(BaseModel):
    """已确认 Entry 的确定性知识覆盖摘要。"""

    total: int
    by_type: dict[str, int]
    by_top_node: list[EntryTopNodeCoverageOut]
    recent: list[EntryRecentOut]
    truncated_count: int = 0


class ProjectContextCorrectionsOut(BaseModel):
    """用户对 AI 生成字段的高优先级纠正（部分覆盖）。"""

    project_summary: str | None = None
    current_focus: str | None = None


class ProjectContextOut(BaseModel):
    """项目上下文快照：派生上下文，不是正式知识。"""

    project_id: int
    user_description: str | None
    project_summary: str | None
    current_focus: str | None
    directory_topics: list[str] = []
    lifecycle_status: str
    generated_at: datetime | None
    version: int
    last_update_reason: str | None
    entries_summary: EntrySummaryOut | None
    recent_themes: list[str] = []
    status: str
    error: str | None
    corrections: ProjectContextCorrectionsOut


class ProjectContextCorrectionUpdate(BaseModel):
    """纠正 AI 生成字段；字段缺失表示不修改，传 null 表示清除纠正。"""

    project_summary: str | None = Field(default=None, max_length=4000)
    current_focus: str | None = Field(default=None, max_length=4000)
