"""Source 与 Attachment 的请求/响应模型。"""

from datetime import datetime

from pydantic import Field

from app.schemas.base import ApiModel


class AttachmentOut(ApiModel):
    """附件摘要（图片返回文件信息，文字返回正文）。"""

    id: int
    kind: str
    position: int
    mime_type: str | None
    file_name: str | None
    text_content: str | None
    ocr_text: str | None


class SourceOut(ApiModel):
    """Source 摘要（含附件）。"""

    id: int
    title: str
    note: str | None
    project_id: int | None
    status: str
    recommended_project_id: int | None
    project_recommendation_reason: str | None
    created_at: datetime
    updated_at: datetime
    attachments: list[AttachmentOut] = []
    failure_reason: str | None = None
    retry_count: int = 0
    # 是否存在处理任务：等待处理但没有任务表示「处理未启动」，只能靠任务存在性判断
    has_processing_task: bool = False
    project_locked: bool = False
    evidence_entry_count: int = 0
    pending_candidate_count: int = 0
    candidate_count: int = 0


class SourcePageOut(ApiModel):
    """全量来源历史查询的分页结果。"""

    items: list[SourceOut]
    total: int
    limit: int
    offset: int


class SourceUpdate(ApiModel):
    """修改 Source 的说明或项目归属。"""

    note: str | None = Field(default=None, max_length=4000)
    project_id: int | None = None
