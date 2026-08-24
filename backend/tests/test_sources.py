"""Source 采集与附件 API 测试。"""

import uuid

from fastapi.testclient import TestClient

from app.main import create_app

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def _new_client() -> TestClient:
    return TestClient(create_app())


def _register(client: TestClient) -> str:
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


def _create_project(client: TestClient, name: str = "测试项目") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _upload_image(client: TestClient, **data) -> dict:
    return client.post(
        "/api/sources",
        files=[("files", ("a.png", PNG_BYTES, "image/png"))],
        data=data,
    ).json()


def test_create_text_source_unassigned(client: TestClient) -> None:
    """粘贴文字创建未归属 Source，标题取首行。"""
    _register(client)

    response = client.post(
        "/api/sources",
        data={"text": "第一行\n第二行", "note": "采集说明"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "第一行"
    assert body["project_id"] is None
    assert body["note"] == "采集说明"
    assert body["attachments"][0]["kind"] == "text"
    assert body["attachments"][0]["text_content"] == "第一行\n第二行"


def test_create_image_source_with_project(client: TestClient) -> None:
    """上传图片创建 Source，标题取文件名并归属项目。"""
    _register(client)
    project = _create_project(client)

    response = client.post(
        "/api/sources",
        files=[("files", ("厨房插座.png", PNG_BYTES, "image/png"))],
        data={"project_id": str(project["id"]), "note": "看图"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "厨房插座.png"
    assert body["project_id"] == project["id"]
    assert body["note"] == "看图"
    assert body["attachments"][0]["kind"] == "image"


def test_list_sources_filters(client: TestClient) -> None:
    """未归属与项目筛选应分别返回正确来源。"""
    _register(client)
    project = _create_project(client)
    client.post("/api/sources", data={"text": "未归属文本"})
    client.post(
        "/api/sources",
        files=[("files", ("b.png", PNG_BYTES, "image/png"))],
        data={"project_id": str(project["id"])},
    )

    unassigned = client.get("/api/sources?unassigned=true").json()
    assert len(unassigned) == 1
    assert unassigned[0]["project_id"] is None

    project_sources = client.get(f"/api/sources?project_id={project['id']}").json()
    assert len(project_sources) == 1
    assert project_sources[0]["project_id"] == project["id"]


def test_update_source_project_and_note(client: TestClient) -> None:
    """来源可归属项目、改说明并可重新设为未归属。"""
    _register(client)
    project = _create_project(client)
    source_id = client.post("/api/sources", data={"text": "待归属"}).json()["id"]

    assigned = client.patch(
        f"/api/sources/{source_id}",
        json={"project_id": project["id"], "note": "改说明"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["project_id"] == project["id"]
    assert assigned.json()["note"] == "改说明"

    unassigned = client.patch(f"/api/sources/{source_id}", json={"project_id": None})
    assert unassigned.status_code == 200
    assert unassigned.json()["project_id"] is None


def test_source_isolation_between_users() -> None:
    """跨用户 Source 不可见（列表不含、直接访问 404）。"""
    client_a = _new_client()
    client_b = _new_client()

    with client_a, client_b:
        _register(client_a)
        _register(client_b)
        source_id = client_a.post("/api/sources", data={"text": "A 的文本"}).json()["id"]

        assert client_b.get("/api/sources").json() == []
        assert client_b.get(f"/api/sources/{source_id}").status_code == 404


def test_image_file_access(client: TestClient) -> None:
    """上传后可经附件接口读取原图。"""
    _register(client)
    source = client.post(
        "/api/sources",
        files=[("files", ("a.png", PNG_BYTES, "image/png"))],
    ).json()
    attachment_id = source["attachments"][0]["id"]

    response = client.get(f"/api/sources/{source['id']}/attachments/{attachment_id}/file")

    assert response.status_code == 200
    assert response.content == PNG_BYTES


def test_delete_source_cleans_up(client: TestClient) -> None:
    """删除 Source 后详情应 404。"""
    _register(client)
    source_id = client.post("/api/sources", data={"text": "待删除"}).json()["id"]

    assert client.delete(f"/api/sources/{source_id}").status_code == 200
    assert client.get(f"/api/sources/{source_id}").status_code == 404


def test_delete_project_keeps_sources_unassigned(client: TestClient) -> None:
    """删除项目后，其 Source 应转为未归属且保留。"""
    _register(client)
    project = _create_project(client)
    source = client.post(
        "/api/sources",
        files=[("files", ("a.png", PNG_BYTES, "image/png"))],
        data={"project_id": str(project["id"])},
    ).json()
    assert source["project_id"] == project["id"]

    assert client.delete(f"/api/projects/{project['id']}").status_code == 200

    sources = client.get("/api/sources?unassigned=true").json()
    assert len(sources) == 1
    assert sources[0]["id"] == source["id"]
    assert sources[0]["project_id"] is None


def test_reject_non_image(client: TestClient) -> None:
    """非图片文件应返回 400。"""
    _register(client)

    response = client.post(
        "/api/sources",
        files=[("files", ("a.txt", b"plain", "text/plain"))],
    )

    assert response.status_code == 400


def test_list_sources_limit(client: TestClient) -> None:
    """limit 参数应限制最近来源条数。"""
    _register(client)
    for index in range(3):
        client.post("/api/sources", data={"text": f"来源 {index}"})

    response = client.get("/api/sources", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_query_sources_filters_and_pagination(client: TestClient) -> None:
    """query 端点应支持项目/状态/关键词筛选与分页。"""
    _register(client)
    project = _create_project(client)
    client.post("/api/sources", data={"text": "闭水试验 24 小时"})
    client.post(
        "/api/sources",
        data={"text": "瓷砖铺贴", "project_id": str(project["id"]), "note": "阳台"},
    )
    client.post(
        "/api/sources",
        data={"text": "闭水试验 48 小时", "project_id": str(project["id"])},
    )

    by_project = client.get("/api/sources/query", params={"project_id": project["id"]})
    assert by_project.status_code == 200
    assert by_project.json()["total"] == 2
    assert all(item["project_id"] == project["id"] for item in by_project.json()["items"])

    by_q = client.get("/api/sources/query", params={"q": "闭水"})
    assert by_q.json()["total"] == 2

    by_status = client.get("/api/sources/query", params={"status": "waiting"})
    assert by_status.json()["total"] == 3

    page1 = client.get("/api/sources/query", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/sources/query", params={"limit": 2, "offset": 2}).json()
    assert len(page1["items"]) == 2
    assert page1["total"] == 3
    assert len(page2["items"]) == 1
    assert not {item["id"] for item in page1["items"]} & {item["id"] for item in page2["items"]}

    other = _new_client()
    _register(other)
    assert (
        other.get("/api/sources/query", params={"project_id": project["id"]}).status_code
        == 404
    )


def test_reject_too_many_images(client: TestClient) -> None:
    """超过 5 张图片应返回 400。"""
    _register(client)
    files = [("files", (f"{i}.png", PNG_BYTES, "image/png")) for i in range(6)]

    response = client.post("/api/sources", files=files)

    assert response.status_code == 400


def test_reject_oversized_image(client: TestClient) -> None:
    """单张超过 10MB 的图片应返回 400。"""
    _register(client)
    big = b"x" * (10 * 1024 * 1024 + 1)

    response = client.post(
        "/api/sources",
        files=[("files", ("big.png", big, "image/png"))],
    )

    assert response.status_code == 400


def test_reject_files_and_text(client: TestClient) -> None:
    """图片与文字同时提交应返回 400。"""
    _register(client)

    response = client.post(
        "/api/sources",
        files=[("files", ("a.png", PNG_BYTES, "image/png"))],
        data={"text": "同时提交"},
    )

    assert response.status_code == 400
