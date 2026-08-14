"""Entry 请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EntryEvidenceOut(BaseModel):
    """Entry 来源证据。"""

    id: int
    source_id: int
    attachment_id: int | None
    quote: str | None
    source_title: str


class EntryOut(BaseModel):
    """正式知识。"""

    id: int
    project_id: int
    node_id: int
    node_name: str
    title: str
    content: str
    main_type: str
    info_nature: str | None
    applicable_condition: str | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    evidences: list[EntryEvidenceOut] = []


class EntryUpdate(BaseModel):
    """编辑 Entry 字段；字段缺失表示不修改。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    node_id: int | None = None


class ArchiveCandidateRequest(BaseModel):
    """采纳并归档候选。"""

    node_id: int
