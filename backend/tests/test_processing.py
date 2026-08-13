"""处理任务管道测试。"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models import ProcessingTask, Source
from app.models.processing import DONE, FAILED, PROCESSING, WAITING
from app.processing import worker
from app.processing.base import ProcessingProvider


def _register(client: TestClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


def _create_text_source(client: TestClient, text: str) -> dict:
    response = client.post("/api/sources", data={"text": text})
    assert response.status_code == 201
    return response.json()


def _run(coro):
    return asyncio.run(coro)


async def _get_task(source_id: int) -> ProcessingTask:
    async with async_session_factory() as db:
        return (
            await db.execute(
                select(ProcessingTask).where(ProcessingTask.source_id == source_id)
            )
        ).scalar_one()


async def _set_task_status(source_id: int, status: str) -> None:
    async with async_session_factory() as db:
        task = (
            await db.execute(
                select(ProcessingTask).where(ProcessingTask.source_id == source_id)
            )
        ).scalar_one()
        task.status = status
        await db.commit()


def test_trigger_creates_waiting_task(client: TestClient) -> None:
    """触发处理后应创建等待处理任务。"""
    _register(client)
    source = _create_text_source(client, "待处理")
    assert source["status"] == WAITING

    response = client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 200
    task = _run(_get_task(source["id"]))
    assert task.status == WAITING


def test_process_one_task_done(client: TestClient) -> None:
    """Worker 领取后应把任务与 Source 置为已完成。"""
    _register(client)
    source = _create_text_source(client, "正常处理")
    client.post(f"/api/sources/{source['id']}/process")

    handled = _run(worker.process_one_task())

    assert handled is True
    assert _run(_get_task(source["id"])).status == DONE
    assert client.get(f"/api/sources/{source['id']}").json()["status"] == DONE


def test_process_one_task_failed(client: TestClient, monkeypatch) -> None:
    """Provider 失败时应把任务与 Source 置为失败并记录错误。"""
    _register(client)
    source = _create_text_source(client, "会失败")
    client.post(f"/api/sources/{source['id']}/process")

    class FailingProvider(ProcessingProvider):
        provider_name = "failing"

        async def process(self, source: Source) -> None:
            raise RuntimeError("处理失败")

    monkeypatch.setattr(worker, "get_processing_provider", lambda: FailingProvider())

    handled = _run(worker.process_one_task())

    assert handled is True
    task = _run(_get_task(source["id"]))
    assert task.status == FAILED
    assert "处理失败" in (task.error or "")


def test_retry_increments_count(client: TestClient) -> None:
    """失败后重试应回到等待处理并递增重试次数。"""
    _register(client)
    source = _create_text_source(client, "重试")
    client.post(f"/api/sources/{source['id']}/process")
    _run(_set_task_status(source["id"], FAILED))

    response = client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 200
    task = _run(_get_task(source["id"]))
    assert task.status == WAITING
    assert task.retry_count == 1


def test_trigger_conflict_when_processing(client: TestClient) -> None:
    """处理中的任务再次触发应返回 409。"""
    _register(client)
    source = _create_text_source(client, "处理中")
    client.post(f"/api/sources/{source['id']}/process")
    _run(_set_task_status(source["id"], PROCESSING))

    response = client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 409


def test_factory_returns_demo_by_default() -> None:
    """默认处理 Provider 应为 Demo 实现。"""
    from app.processing.demo import DemoProcessingProvider
    from app.processing.factory import get_processing_provider

    assert isinstance(get_processing_provider(), DemoProcessingProvider)


@pytest.mark.asyncio
async def test_unavailable_provider_raises() -> None:
    """未接入的真实 Provider 调用时应明确报错。"""
    from app.processing.factory import UnavailableProcessingProvider

    source = Source(id=1, workspace_id=1, title="x", status=WAITING)
    with pytest.raises(NotImplementedError, match="尚未接入"):
        await UnavailableProcessingProvider().process(source)
