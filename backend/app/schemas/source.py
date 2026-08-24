"""Source 与 Attachment 的请求/响应模型。"""

from datetime import datetime

from pydantic import BaseModel, Field


class AttachmentOut(BaseModel):
    """附件摘要（图片返回文件信息，文字返回正文）。"""

    id: int
    kind: str
    position: int
    mime_type: str | None
    file_name: str | None
    text_content: str | None
    ocr_text: str | None


class SourceOut(BaseModel):
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
    project_locked: bool = False
    evidence_entry_count: int = 0


class SourcePageOut(BaseModel):
    """全量来源历史查询的分页结果。"""

    items: list[SourceOut]
    total: int
    limit: int
    offset: int


class SourceUpdate(BaseModel):
    """修改 Source 的说明或项目归属。"""

    note: str | None = Field(default=None, max_length=4000)
    project_id: int | None = None
