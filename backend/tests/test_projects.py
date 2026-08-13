"""项目与目录树 API 测试。"""

import uuid

from fastapi.testclient import TestClient

from app.main import create_app


def _new_client() -> TestClient:
    return TestClient(create_app())


def _register(client: TestClient) -> str:
    """注册并返回用户名（注册即登录，客户端自带会话 Cookie）。"""
    username = f"user_{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 201
    return username


def _create_project(
    client: TestClient,
    name: str,
    template: str = "empty",
) -> dict:
    response = client.post(
        "/api/projects",
        json={"name": name, "template": template},
    )
    assert response.status_code == 201
    return response.json()


def count_tree_nodes(nodes: list[dict]) -> int:
    """统计树节点总数。"""
    return sum(1 + count_tree_nodes(node["children"]) for node in nodes)


def test_project_list_empty_after_register(client: TestClient) -> None:
    """注册后项目列表应为空（不自动创建项目）。"""
    _register(client)

    response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.json() == []


def test_create_empty_project(client: TestClient) -> None:
    """空模板项目应无节点。"""
    _register(client)

    project = _create_project(client, "装修", template="empty")

    assert project["name"] == "装修"
    assert project["node_count"] == 0
    assert project["status"] == "active"
    tree = client.get(f"/api/projects/{project['id']}/tree")
    assert tree.json() == []


def test_project_lifecycle_filter_and_restore(client: TestClient) -> None:
    """项目状态可更新、筛选，归档默认隐藏且可恢复。"""
    _register(client)
    project = _create_project(client, "生命周期")
    paused = client.patch(
        f"/api/projects/{project['id']}/status", json={"status": "paused"}
    )
    assert paused.status_code == 200
    assert client.get("/api/projects?status_filter=active").json() == []
    assert client.get("/api/projects?status_filter=paused").json()[0]["status"] == "paused"
    archived = client.patch(
        f"/api/projects/{project['id']}/status", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert client.get("/api/projects").json() == []
    restored = client.patch(
        f"/api/projects/{project['id']}/status", json={"status": "active"}
    )
    assert restored.status_code == 200
    assert client.get("/api/projects").json()[0]["status"] == "active"


def test_create_decoration_project_seeds_full_tree(client: TestClient) -> None:
    """装修模板应生成 149 个节点的完整树。"""
    _register(client)

    project = _create_project(client, "房子装修", template="decoration")

    assert project["node_count"] == 149
    tree_response = client.get(f"/api/projects/{project['id']}/tree")
    assert tree_response.status_code == 200
    tree = tree_response.json()
    assert count_tree_nodes(tree) == 149
    assert len(tree) == 7
    assert tree[0]["name"] == "装修准备"
    assert tree[0]["children"][0]["name"] == "需求确认"


def test_project_isolation_between_users() -> None:
    """跨用户项目不可见（列表不含、直接访问 404）。"""
    client_a = _new_client()
    client_b = _new_client()

    with client_a, client_b:
        _register(client_a)
        _register(client_b)
        project = _create_project(client_a, "A 的装修", template="decoration")

        list_b = client_b.get("/api/projects")
        assert list_b.json() == []

        tree_b = client_b.get(f"/api/projects/{project['id']}/tree")
        assert tree_b.status_code == 404


def test_node_create_root_and_child(client: TestClient) -> None:
    """根节点与子节点创建后应出现在树中。"""
    _register(client)
    project = _create_project(client, "测试项目")

    root_response = client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "根节点", "description": "描述", "parent_id": None},
    )
    assert root_response.status_code == 201
    root = root_response.json()

    child_response = client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "子节点", "parent_id": root["id"]},
    )
    assert child_response.status_code == 201

    tree = client.get(f"/api/projects/{project['id']}/tree").json()
    assert len(tree) == 1
    assert tree[0]["name"] == "根节点"
    assert tree[0]["description"] == "描述"
    assert tree[0]["children"][0]["name"] == "子节点"


def test_node_rename_and_description(client: TestClient) -> None:
    """节点重命名与描述更新应生效。"""
    _register(client)
    project = _create_project(client, "测试项目")
    node = client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "旧名"},
    ).json()

    response = client.patch(
        f"/api/projects/{project['id']}/nodes/{node['id']}",
        json={"name": "新名", "description": "新描述"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "新名"
    tree = client.get(f"/api/projects/{project['id']}/tree").json()
    assert tree[0]["name"] == "新名"


def test_node_move_rejects_descendant(client: TestClient) -> None:
    """节点不能移动到自身后代。"""
    _register(client)
    project = _create_project(client, "移动")
    parent = client.post(f"/api/projects/{project['id']}/nodes", json={"name": "父"}).json()
    child = client.post(
        f"/api/projects/{project['id']}/nodes", json={"name": "子", "parent_id": parent["id"]}
    ).json()
    response = client.patch(
        f"/api/projects/{project['id']}/nodes/{parent['id']}",
        json={"parent_id": child["id"]},
    )
    assert response.status_code == 400


def test_node_delete_cascades(client: TestClient) -> None:
    """删除父节点应级联删除全部后代。"""
    _register(client)
    project = _create_project(client, "测试项目")
    parent = client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "父节点"},
    ).json()
    client.post(
        f"/api/projects/{project['id']}/nodes",
        json={"name": "子节点", "parent_id": parent["id"]},
    )

    response = client.delete(f"/api/projects/{project['id']}/nodes/{parent['id']}")

    assert response.status_code == 200
    assert client.get(f"/api/projects/{project['id']}/tree").json() == []


def test_reorder_persists(client: TestClient) -> None:
    """同级排序应持久化，树读取按新顺序返回。"""
    _register(client)
    project = _create_project(client, "测试项目")
    ids = [
        client.post(
            f"/api/projects/{project['id']}/nodes",
            json={"name": f"节点{i}"},
        ).json()["id"]
        for i in range(3)
    ]

    response = client.post(
        f"/api/projects/{project['id']}/nodes/reorder",
        json={"parent_id": None, "ordered_ids": [ids[2], ids[0], ids[1]]},
    )
    assert response.status_code == 200

    tree = client.get(f"/api/projects/{project['id']}/tree").json()
    assert [node["name"] for node in tree] == ["节点2", "节点0", "节点1"]


def test_reorder_rejects_incomplete_list(client: TestClient) -> None:
    """排序列表不完整应返回 400。"""
    _register(client)
    project = _create_project(client, "测试项目")
    ids = [
        client.post(
            f"/api/projects/{project['id']}/nodes",
            json={"name": f"节点{i}"},
        ).json()["id"]
        for i in range(2)
    ]

    response = client.post(
        f"/api/projects/{project['id']}/nodes/reorder",
        json={"parent_id": None, "ordered_ids": [ids[0]]},
    )

    assert response.status_code == 400


def test_delete_project_cascades(client: TestClient) -> None:
    """删除项目应级联删除全部节点。"""
    _register(client)
    project = _create_project(client, "房子装修", template="decoration")

    response = client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert client.get("/api/projects").json() == []
