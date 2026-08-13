"""项目上下文快照测试。"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select, update

from app.context.base import ProjectContextGenerator
from app.context.worker import process_due_context
from app.db.session import async_session_factory
from app.main import create_app
from app.models import ProjectContext
from app.models.project_context import PENDING, READY
from app.services import project_context as service


@pytest.fixture
async def client():
    """异步 API 客户端，Worker 已在 conftest 关闭。"""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


async def _register(client: httpx.AsyncClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


async def _create_project(
    client: httpx.AsyncClient,
    name: str = "项目",
    description: str = "项目说明",
) -> dict:
    response = await client.post(
        "/api/projects",
        json={"name": name, "description": description},
    )
    assert response.status_code == 201
    return response.json()


async def _create_node(
    client: httpx.AsyncClient,
    project_id: int,
    name: str,
    parent_id: int | None = None,
) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": parent_id},
    )
    assert response.status_code == 201
    return response.json()


async def _context_row(project_id: int) -> ProjectContext:
    async with async_session_factory() as db:
        return (
            await db.execute(
                select(ProjectContext).where(ProjectContext.project_id == project_id)
            )
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_get_context_creates_pending_once(client: httpx.AsyncClient) -> None:
    """首次读取上下文应惰性建行，且不会产生第二份。"""
    await _register(client)
    project = await _create_project(client, description="初始说明")

    first = await client.get(f"/api/projects/{project['id']}/context")
    second = await client.get(f"/api/projects/{project['id']}/context")

    assert first.status_code == 200
    assert first.json()["status"] == PENDING
    assert first.json()["user_description"] == "初始说明"
    assert second.status_code == 200
    assert first.json()["project_id"] == second.json()["project_id"]
    assert (await _context_row(project["id"])).status == PENDING


@pytest.mark.asyncio
async def test_get_context_lazily_persists_missing_row(
    client: httpx.AsyncClient,
) -> None:
    """旧项目没有上下文行时，读取应惰性建行并持久化。"""
    await _register(client)
    project = await _create_project(client)
    async with async_session_factory() as db:
        await db.execute(delete(ProjectContext).where(ProjectContext.project_id == project["id"]))
        await db.commit()

    response = await client.get(f"/api/projects/{project['id']}/context")

    assert response.status_code == 200
    assert response.json()["status"] == PENDING
    assert (await _context_row(project["id"])) is not None


@pytest.mark.asyncio
async def test_context_isolation_between_users(client: httpx.AsyncClient) -> None:
    """跨用户项目上下文不可见。"""
    await _register(client)
    project = await _create_project(client)

    other_transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=other_transport, base_url="http://test"
    ) as other:
        await _register(other)
        response = await other.get(f"/api/projects/{project['id']}/context")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_manual_refresh_generates_initial_summary(
    client: httpx.AsyncClient,
) -> None:
    """手动重新生成应基于项目说明与正式目录生成初始概要。"""
    await _register(client)
    project = await _create_project(client, description="整理新家装修")
    root = await _create_node(client, project["id"], "装修准备")
    await _create_node(client, project["id"], "需求确认", parent_id=root["id"])

    response = await client.post(f"/api/projects/{project['id']}/context/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == READY
    assert "整理新家装修" in data["project_summary"]
    assert data["directory_topics"] == ["装修准备"]
    assert data["lifecycle_status"] == "active"
    assert data["generated_at"] is not None


@pytest.mark.asyncio
async def test_directory_change_schedules_debounced_refresh(
    client: httpx.AsyncClient,
) -> None:
    """目录变化后应设置 refresh_due_at 且只保留一份上下文。"""
    await _register(client)
    project = await _create_project(client)
    before = await _context_row(project["id"])
    assert before is not None

    await _create_node(client, project["id"], "第一个节点")
    after_first = await _context_row(project["id"])
    first_due = after_first.refresh_due_at
    assert first_due is not None

    await _create_node(client, project["id"], "第二个节点")
    after_second = await _context_row(project["id"])
    assert after_second.id == after_first.id
    assert after_second.refresh_due_at is not None


@pytest.mark.asyncio
async def test_failure_fallback_keeps_previous_snapshot(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """生成失败时应保留上一份有效快照并记录错误。"""
    await _register(client)
    project = await _create_project(client, description="装修")
    await _create_node(client, project["id"], "节点")
    ready = await client.post(f"/api/projects/{project['id']}/context/refresh")
    assert ready.json()["status"] == READY
    previous_summary = ready.json()["project_summary"]

    class FailingGenerator(ProjectContextGenerator):
        provider_name = "failing"

        async def generate(self, project, nodes, corrections=None):
            raise RuntimeError("生成失败")

    monkeypatch.setattr(service, "get_project_context_generator", lambda: FailingGenerator())
    response = await client.post(f"/api/projects/{project['id']}/context/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == READY
    assert data["project_summary"] == previous_summary
    assert "生成失败" in (data["error"] or "")


@pytest.mark.asyncio
async def test_failure_without_snapshot_marks_failed(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """尚无有效快照时生成失败应标记 failed 并保留错误。"""
    await _register(client)
    project = await _create_project(client)

    class FailingGenerator(ProjectContextGenerator):
        provider_name = "failing"

        async def generate(self, project, nodes, corrections=None):
            raise RuntimeError("首次生成失败")

    monkeypatch.setattr(service, "get_project_context_generator", lambda: FailingGenerator())
    response = await client.post(f"/api/projects/{project['id']}/context/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["project_summary"] is None
    assert "首次生成失败" in (data["error"] or "")


@pytest.mark.asyncio
async def test_correction_is_retained_as_high_priority(
    client: httpx.AsyncClient,
) -> None:
    """纠正内容应持久化，并在重新生成后继续作为有效内容。"""
    await _register(client)
    project = await _create_project(client, description="装修")
    await _create_node(client, project["id"], "节点")

    corrected = await client.patch(
        f"/api/projects/{project['id']}/context",
        json={"project_summary": "我的项目概要", "current_focus": "优先看预算"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["project_summary"] == "我的项目概要"
    assert corrected.json()["current_focus"] == "优先看预算"
    assert corrected.json()["corrections"]["project_summary"] == "我的项目概要"

    regenerated = await client.post(f"/api/projects/{project['id']}/context/refresh")
    assert regenerated.status_code == 200
    assert regenerated.json()["project_summary"] == "我的项目概要"
    assert regenerated.json()["current_focus"] == "优先看预算"


@pytest.mark.asyncio
async def test_context_worker_processes_due_refresh() -> None:
    """Worker 应领取到期的刷新并生成上下文。"""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await _register(client)
        project = await _create_project(client, description="后台刷新")
        await _create_node(client, project["id"], "节点")

    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(ProjectContext).where(ProjectContext.project_id == project["id"])
            )
        ).scalar_one()
        row.refresh_due_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.execute(
            update(ProjectContext)
            .where(ProjectContext.project_id != project["id"])
            .values(refresh_due_at=None)
        )
        await db.commit()

    assert await process_due_context() is True
    row = await _context_row(project["id"])
    assert row.status == READY
    assert "后台刷新" in (row.project_summary or "")


def test_factory_returns_demo_by_default() -> None:
    """默认项目上下文生成器应为 Demo 实现。"""
    from app.context.demo import DemoProjectContextGenerator
    from app.context.factory import get_project_context_generator

    assert isinstance(get_project_context_generator(), DemoProjectContextGenerator)


@pytest.mark.asyncio
async def test_unavailable_provider_raises() -> None:
    """未接入的真实生成器调用时应明确报错。"""
    from app.context.factory import UnavailableProjectContextGenerator
    from app.models import Project

    project = Project(id=1, workspace_id=1, name="x", status="active")
    with pytest.raises(NotImplementedError, match="尚未接入"):
        await UnavailableProjectContextGenerator().generate(project, [])
