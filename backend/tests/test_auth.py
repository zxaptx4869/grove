"""认证与 Workspace 隔离测试。"""

import uuid

from fastapi.testclient import TestClient

from app.main import create_app


def _username(prefix: str = "user") -> str:
    """生成唯一测试账号，避免重复运行冲突。"""
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _register(client: TestClient, username: str, password: str = "password123") -> TestClient:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert response.status_code == 201
    return client


def test_register_creates_session_cookie(client: TestClient) -> None:
    """注册成功应返回带安全属性的会话 Cookie。"""
    username = _username()
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )

    assert response.status_code == 201
    assert response.json()["username"] == username
    set_cookie = response.headers.get("set-cookie", "")
    assert "grove_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_register_duplicate_username_conflict(client: TestClient) -> None:
    """重复账号注册应返回 409。"""
    username = _username()
    _register(client, username)

    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123"},
    )

    assert response.status_code == 409


def test_login_wrong_password_unauthorized(client: TestClient) -> None:
    """错误密码登录应返回 401。"""
    username = _username()
    _register(client, username)

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_me_requires_auth(client: TestClient) -> None:
    """未登录访问受保护接口应返回 401。"""
    response = client.get("/api/me")
    assert response.status_code == 401


def test_register_then_me_returns_workspace(client: TestClient) -> None:
    """注册即登录，/api/me 应返回用户与其默认 Workspace。"""
    username = _username()
    _register(client, username)

    response = client.get("/api/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["username"] == username
    assert payload["workspace"]["id"]
    assert payload["workspace"]["name"] == f"{username} 的空间"


def test_logout_invalidates_session(client: TestClient) -> None:
    """登出后原会话应失效。"""
    username = _username()
    _register(client, username)

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    me = client.get("/api/me")
    assert me.status_code == 401


def test_workspace_isolation_between_users() -> None:
    """两个用户各自拥有独立 Workspace，互不可见。"""
    client_a = TestClient(create_app())
    client_b = TestClient(create_app())

    with client_a, client_b:
        _register(client_a, _username("alice"))
        _register(client_b, _username("bob"))

        me_a = client_a.get("/api/me")
        me_b = client_b.get("/api/me")

        workspace_a = me_a.json()["workspace"]["id"]
        workspace_b = me_b.json()["workspace"]["id"]
        assert workspace_a != workspace_b


def test_mobile_login_and_logout_revokes_bearer_session(client: TestClient) -> None:
    """移动 Token 可访问业务接口，登出后会被撤销。"""
    username = _username()
    register = client.post(
        "/api/auth/mobile/register", json={"username": username, "password": "password123"}
    )
    assert register.status_code == 201
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/me", headers=headers).status_code == 200
    assert client.post("/api/auth/mobile/logout", headers=headers).status_code == 200
    assert client.get("/api/me", headers=headers).status_code == 401


def test_invalid_bearer_does_not_fall_back_to_cookie(client: TestClient) -> None:
    """携带 Bearer 时必须严格优先，避免错误降级至 Cookie。"""
    _register(client, _username())
    response = client.get("/api/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401


def test_mobile_bearer_preserves_workspace_isolation() -> None:
    """移动会话只能读取自身 Workspace 的项目。"""
    client_a = TestClient(create_app())
    client_b = TestClient(create_app())
    with client_a, client_b:
        first = client_a.post(
            "/api/auth/mobile/register",
            json={"username": _username("mobile_a"), "password": "password123"},
        )
        second = client_b.post(
            "/api/auth/mobile/register",
            json={"username": _username("mobile_b"), "password": "password123"},
        )
        first_headers = {"Authorization": f"Bearer {first.json()['token']}"}
        second_headers = {"Authorization": f"Bearer {second.json()['token']}"}
        project = client_a.post("/api/projects", headers=first_headers, json={"name": "仅自己可见"})
        assert project.status_code == 201
        assert client_b.get("/api/projects", headers=second_headers).json() == []
