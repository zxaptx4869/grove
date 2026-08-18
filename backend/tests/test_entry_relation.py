"""候选与已有 Entry 关系建议的测试。"""

import json
import uuid

import httpx
import pytest

from app.agents.relation import EntryRevisionDraft, RelationRecommendationDraft
from app.main import create_app
from app.models import Candidate, Entry
from app.processing import worker
from app.services.entry_relation import _apply_recommendation, retrieve_similar_entries


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as api_client:
        yield api_client


def _candidate(title: str, content: str, candidate_id: int = 1) -> Candidate:
    return Candidate(
        id=candidate_id,
        extraction_id=1,
        source_id=1,
        candidate_kind="recommended",
        title=title,
        content=content,
        main_type="knowledge",
        info_nature="fact",
        status="pending",
    )


def _entry(title: str, content: str, entry_id: int = 1) -> Entry:
    return Entry(
        id=entry_id,
        project_id=1,
        node_id=10,
        title=title,
        content=content,
        main_type="knowledge",
    )


async def _register(client: httpx.AsyncClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


async def _create_project(client: httpx.AsyncClient) -> dict:
    response = await client.post("/api/projects", json={"name": "关系项目"})
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


def test_retrieve_similar_entries_ranks_title_match() -> None:
    candidate = _candidate("闭水试验规范", "闭水试验通常持续 24 小时")
    entries = [
        _entry("瓷砖铺贴", "地砖铺贴工艺", entry_id=1),
        _entry("闭水试验", "闭水试验通常持续 24 小时", entry_id=2),
    ]

    result = retrieve_similar_entries(entries, candidate)

    assert [item.id for item in result] == [2]


def test_retrieve_similar_entries_returns_empty_without_overlap() -> None:
    candidate = _candidate("招聘要求", "学历本科")
    entries = [_entry("闭水试验", "闭水试验通常持续 24 小时")]

    assert retrieve_similar_entries(entries, candidate) == []


def test_apply_recommendation_invalid_target_downgrades_to_new() -> None:
    candidate = _candidate("闭水试验", "内容")
    recommendation = RelationRecommendationDraft(
        candidate_id=1,
        relation_status="duplicate",
        target_entry_id=999,
        reason="内容相同",
    )

    _apply_recommendation(candidate, recommendation, {1})

    assert candidate.relation_status == "new"
    assert candidate.relation_target_entry_id is None
    assert candidate.relation_reason == "目标 Entry 无效，按新知识处理"
    assert candidate.revision_draft is None


def test_apply_recommendation_supplement_without_draft_downgrades_to_duplicate() -> None:
    candidate = _candidate("闭水试验", "内容")
    recommendation = RelationRecommendationDraft(
        candidate_id=1,
        relation_status="supplement",
        target_entry_id=1,
        reason="补充参数",
    )

    _apply_recommendation(candidate, recommendation, {1})

    assert candidate.relation_status == "duplicate"
    assert candidate.relation_target_entry_id == 1
    assert candidate.relation_reason == "缺少修订草稿，按补充来源处理"
    assert candidate.revision_draft is None


def test_apply_recommendation_conflict_keeps_revision_draft() -> None:
    candidate = _candidate("闭水试验", "内容")
    draft = EntryRevisionDraft(
        title="闭水试验规范",
        content="通常持续 24 小时",
        change_summary="更新",
    )
    recommendation = RelationRecommendationDraft(
        candidate_id=1,
        relation_status="conflict",
        target_entry_id=1,
        reason="与已有知识矛盾",
        revision_draft=draft,
    )

    _apply_recommendation(candidate, recommendation, {1})

    assert candidate.relation_status == "conflict"
    assert candidate.relation_target_entry_id == 1
    assert candidate.relation_reason == "与已有知识矛盾"
    assert json.loads(candidate.revision_draft)["change_summary"] == "更新"


@pytest.mark.asyncio
async def test_add_evidence_appends_source_and_confirms_candidate(client) -> None:
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    first_source = await _create_source(client, project["id"], "第一条知识")
    second_source = await _create_source(client, project["id"], "第二条知识")
    await _process(client, first_source["id"])
    await _process(client, second_source["id"])
    entry = await _archive_first(client, node["id"], first_source["id"])
    candidate = (await _candidates(client, second_source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )

    assert response.status_code == 200
    detail = (await client.get(f"/api/entries/{entry['id']}")).json()
    assert any(item["source_id"] == second_source["id"] for item in detail["evidences"])
    assert (await _candidates(client, second_source["id"]))[0]["status"] == "confirmed"

    locked = await client.post(
        f"/api/candidates/{candidate['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )
    assert locked.status_code == 409


@pytest.mark.asyncio
async def test_apply_revision_updates_entry_and_confirms_candidate(client) -> None:
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    first_source = await _create_source(client, project["id"], "第一条知识")
    second_source = await _create_source(client, project["id"], "补充知识")
    await _process(client, first_source["id"])
    await _process(client, second_source["id"])
    entry = await _archive_first(client, node["id"], first_source["id"])
    candidate = (await _candidates(client, second_source["id"]))[0]

    response = await client.post(
        f"/api/candidates/{candidate['id']}/apply-revision",
        json={
            "entry_id": entry["id"],
            "title": "闭水试验规范",
            "content": "闭水试验通常持续 24 小时以上。",
            "applicable_condition": None,
        },
    )

    assert response.status_code == 200
    detail = (await client.get(f"/api/entries/{entry['id']}")).json()
    assert detail["title"] == "闭水试验规范"
    assert detail["content"] == "闭水试验通常持续 24 小时以上。"
    assert any(item["source_id"] == second_source["id"] for item in detail["evidences"])
    assert (await _candidates(client, second_source["id"]))[0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_add_evidence_isolates_entry_by_workspace_and_project(client) -> None:
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    first_source = await _create_source(client, project["id"], "第一条知识")
    await _process(client, first_source["id"])
    entry = await _archive_first(client, node["id"], first_source["id"])

    other_project = await _create_project(client)
    other_source = await _create_source(client, other_project["id"], "其他项目知识")
    await _process(client, other_source["id"])
    other_candidate = (await _candidates(client, other_source["id"]))[0]

    cross_project = await client.post(
        f"/api/candidates/{other_candidate['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )
    assert cross_project.status_code == 400

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as other_client:
        await _register(other_client)
        foreign_project = await _create_project(other_client)
        foreign_source = await _create_source(other_client, foreign_project["id"], "外部知识")
        await _process(other_client, foreign_source["id"])
        foreign_candidate = (await _candidates(other_client, foreign_source["id"]))[0]
        cross_workspace = await other_client.post(
            f"/api/candidates/{foreign_candidate['id']}/add-evidence",
            json={"entry_id": entry["id"]},
        )
        assert cross_workspace.status_code == 404
