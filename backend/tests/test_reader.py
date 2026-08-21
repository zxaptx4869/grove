"""Reader 带引用问答与保存转候选测试。"""

import uuid

import httpx
import pytest

from app.main import create_app
from app.processing import worker


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


async def _project(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _entry(client: httpx.AsyncClient, project_id: int, node_id: int, text: str) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": text, "project_id": str(project_id)},
    )
    assert response.status_code == 201
    source = response.json()
    await client.post(f"/api/sources/{source['id']}/process")
    assert await worker.process_one_task() is True
    candidates = (await client.get(f"/api/sources/{source['id']}/candidates")).json()
    assert candidates
    response = await client.post(
        f"/api/candidates/{candidates[0]['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_reader_ask_project_scope_falls_back(client: httpx.AsyncClient) -> None:
    """未配置密钥时项目范围问答降级为离线回答并标记。"""
    await _register(client)
    project = await _project(client, "阅读项目")
    node = await _node(client, project["id"], "施工")
    await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")

    response = await client.post(
        f"/api/projects/{project['id']}/reader/ask",
        json={"message": "闭水试验怎么做", "scope": "project"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_fallback"] is True
    assert data["insufficient"] is True
    assert "没有可用的文本模型" in data["answer"]
    assert data["provider"] == "offline"
    assert data["citations"] == []


@pytest.mark.asyncio
async def test_reader_ask_node_scope(client: httpx.AsyncClient) -> None:
    """节点范围问答限定在指定节点及其子树。"""
    await _register(client)
    project = await _project(client, "阅读项目")
    first = await _node(client, project["id"], "水电")
    second = await _node(client, project["id"], "瓦工")
    await _entry(client, project["id"], first["id"], "闭水试验通常持续 24 小时")
    await _entry(client, project["id"], second["id"], "瓷砖美缝后 48 小时再踩踏")

    response = await client.post(
        f"/api/projects/{project['id']}/reader/ask",
        json={"message": "闭水试验怎么做", "scope": "node", "node_id": first["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_fallback"] is True
    assert data["insufficient"] is True


@pytest.mark.asyncio
async def test_reader_ask_empty_project_is_insufficient(client: httpx.AsyncClient) -> None:
    """空项目问答返回知识不足。"""
    await _register(client)
    project = await _project(client, "空项目")

    response = await client.post(
        f"/api/projects/{project['id']}/reader/ask",
        json={"message": "有什么知识", "scope": "project"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["insufficient"] is True
    assert "还没有已确认" in data["answer"]


@pytest.mark.asyncio
async def test_reader_ask_project_and_node_not_found(client: httpx.AsyncClient) -> None:
    """越权项目与节点返回 404。"""
    await _register(client)
    response = await client.post(
        "/api/projects/99999/reader/ask",
        json={"message": "问题", "scope": "project"},
    )
    assert response.status_code == 404

    project = await _project(client, "阅读项目")
    response = await client.post(
        f"/api/projects/{project['id']}/reader/ask",
        json={"message": "问题", "scope": "node", "node_id": 99999},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reader_save_candidate_creates_virtual_source(client: httpx.AsyncClient) -> None:
    """保存回答创建虚拟 Source 与待采纳 Candidate，进入确认台。"""
    await _register(client)
    project = await _project(client, "阅读项目")
    node = await _node(client, project["id"], "施工")
    entry = await _entry(client, project["id"], node["id"], "闭水试验通常持续 24 小时")
    source_id = entry["evidences"][0]["source_id"]

    response = await client.post(
        f"/api/projects/{project['id']}/reader/save-candidate",
        json={
            "question": "闭水试验怎么做",
            "title": "闭水试验做法",
            "content": "闭水试验通常持续 24 小时。",
            "citations": [
                {"entry_id": entry["id"], "source_id": source_id, "quote": "持续 24 小时"}
            ],
        },
    )
    assert response.status_code == 200
    candidate = response.json()
    assert candidate["status"] == "pending"
    assert candidate["title"] == "闭水试验做法"
    assert candidate["source_id"] > 0
    assert candidate["evidence"][0]["quote"] == "持续 24 小时"

    sources = (await client.get("/api/sources", params={"project_id": project["id"]})).json()
    virtual_source = next(item for item in sources if item["id"] == candidate["source_id"])
    assert virtual_source["title"].startswith("AI 阅读问答：")
    assert virtual_source["attachments"][0]["text_content"] == "闭水试验通常持续 24 小时。"

    listed = (await client.get(f"/api/sources/{candidate['source_id']}/candidates")).json()
    assert any(item["id"] == candidate["id"] for item in listed)


@pytest.mark.asyncio
async def test_reader_save_candidate_rejects_invalid_citation(client: httpx.AsyncClient) -> None:
    """保存回答时非法引用返回 400，不创建数据。"""
    await _register(client)
    project = await _project(client, "阅读项目")

    response = await client.post(
        f"/api/projects/{project['id']}/reader/save-candidate",
        json={
            "question": "问题",
            "title": "标题",
            "content": "内容",
            "citations": [{"entry_id": 99999, "source_id": 99999, "quote": "片段"}],
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_reader_respects_workspace_isolation(client: httpx.AsyncClient) -> None:
    """问答与保存不能跨 Workspace 访问项目。"""
    await _register(client)
    project = await _project(client, "甲的空间")

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other_client:
        await _register(other_client)
        ask = await other_client.post(
            f"/api/projects/{project['id']}/reader/ask",
            json={"message": "问题", "scope": "project"},
        )
        assert ask.status_code == 404
        save = await other_client.post(
            f"/api/projects/{project['id']}/reader/save-candidate",
            json={
                "question": "问题",
                "title": "标题",
                "content": "内容",
                "citations": [],
            },
        )
        assert save.status_code == 404


def test_validate_citations_keeps_valid_and_drops_invalid() -> None:
    """引用校验保留有效引用、丢弃非法 entry 与非法 source。"""
    from app.agents.reader import ReaderCitationDraft
    from app.models import Entry, EntrySourceEvidence, Source
    from app.services.reader import _validate_citations

    source = Source(id=68, workspace_id=79, project_id=26, title="来源A")
    evidence = EntrySourceEvidence(
        id=1,
        entry_id=10,
        source_id=68,
        attachment_id=5,
        quote="原文片段",
    )
    entry = Entry(
        id=10,
        project_id=26,
        node_id=1,
        title="闭水试验",
        content="闭水试验通常持续 24 小时",
        main_type="knowledge",
    )
    evidence.source = source
    entry.evidences = [evidence]

    citations = [
        ReaderCitationDraft(entry_id=10, source_id=68, quote="有效引用"),
        ReaderCitationDraft(entry_id=999, source_id=68, quote="非法 Entry"),
        ReaderCitationDraft(entry_id=10, source_id=999, quote="非法 Source"),
    ]

    result = _validate_citations(citations, [entry])

    assert len(result) == 1
    assert result[0].entry_id == 10
    assert result[0].source_id == 68
    assert result[0].entry_title == "闭水试验"
    assert result[0].source_title == "来源A"
    assert result[0].quote == "有效引用"
