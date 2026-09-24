"""Organizing 处理 Provider：生成 Extraction 与 Candidate。"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.organizing import run_organizing_agent
from app.models import Project, Source
from app.processing.base import ProcessingProvider
from app.services.ai_models import get_settings_row
from app.services.entry_relation import route_relations
from app.services.extraction import save_failed_extraction, save_success_extraction
from app.services.routing import route_source

logger = logging.getLogger(__name__)


async def _end_write_transaction(db: AsyncSession) -> None:
    """结束当前写事务：写库可以持写锁，模型调用期间绝对不可以。

    SQLite 下写事务会持写锁到提交为止，若在持锁期间等待模型返回，并发采集的
    提交会等到超时并返回 500「database is locked」。因此每次进入模型调用前都
    先把已产生的写入落库（含 get_settings_row 的惰性建行）。
    """
    await db.commit()


class OrganizingProcessingProvider(ProcessingProvider):
    """调用 Organizing Agent 处理 Source。"""

    provider_name = "organizing"

    async def process(self, db: AsyncSession, source: Source) -> None:
        """解析 Source 并持久化版本化 Extraction 与 Candidate。

        写库与模型调用必须分段提交：SQLite 下写事务会持写锁到提交为止，
        若在持锁期间等待模型返回，并发采集的提交会等到超时并返回 500
        「database is locked」。因此每段写入结束就先提交，再进入下一次模型调用。
        """
        loaded = (
            await db.execute(
                select(Source)
                .options(selectinload(Source.attachments), selectinload(Source.project))
                .where(Source.id == source.id)
            )
        ).scalar_one()
        settings_row = await get_settings_row(db, source.workspace_id)
        model = settings_row.text_model
        workspace_projects: list[Project] = []
        if loaded.project_id is None:
            workspace_projects = (
                await db.execute(
                    select(Project).where(
                        Project.workspace_id == source.workspace_id,
                        Project.status != "archived",
                    )
                )
            ).scalars().all()
        try:
            await _end_write_transaction(db)
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
            if loaded.project_id is None and draft.recommended_project_id is not None:
                valid_project_ids = {project.id for project in workspace_projects}
                if draft.recommended_project_id in valid_project_ids:
                    loaded.project_id = draft.recommended_project_id
            # 先落库解析结果再进路由：路由里还有两次模型调用，不能持写锁等模型
            await _end_write_transaction(db)
        except Exception as exc:  # noqa: BLE001
            await save_failed_extraction(
                db,
                loaded,
                self.provider_name,
                model,
                str(exc),
            )
            raise

        if loaded.project_id is not None:
            try:
                await route_source(db, loaded.id)
                await _end_write_transaction(db)
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("路由来源失败：%s", loaded.id)
            try:
                await route_relations(db, loaded.id)
                await _end_write_transaction(db)
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("关系判断来源失败：%s", loaded.id)
