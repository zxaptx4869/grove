"""Reader 问答与保存请求/响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class ReaderAskRequest(BaseModel):
    """一次问答请求。"""

    message: str = Field(min_length=1, max_length=2000)
    scope: Literal["project", "node"] = "project"
    node_id: int | None = None


class ReaderCitationOut(BaseModel):
    """回答引用：Entry 与 Source 证据。"""

    entry_id: int
    entry_title: str
    source_id: int
    source_title: str
    quote: str


class ReaderConflictOut(BaseModel):
    """矛盾 Entry 展示。"""

    entry_id_a: int
    entry_title_a: str = ""
    entry_id_b: int
    entry_title_b: str = ""
    summary: str


class ReaderAnswerOut(BaseModel):
    """一次问答的结构化响应。"""

    answer: str
    citations: list[ReaderCitationOut] = []
    insufficient: bool = False
    insufficient_note: str | None = None
    conflicts: list[ReaderConflictOut] = []
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    save_recommended: bool = False
    provider: str | None = None
    model: str | None = None
    is_fallback: bool = False
    error: str | None = None


class ReaderCitationIn(BaseModel):
    """保存回答时的引用输入。"""

    entry_id: int
    source_id: int
    quote: str = ""


class ReaderSaveRequest(BaseModel):
    """把回答保存为候选的请求。"""

    question: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=8000)
    citations: list[ReaderCitationIn] = []
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
