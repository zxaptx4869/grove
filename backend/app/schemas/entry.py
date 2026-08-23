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


class EntryVersionOut(BaseModel):
    """Entry 版本快照。"""

    id: int
    version_number: int
    title: str
    content: str
    main_type: str
    info_nature: str | None
    applicable_condition: str | None
    note: str | None
    node_id: int
    node_name: str
    change_type: str
    change_summary: str | None
    created_at: datetime


class RestoreRequest(BaseModel):
    """恢复到指定 Entry 版本。"""

    version_id: int


class ArchiveCandidateRequest(BaseModel):
    """采纳并归档候选。"""

    node_id: int


class NewNodeArchiveRequest(BaseModel):
    """创建或复用节点并归档候选。"""

    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)


class AddEvidenceRequest(BaseModel):
    """把候选来源证据补充到已有 Entry。"""

    entry_id: int


class ApplyRevisionRequest(BaseModel):
    """把候选修订草稿应用到已有 Entry。"""

    entry_id: int
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    change_summary: str | None = Field(default=None, max_length=2000)


class RevisionSuggestionRequest(BaseModel):
    """发起 AI 修订建议。"""

    instruction: str | None = Field(default=None, max_length=2000)


class RevisionChatMessage(BaseModel):
    """一次修订对话的单条消息。"""

    role: Literal["user", "assistant"]
    content: str


class RevisionDraftPayload(BaseModel):
    """AI 修订建议的候选草稿。"""

    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    change_summary: str = ""
    reason: str = ""


class RevisionRefineRequest(BaseModel):
    """继续对话调整修订草稿。"""

    instruction: str = Field(min_length=1, max_length=2000)
    messages: list[RevisionChatMessage] = []
    draft: RevisionDraftPayload | None = None


class ApplyRevisionSuggestionRequest(BaseModel):
    """应用确认后的 AI 修订草稿。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    change_summary: str | None = Field(default=None, max_length=2000)


class RevisionSuggestionOut(BaseModel):
    """AI 修订建议生成/调整结果。"""

    reply_text: str
    draft: RevisionDraftPayload | None = None
    provider: str | None
    model: str | None
    is_fallback: bool
    error: str | None
