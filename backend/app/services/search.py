"""Entry 关键词搜索服务。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Entry, EntrySourceEvidence, Node, Project, Source
from app.services.entry import entry_eager_options


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，让用户输入按字面匹配。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_entries(
    db: AsyncSession,
    workspace_id: int,
    keyword: str,
    project_id: int | None = None,
) -> list[Entry]:
    """在当前 Workspace（或指定项目）内按关键词搜索已确认 Entry。"""
    query = keyword.strip()
    if not query:
        return []

    pattern = f"%{_escape_like(query)}%"
    escape = "\\"
    source_title_entries = (
        select(EntrySourceEvidence.entry_id)
        .join(Source, EntrySourceEvidence.source_id == Source.id)
        .where(Source.title.ilike(pattern, escape=escape))
    )

    stmt = (
        select(Entry)
        .join(Node, Entry.node_id == Node.id)
        .join(Project, Entry.project_id == Project.id)
        .options(*entry_eager_options(), selectinload(Entry.project))
        .where(Project.workspace_id == workspace_id)
        .where(
            or_(
                Entry.title.ilike(pattern, escape=escape),
                Entry.content.ilike(pattern, escape=escape),
                Node.name.ilike(pattern, escape=escape),
                Node.description.ilike(pattern, escape=escape),
                Entry.id.in_(source_title_entries),
            )
        )
        .order_by(Entry.created_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(Entry.project_id == project_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())
