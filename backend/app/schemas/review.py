"""确认台请求/响应模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CandidateUpdate(BaseModel):
    """编辑候选字段；字段缺失表示不修改，传 null 表示清空。"""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=8000)
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)


class CandidateDecisionUpdate(BaseModel):
    """单条候选决策。"""

    status: Literal["pending", "confirmed", "rejected"]


class BatchCandidateDecisionRequest(BaseModel):
    """Source 内批量决策。"""

    candidate_ids: list[int] = Field(min_length=1)
    status: Literal["confirmed", "rejected"]


class ReviewSourceOut(BaseModel):
    """项目内待审 Source 摘要。"""

    id: int
    title: str
    note: str | None
    status: str
    review_status: str
    candidate_count: int
    created_at: datetime
