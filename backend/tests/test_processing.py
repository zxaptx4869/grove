"""处理任务管道测试。"""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.main import create_app
from app.models import ProcessingTask, Source
from app.models.processing import DONE, FAILED, PROCESSING, WAITING
from app.processing import worker
from app.processing.base import ProcessingProvider


@pytest.fixture
async def client():
    async with async_session_factory() as db:
        await db.execute(delete(ProcessingTask))
        await db.commit()
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


async def _create_text_source(client: httpx.AsyncClient, text: str) -> dict:
    response = await client.post("/api/sources", data={"text": text})
    assert response.status_code == 201
    return response.json()


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


@pytest.mark.asyncio
async def test_trigger_creates_waiting_task(client: httpx.AsyncClient) -> None:
    """触发处理后应创建等待处理任务。"""
    await _register(client)
    source = await _create_text_source(client, "待处理")
    assert source["status"] == WAITING

    response = await client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 200
    assert (await _get_task(source["id"])).status == WAITING


@pytest.mark.asyncio
async def test_process_one_task_done(client: httpx.AsyncClient) -> None:
    """Worker 领取后应把任务与 Source 置为已完成。"""
    await _register(client)
    source = await _create_text_source(client, "正常处理")
    await client.post(f"/api/sources/{source['id']}/process")

    handled = await worker.process_one_task()

    assert handled is True
    assert (await _get_task(source["id"])).status == DONE
    assert (await client.get(f"/api/sources/{source['id']}")).json()["status"] == DONE


@pytest.mark.asyncio
async def test_process_one_task_failed(client: httpx.AsyncClient, monkeypatch) -> None:
    """Provider 失败时应把任务与 Source 置为失败并记录错误。"""
    await _register(client)
    source = await _create_text_source(client, "会失败")
    await client.post(f"/api/sources/{source['id']}/process")

    class FailingProvider(ProcessingProvider):
        provider_name = "failing"

        async def process(self, db, source: Source) -> None:
            raise RuntimeError("处理失败")

    monkeypatch.setattr(worker, "get_processing_provider", lambda: FailingProvider())

    handled = await worker.process_one_task()

    assert handled is True
    task = await _get_task(source["id"])
    assert task.status == FAILED
    assert "处理失败" in (task.error or "")


@pytest.mark.asyncio
async def test_retry_increments_count(client: httpx.AsyncClient) -> None:
    """失败后重试应回到等待处理并递增重试次数。"""
    await _register(client)
    source = await _create_text_source(client, "重试")
    await client.post(f"/api/sources/{source['id']}/process")
    await _set_task_status(source["id"], FAILED)

    response = await client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 200
    task = await _get_task(source["id"])
    assert task.status == WAITING
    assert task.retry_count == 1


@pytest.mark.asyncio
async def test_trigger_conflict_when_processing(client: httpx.AsyncClient) -> None:
    """处理中的任务再次触发应返回 409。"""
    await _register(client)
    source = await _create_text_source(client, "处理中")
    await client.post(f"/api/sources/{source['id']}/process")
    await _set_task_status(source["id"], PROCESSING)

    response = await client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_trigger_is_idempotent(client: httpx.AsyncClient) -> None:
    """同一来源并发触发处理时不能因唯一约束冲突报 500（真机连点重试会走到这里）。"""
    await _register(client)
    source = await _create_text_source(client, "并发触发")

    responses = await asyncio.gather(
        client.post(f"/api/sources/{source['id']}/process"),
        client.post(f"/api/sources/{source['id']}/process"),
        client.post(f"/api/sources/{source['id']}/process"),
    )

    assert [response.status_code for response in responses] == [200, 200, 200]
    task = await _get_task(source["id"])
    assert task.status == WAITING


@pytest.mark.asyncio
async def test_trigger_survives_concurrent_insert(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读到「无任务」后插入撞唯一索引时必须幂等返回，而不是 500。

    用 monkeypatch 精确模拟并发窗口：本次请求读到 None，但任务已被另一请求插入。
    """
    from app.api import sources as sources_module

    await _register(client)
    source = await _create_text_source(client, "并发插入")
    await client.post(f"/api/sources/{source['id']}/process")

    real_find = sources_module._find_processing_task
    calls = {"count": 0}

    async def fake_find(db, source_id):
        calls["count"] += 1
        return None if calls["count"] == 1 else await real_find(db, source_id)

    monkeypatch.setattr(sources_module, "_find_processing_task", fake_find)

    real_has = sources_module._has_processing_task
    fallback = {"count": 0}

    async def fake_has(db, source_id):
        fallback["count"] += 1
        return await real_has(db, source_id)

    monkeypatch.setattr(sources_module, "_has_processing_task", fake_has)

    response = await client.post(f"/api/sources/{source['id']}/process")

    assert response.status_code == 200
    assert (calls["count"], fallback["count"]) == (1, 1)


def test_factory_returns_organizing_by_default() -> None:
    """默认处理 Provider 应为 Organizing 实现。"""
    from app.processing.factory import get_processing_provider
    from app.processing.organizing import OrganizingProcessingProvider

    assert isinstance(get_processing_provider(), OrganizingProcessingProvider)


@pytest.mark.asyncio
async def test_unavailable_provider_raises() -> None:
    """未接入的真实 Provider 调用时应明确报错。"""
    from app.processing.factory import UnavailableProcessingProvider

    source = Source(id=1, workspace_id=1, title="x", status=WAITING)
    with pytest.raises(NotImplementedError, match="尚未接入"):
        await UnavailableProcessingProvider().process(None, source)


async def _set_task_failure(source_id: int, error: str, retry_count: int) -> None:
    """把来源的任务标记为失败并写入错误与重试次数。"""
    async with async_session_factory() as db:
        task = (
            await db.execute(
                select(ProcessingTask).where(ProcessingTask.source_id == source_id)
            )
        ).scalar_one()
        task.status = FAILED
        task.step = "extract"
        task.error = error
        task.retry_count = retry_count
        await db.commit()


@pytest.mark.asyncio
async def test_source_out_exposes_failure_when_failed(client: httpx.AsyncClient) -> None:
    """任务失败时列表、历史查询与详情给出一致的失败文案与重试次数。"""
    await _register(client)
    source = await _create_text_source(client, "会失败的来源")
    await client.post(f"/api/sources/{source['id']}/process")
    await _set_task_failure(source["id"], "模型调用超时", 2)

    detail = (await client.get(f"/api/sources/{source['id']}")).json()
    listed = next(
        item for item in (await client.get("/api/sources")).json() if item["id"] == source["id"]
    )
    queried = next(
        item
        for item in (await client.get("/api/sources/query")).json()["items"]
        if item["id"] == source["id"]
    )

    for item in (detail, listed, queried):
        assert item["failure_reason"] == "模型调用超时"
        assert item["retry_count"] == 2


@pytest.mark.asyncio
async def test_source_out_failure_cleared_after_retrigger(client: httpx.AsyncClient) -> None:
    """无任务、等待处理与重试后不得展示历史错误。"""
    await _register(client)
    no_task = await _create_text_source(client, "没有任务")
    waiting = await _create_text_source(client, "等待处理")
    await client.post(f"/api/sources/{waiting['id']}/process")
    retried = await _create_text_source(client, "重试后恢复等待")
    await client.post(f"/api/sources/{retried['id']}/process")
    await _set_task_failure(retried["id"], "上一次失败", 1)
    await client.post(f"/api/sources/{retried['id']}/process")

    items = {item["id"]: item for item in (await client.get("/api/sources")).json()}

    assert items[no_task["id"]]["failure_reason"] is None
    assert items[no_task["id"]]["retry_count"] == 0
    assert items[waiting["id"]]["failure_reason"] is None
    assert items[retried["id"]]["failure_reason"] is None
    # 重试把错误清空并让重试次数加一，字段给出任务当前值而不是历史错误
    assert items[retried["id"]]["retry_count"] == 2


@pytest.mark.asyncio
async def test_source_list_task_info_query_count_bounded(client: httpx.AsyncClient) -> None:
    """列表批量读取任务失败信息，查询次数不随来源条数增长。"""
    import sqlalchemy as sa

    from app.db.session import engine

    await _register(client)
    for index in range(5):
        source = await _create_text_source(client, f"来源 {index}")
        await client.post(f"/api/sources/{source['id']}/process")
        await _set_task_failure(source["id"], f"错误 {index}", index)

    counts: list[int] = []

    def _count_task_query(conn, cursor, statement, parameters, context, executemany):
        if "processing_tasks" in str(statement):
            counts.append(1)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", _count_task_query)
    try:
        listed = (await client.get("/api/sources")).json()
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", _count_task_query)

    assert len(listed) == 5
    assert all(item["failure_reason"] for item in listed)
    # 批量读取：5 条来源只发起一次 processing_tasks 查询
    assert len(counts) == 1
