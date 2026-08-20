"""语义检索响应模型。"""

from app.schemas.entry import EntryOut


class SemanticEntryOut(EntryOut):
    """语义检索结果：在 Entry 基础上补充所属项目名、相关理由与降级标记。"""

    project_name: str
    reason: str = ""
    provider: str | None = None
    model: str | None = None
    is_fallback: bool = False
