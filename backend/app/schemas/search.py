"""搜索响应模型。"""

from app.schemas.entry import EntryOut


class SearchEntryOut(EntryOut):
    """搜索结果：在 Entry 基础上补充所属项目名。"""

    project_name: str
