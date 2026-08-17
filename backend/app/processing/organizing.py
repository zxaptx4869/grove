"""Organizing 处理 Provider：生成 Extraction 与 Candidate。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.organizing import run_organizing_agent
from app.models import Project, Source
from app.processing.base import ProcessingProvider
from app.services.ai_models import get_settings_row
from app.services.extraction import save_failed_extraction, save_success_extraction
from app.services.routing import route_source


class OrganizingProcessingProvider(ProcessingProvider):
    """调用 Organizing Agent 处理 Source。"""

    provider_name = "organizing"

    async def process(self, db: AsyncSession, source: Source) -> None:
        """解析 Source 并持久化版本化 Extraction 与 Candidate。"""
        loaded = (
            await db.execute(
                select(Source)
                .options(selectinload(Source.attachments), selectinload(Source.project))
                .where(Source.id == source.id)
            )
        ).scalar_one()
        settings_row = await get_settings_row(db, source.workspace_id)
        model = settings_row.text_model
        workspace_projects = (
            await db.execute(
                select(Project).where(
                    Project.workspace_id == source.workspace_id,
                    Project.status != "archived",
                )
            )
        ).scalars().all() if loaded.project_id is None else []
        try:
            draft = await run_organizing_agent(
                db,
                loaded,
                list(loaded.attachments),
                loaded.project,
                workspace_projects,
            )
            await save_success_extraction(
                db,
                loaded,
                draft,
                self.provider_name,
                model,
            )
            title = (draft.source_title or "").strip()
            if title:
                loaded.title = title[:255]
            if loaded.project_id is not None:
                await route_source(db, loaded.id)
        except Exception as exc:  # noqa: BLE001
            await save_failed_extraction(
                db,
                loaded,
                self.provider_name,
                model,
                str(exc),
            )
            raise
