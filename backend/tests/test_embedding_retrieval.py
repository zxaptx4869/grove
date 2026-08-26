"""embedding 检索增强：编码降级、向量存储、阈值规则与配置 API。"""

import uuid

import httpx
import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.embedding_worker import backfill_missing_embedding_rows
from app.main import create_app
from app.models import Candidate, Entry, EntryEmbedding, Node, Project, Source, Workspace
from app.models.entry_embedding import EMBEDDING_PENDING, EMBEDDING_READY
from app.processing import worker
from app.schemas.ai_settings import ConnectionTestOut
from app.services.ai_models import get_settings_row
from app.services.embedding import _demo_vector, encode_text
from app.services.entry_relation import route_relations
from app.services.secret_store import get_secret_store, secret_key
from app.services.vector_store import cosine_similarity, deserialize_vector, serialize_vector


@pytest.fixture
async def client():
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


async def _create_project(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _create_source(client: httpx.AsyncClient, project_id: int, text: str) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": text, "project_id": str(project_id)},
    )
    assert response.status_code == 201
    return response.json()


async def _process(client: httpx.AsyncClient, source_id: int) -> None:
    response = await client.post(f"/api/sources/{source_id}/process")
    assert response.status_code == 200
    assert await worker.process_one_task() is True


async def _candidates(client: httpx.AsyncClient, source_id: int) -> list[dict]:
    response = await client.get(f"/api/sources/{source_id}/candidates")
    assert response.status_code == 200
    return response.json()


async def _archive_first(
    client: httpx.AsyncClient,
    node_id: int,
    source_id: int,
) -> dict:
    candidate = (await _candidates(client, source_id))[0]
    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


def test_demo_vector_is_deterministic() -> None:
    """离线 demo embedding 相同输入相同输出，不同输入可区分。"""
    first = _demo_vector("地漏防臭小技巧")
    second = _demo_vector("地漏防臭小技巧")
    assert first == second
    assert len(first) == 256
    assert _demo_vector("地漏防臭小技巧") != _demo_vector("瓷砖美缝怎么做")


def test_vector_store_roundtrip_and_cosine() -> None:
    """向量序列化往返与余弦相似度计算。"""
    vector = [1.0, 0.0, 0.0]
    assert deserialize_vector(serialize_vector(vector), 3) == vector
    assert deserialize_vector(b"", 3) == []
    assert deserialize_vector(b"12345678", 3) == []
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], [0.0, 1.0]) == 0.0


@pytest.mark.asyncio
async def test_backfill_creates_missing_rows() -> None:
    """启动回填应为没有向量记录的 Entry 创建待重建行。"""
    async with async_session_factory() as db:
        workspace = Workspace(name="测试空间")
        db.add(workspace)
        await db.flush()
        project = Project(name="测试项目", workspace_id=workspace.id)
        db.add(project)
        await db.flush()
        node = Node(name="根", project_id=project.id, position=0)
        db.add(node)
        await db.flush()
        db.add(
            Entry(
                project_id=project.id,
                node_id=node.id,
                title="旧知识",
                content="内容",
                main_type="knowledge",
            )
        )
        await db.flush()

        created = await backfill_missing_embedding_rows(db)

        assert created == 1
        row = (
            await db.execute(
                select(EntryEmbedding).where(EntryEmbedding.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert row.status == EMBEDDING_PENDING
        assert row.workspace_id == workspace.id
        assert row.project_id == project.id
        assert row.model == "doubao-embedding-vision-251215"
        # 只清理本次测试数据，避免污染共享测试库
        await db.execute(
            delete(EntryEmbedding).where(EntryEmbedding.workspace_id == workspace.id)
        )
        await db.execute(delete(Entry).where(Entry.project_id == project.id))
        await db.commit()


@pytest.mark.asyncio
async def test_backfill_marks_stale_model_pending() -> None:
    """旧模型向量在回填时被标记为待重建，避免混用向量空间。"""
    async with async_session_factory() as db:
        workspace = Workspace(name="测试空间")
        db.add(workspace)
        await db.flush()
        project = Project(name="测试项目", workspace_id=workspace.id)
        db.add(project)
        await db.flush()
        node = Node(name="根", project_id=project.id, position=0)
        db.add(node)
        await db.flush()
        entry = Entry(
            project_id=project.id,
            node_id=node.id,
            title="旧知识",
            content="内容",
            main_type="knowledge",
        )
        db.add(entry)
        await db.flush()
        db.add(
            EntryEmbedding(
                workspace_id=workspace.id,
                project_id=project.id,
                entry_id=entry.id,
                model="old-model",
                dimension=1,
                embedding=serialize_vector([1.0]),
                status=EMBEDDING_READY,
            )
        )
        await get_settings_row(db, workspace.id)
        await db.flush()

        await backfill_missing_embedding_rows(db)

        row = (
            await db.execute(
                select(EntryEmbedding).where(EntryEmbedding.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert row.status == EMBEDDING_PENDING
        assert row.model == "old-model"
        await db.execute(
            delete(EntryEmbedding).where(EntryEmbedding.workspace_id == workspace.id)
        )
        await db.execute(delete(Entry).where(Entry.project_id == project.id))
        await db.commit()


@pytest.mark.asyncio
async def test_encode_text_fallback_without_key() -> None:
    """未配置豆包密钥时编码返回降级结果，不访问外部网络。"""
    async with async_session_factory() as db:
        workspace = Workspace(name="测试空间")
        db.add(workspace)
        await db.flush()
        result = await encode_text(db, workspace.id, "地漏防臭")
        assert result.is_fallback is True
        assert result.vector is None
        assert "未配置豆包密钥" in result.error


@pytest.mark.asyncio
async def test_encode_text_parses_dict_data(monkeypatch) -> None:
    """方舟多模态端点 data 为对象时应正确解析稠密向量。"""

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"created": 1, "data": {"embedding": [0.1, 0.2, 0.3]}}

    class FakeClient:
        def __init__(self, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, url, headers=None, json=None):
            del url, headers, json
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.embedding.httpx.AsyncClient",
        lambda timeout: FakeClient(timeout),
    )

    async with async_session_factory() as db:
        workspace = Workspace(name="测试空间")
        db.add(workspace)
        await db.flush()
        get_secret_store().set(secret_key(workspace.id, "doubao"), "ark-test-key")
        result = await encode_text(db, workspace.id, "测试")

    assert result.vector == [0.1, 0.2, 0.3]
    assert result.is_fallback is False
    assert result.error is None


@pytest.mark.asyncio
async def test_embedding_config_reuses_vision_key(client: httpx.AsyncClient) -> None:
    """embedding 配置复用豆包视觉密钥，无需单独填写密钥。"""
    await _register(client)

    response = await client.get("/api/settings/ai")
    assert response.json()["embedding_configured"] is False
    assert response.json()["embedding_model"] == "doubao-embedding-vision-251215"

    await client.put("/api/settings/ai/vision", json={"api_key": "ark-1234567890wxyz"})
    saved = await client.put(
        "/api/settings/ai/embedding",
        json={"model": "doubao-embedding-vision-251215"},
    )

    assert saved.status_code == 200
    data = saved.json()
    assert data["embedding_configured"] is True
    assert data["embedding_key_tail"] == "wxyz"
    assert data["embedding_available"] is False
    assert data["embedding_tested"] is False


@pytest.mark.asyncio
async def test_clear_embedding_disables(client: httpx.AsyncClient) -> None:
    """停用 embedding 后回到未配置状态。"""
    await _register(client)
    await client.put("/api/settings/ai/vision", json={"api_key": "ark-1234567890wxyz"})
    await client.put("/api/settings/ai/embedding", json={})

    response = await client.delete("/api/settings/ai/embedding")

    assert response.status_code == 200
    assert response.json()["embedding_configured"] is False
    assert response.json()["embedding_key_tail"] is None
    assert response.json()["embedding_tested"] is False


@pytest.mark.asyncio
async def test_embedding_test_connection_updates_available(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """embedding 连接测试成功应标记可用。"""
    await _register(client)
    await client.put("/api/settings/ai/vision", json={"api_key": "ark-1234567890wxyz"})
    await client.put("/api/settings/ai/embedding", json={})

    async def _fake_test(db, workspace_id):
        del db, workspace_id
        return ConnectionTestOut(ok=True, message="ok")

    monkeypatch.setattr("app.api.ai_settings.test_embedding_connection", _fake_test)
    response = await client.post("/api/settings/ai/embedding/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    data = (await client.get("/api/settings/ai")).json()
    assert data["embedding_available"] is True
    assert data["embedding_tested"] is True


@pytest.mark.asyncio
async def test_embedding_failed_test_marks_tested(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """连接测试失败也应记录已测试，徽标可区分「未测试」与「连接失败」。"""
    await _register(client)
    await client.put("/api/settings/ai/vision", json={"api_key": "ark-1234567890wxyz"})
    await client.put("/api/settings/ai/embedding", json={})

    async def _fake_test(db, workspace_id):
        del db, workspace_id
        return ConnectionTestOut(ok=False, message="模型未开通")

    monkeypatch.setattr("app.api.ai_settings.test_embedding_connection", _fake_test)
    response = await client.post("/api/settings/ai/embedding/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    data = (await client.get("/api/settings/ai")).json()
    assert data["embedding_available"] is False
    assert data["embedding_tested"] is True


@pytest.mark.asyncio
async def test_relation_high_similarity_rule_duplicate(client, monkeypatch) -> None:
    """高相似度候选由规则直判 duplicate，不调用文本模型。"""
    await _register(client)
    project = await _create_project(client, "阈值项目")
    node = await _create_node(client, project["id"], "施工")
    first = await _create_source(client, project["id"], "闭水试验规范")
    second = await _create_source(client, project["id"], "闭水试验")
    await _process(client, first["id"])
    await _process(client, second["id"])
    entry = await _archive_first(client, node["id"], first["id"])
    candidate = (await _candidates(client, second["id"]))[0]

    async def _fake_hybrid(db, workspace_id, candidate, entries, top_k):
        del db, workspace_id, candidate, top_k
        return [(entries[0], 0.99)]

    monkeypatch.setattr(
        "app.services.entry_relation.hybrid_recall_for_candidate",
        _fake_hybrid,
    )

    async with async_session_factory() as db:
        source = await db.get(Source, candidate["source_id"])
        await route_relations(db, source.id)
        await db.commit()
        row = (
            await db.execute(select(Candidate).where(Candidate.id == candidate["id"]))
        ).scalar_one()

    assert row.relation_status == "duplicate"
    assert row.relation_target_entry_id == entry["id"]
    assert "规则判定重复" in row.relation_reason


@pytest.mark.asyncio
async def test_relation_low_similarity_rule_new(client, monkeypatch) -> None:
    """低相似度候选由规则直判 new，不调用文本模型。"""
    await _register(client)
    project = await _create_project(client, "阈值项目")
    node = await _create_node(client, project["id"], "施工")
    first = await _create_source(client, project["id"], "闭水试验规范")
    second = await _create_source(client, project["id"], "招聘要求学历本科")
    await _process(client, first["id"])
    await _process(client, second["id"])
    await _archive_first(client, node["id"], first["id"])
    candidate = (await _candidates(client, second["id"]))[0]

    async def _fake_hybrid(db, workspace_id, candidate, entries, top_k):
        del db, workspace_id, candidate, top_k
        return [(entries[0], 0.10)]

    monkeypatch.setattr(
        "app.services.entry_relation.hybrid_recall_for_candidate",
        _fake_hybrid,
    )

    async with async_session_factory() as db:
        source = await db.get(Source, candidate["source_id"])
        await route_relations(db, source.id)
        await db.commit()
        row = (
            await db.execute(select(Candidate).where(Candidate.id == candidate["id"]))
        ).scalar_one()

    assert row.relation_status == "new"
    assert row.relation_target_entry_id is None
    assert "规则判定新知识" in row.relation_reason


@pytest.mark.asyncio
async def test_relation_middle_similarity_goes_to_llm(client, monkeypatch) -> None:
    """中间区间候选交文本模型判定；无密钥时按离线确定性判定 new。"""
    await _register(client)
    project = await _create_project(client, "阈值项目")
    node = await _create_node(client, project["id"], "施工")
    first = await _create_source(client, project["id"], "闭水试验规范")
    second = await _create_source(client, project["id"], "闭水试验")
    await _process(client, first["id"])
    await _process(client, second["id"])
    await _archive_first(client, node["id"], first["id"])
    candidate = (await _candidates(client, second["id"]))[0]

    async def _fake_hybrid(db, workspace_id, candidate, entries, top_k):
        del db, workspace_id, candidate, top_k
        return [(entries[0], 0.70)]

    monkeypatch.setattr(
        "app.services.entry_relation.hybrid_recall_for_candidate",
        _fake_hybrid,
    )

    async with async_session_factory() as db:
        source = await db.get(Source, candidate["source_id"])
        await route_relations(db, source.id)
        await db.commit()
        row = (
            await db.execute(select(Candidate).where(Candidate.id == candidate["id"]))
        ).scalar_one()

    assert row.relation_status == "new"
    assert "规则判定" not in (row.relation_reason or "")
