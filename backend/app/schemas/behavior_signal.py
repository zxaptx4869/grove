"""行为信号只读查询的响应模型。"""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class BehaviorSignalOut(BaseModel):
    """单条行为信号（只读）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_type: str
    recommended: dict | None
    final: dict | None
    accepted: bool | None
    detail: str | None
    user_id: int | None
    project_id: int | None
    source_id: int | None
    candidate_id: int | None
    created_at: datetime

    @field_validator("recommended", "final", mode="before")
    @classmethod
    def _parse_json_text(cls, value: object) -> object:
        """把库内 JSON 文本解析为 dict 返回给前端。"""
        if isinstance(value, str) and value:
            return json.loads(value)
        return value
