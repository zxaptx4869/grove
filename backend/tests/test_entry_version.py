"""Entry 版本历史与 AI 修订建议测试。"""

import uuid

import httpx
import pytest

from app.agents.revision import RevisionDraft, RevisionReplyDraft
from app.main import create_app
from app.processing import worker
from app.services.entry import _normalize_revision_reply


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


async def _create_project(client: httpx.AsyncClient) -> dict:
    response = await client.post("/api/projects", json={"name": "版本项目"})
    assert response.status_code == 201
    return response.json()


async def _create_node(client: httpx.AsyncClient, project_id: int, name: str) -> dict:
    response = await client.post(
        f"/api/projects/{project_id}/nodes",
        json={"name": name, "parent_id": None},
    )
    assert response.status_code == 201
    return response.json()


async def _create_source(client: httpx.AsyncClient, project_id: int) -> dict:
    response = await client.post(
        "/api/sources",
        data={"text": "闭水试验至少持续 24 小时", "project_id": str(project_id)},
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
    project_id: int,
    node_id: int,
) -> dict:
    source = await _create_source(client, project_id)
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    response = await client.post(
        f"/api/candidates/{candidate['id']}/archive",
        json={"node_id": node_id},
    )
    assert response.status_code == 200
    return response.json()


async def _versions(client: httpx.AsyncClient, entry_id: int) -> list[dict]:
    response = await client.get(f"/api/entries/{entry_id}/versions")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_create_entry_has_initial_version(client: httpx.AsyncClient) -> None:
    """创建 Entry 时应生成版本 1。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    versions = await _versions(client, entry["id"])

    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["change_type"] == "created"
    assert versions[0]["title"] == entry["title"]


@pytest.mark.asyncio
async def test_edit_appends_version_and_noop_does_not(
    client: httpx.AsyncClient,
) -> None:
    """编辑应追加版本；无实际变化不追加。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    response = await client.patch(
        f"/api/entries/{entry['id']}",
        json={"title": "新标题", "content": "闭水试验至少持续 24 小时并观察渗漏"},
    )
    assert response.status_code == 200
    versions = await _versions(client, entry["id"])
    assert len(versions) == 2
    assert versions[0]["change_type"] == "edited"
    assert versions[0]["title"] == "新标题"
    assert versions[0]["content"] == "闭水试验至少持续 24 小时并观察渗漏"

    response = await client.patch(
        f"/api/entries/{entry['id']}",
        json={"title": "新标题", "content": "闭水试验至少持续 24 小时并观察渗漏"},
    )
    assert response.status_code == 200
    assert len(await _versions(client, entry["id"])) == 2


@pytest.mark.asyncio
async def test_apply_candidate_revision_records_version(
    client: httpx.AsyncClient,
) -> None:
    """应用候选修订草稿应追加 ai_revision 版本并记录变更说明。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    response = await client.post(
        f"/api/candidates/{candidate['id']}/apply-revision",
        json={
            "entry_id": entry["id"],
            "content": "闭水试验至少持续 24 小时，蓄水深度不低于 20mm",
            "change_summary": "补充验收标准",
        },
    )
    assert response.status_code == 200

    versions = await _versions(client, entry["id"])
    assert versions[0]["change_type"] == "ai_revision"
    assert versions[0]["change_summary"] == "补充验收标准"
    assert versions[0]["content"] == "闭水试验至少持续 24 小时，蓄水深度不低于 20mm"


@pytest.mark.asyncio
async def test_add_evidence_does_not_create_version(
    client: httpx.AsyncClient,
) -> None:
    """补充来源证据不应产生版本。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    source = await _create_source(client, project["id"])
    await _process(client, source["id"])
    candidate = (await _candidates(client, source["id"]))[0]
    response = await client.post(
        f"/api/candidates/{candidate['id']}/add-evidence",
        json={"entry_id": entry["id"]},
    )
    assert response.status_code == 200

    assert len(await _versions(client, entry["id"])) == 1


@pytest.mark.asyncio
async def test_versions_rolling_cap(client: httpx.AsyncClient) -> None:
    """版本数超过保留上限时应滚动丢弃最旧版本。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    for index in range(12):
        response = await client.patch(
            f"/api/entries/{entry['id']}",
            json={"title": f"标题 {index}"},
        )
        assert response.status_code == 200

    versions = await _versions(client, entry["id"])
    assert len(versions) == 10
    assert versions[0]["version_number"] == 13
    assert versions[-1]["version_number"] == 4


@pytest.mark.asyncio
async def test_restore_entry_restores_fields_and_node(
    client: httpx.AsyncClient,
) -> None:
    """恢复到旧版本应还原字段与目录，并追加恢复版本。"""
    await _register(client)
    project = await _create_project(client)
    node1 = await _create_node(client, project["id"], "施工")
    node2 = await _create_node(client, project["id"], "验收")
    entry = await _archive_first(client, project["id"], node1["id"])
    version1 = (await _versions(client, entry["id"]))[0]

    await client.patch(
        f"/api/entries/{entry['id']}",
        json={"title": "改过的标题", "node_id": node2["id"]},
    )

    response = await client.post(
        f"/api/entries/{entry['id']}/restore",
        json={"version_id": version1["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == version1["title"]
    assert data["node_id"] == node1["id"]
    assert data["node_name"] == "施工"

    versions = await _versions(client, entry["id"])
    assert versions[0]["change_type"] == "restored"
    assert versions[0]["change_summary"] == "恢复到版本 1"
    assert versions[0]["title"] == version1["title"]
    assert len(versions) == 3


@pytest.mark.asyncio
async def test_restore_missing_version_404(client: httpx.AsyncClient) -> None:
    """恢复不存在的版本应返回 404 且 Entry 不变。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    response = await client.post(
        f"/api/entries/{entry['id']}/restore",
        json={"version_id": 99999},
    )

    assert response.status_code == 404
    assert len(await _versions(client, entry["id"])) == 1


@pytest.mark.asyncio
async def test_versions_foreign_workspace_404(client: httpx.AsyncClient) -> None:
    """其他 Workspace 用户读取或恢复版本应返回 404。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])
    version = (await _versions(client, entry["id"]))[0]

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await _register(other)
        assert (
            await other.get(f"/api/entries/{entry['id']}/versions")
        ).status_code == 404
        assert (
            await other.post(
                f"/api/entries/{entry['id']}/restore",
                json={"version_id": version["id"]},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_revision_suggestion_offline_fallback(
    client: httpx.AsyncClient,
) -> None:
    """未配置文本模型密钥时修订建议应降级返回，不生成草稿。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    response = await client.post(
        f"/api/entries/{entry['id']}/revision-suggestion",
        json={"instruction": "补充验收标准"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "discuss"
    assert data["is_fallback"] is True
    assert data["draft"] is None
    assert data["error"]

    refine = await client.post(
        f"/api/entries/{entry['id']}/revision-suggestion/refine",
        json={
            "instruction": "再补充下沉式卫生间差异",
            "messages": [{"role": "user", "content": "补充验收标准"}],
        },
    )
    assert refine.status_code == 200
    assert refine.json()["intent"] == "discuss"
    assert refine.json()["is_fallback"] is True


def test_normalize_revision_reply_discuss_drops_draft() -> None:
    """意图为 discuss 却携带草稿时应丢弃草稿。"""
    reply = RevisionReplyDraft(
        intent="discuss",
        reply_text="讨论回复",
        draft=RevisionDraft(title="建议标题"),
    )

    normalized = _normalize_revision_reply(reply)

    assert normalized.intent == "discuss"
    assert normalized.draft is None


def test_normalize_revision_reply_propose_without_draft_downgrades() -> None:
    """意图为 propose 却缺少草稿时应降级为 discuss。"""
    reply = RevisionReplyDraft(
        intent="propose",
        reply_text="回复",
        draft=None,
    )

    normalized = _normalize_revision_reply(reply)

    assert normalized.intent == "discuss"


@pytest.mark.asyncio
async def test_revision_suggestion_foreign_workspace_404(
    client: httpx.AsyncClient,
) -> None:
    """其他 Workspace 用户发起或应用修订建议应返回 404。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        await _register(other)
        assert (
            await other.post(
                f"/api/entries/{entry['id']}/revision-suggestion",
                json={},
            )
        ).status_code == 404
        assert (
            await other.post(
                f"/api/entries/{entry['id']}/revision-suggestion/apply",
                json={"title": "越权", "content": "越权"},
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_apply_revision_suggestion_updates_entry_and_version(
    client: httpx.AsyncClient,
) -> None:
    """应用 AI 修订草稿应更新 Entry、追加 ai_revision 版本且证据不变。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])
    evidence_before = entry["evidences"]

    response = await client.post(
        f"/api/entries/{entry['id']}/revision-suggestion/apply",
        json={
            "title": entry["title"],
            "content": "闭水试验至少持续 24 小时，蓄水深度不低于 20mm",
            "main_type": "knowledge",
            "info_nature": "fact",
            "applicable_condition": "",
            "note": "",
            "change_summary": "补充验收标准",
            "instruction": "补充验收标准",
            "ai_reply": "我建议补充验收标准。",
            "reason": "现有内容缺少验收细节",
            "provider": "llm",
            "model": "test-model",
            "external_supplemented": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "闭水试验至少持续 24 小时，蓄水深度不低于 20mm"
    assert data["evidences"][0] == evidence_before[0]
    assert len(data["evidences"]) == len(evidence_before) + 1
    assert "AI 修订建议" in data["evidences"][-1]["source_title"]
    assert data["evidences"][-1]["quote"] == "补充验收标准"

    versions = await _versions(client, entry["id"])
    assert versions[0]["change_type"] == "ai_revision"
    assert versions[0]["change_summary"] == "补充验收标准"
    assert versions[0]["content"] == "闭水试验至少持续 24 小时，蓄水深度不低于 20mm"


@pytest.mark.asyncio
async def test_apply_formatting_only_revision_keeps_version_without_source(
    client: httpx.AsyncClient,
) -> None:
    """纯格式调整应用后应记版本但不新增来源证据。"""
    await _register(client)
    project = await _create_project(client)
    node = await _create_node(client, project["id"], "施工")
    entry = await _archive_first(client, project["id"], node["id"])
    evidence_before = entry["evidences"]

    response = await client.post(
        f"/api/entries/{entry['id']}/revision-suggestion/apply",
        json={
            "title": entry["title"],
            "content": "闭水试验至少持续 24 小时，观察渗漏。",
            "main_type": "knowledge",
            "info_nature": "fact",
            "applicable_condition": "",
            "note": "",
            "change_summary": "调整表述更通顺",
            "external_supplemented": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "闭水试验至少持续 24 小时，观察渗漏。"
    assert data["evidences"] == evidence_before

    versions = await _versions(client, entry["id"])
    assert versions[0]["change_type"] == "ai_revision"
    assert versions[0]["change_summary"] == "调整表述更通顺"
