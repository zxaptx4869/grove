"""健康检查接口测试。"""

from fastapi.testclient import TestClient


def test_healthz_returns_200(client: TestClient) -> None:
    """GET /healthz 应返回 200 且 status 为 ok。"""
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["version"]
