"""模型 BYOK 配置与连接测试。"""

import uuid

import httpx
import pytest

from app.main import create_app
from app.schemas.ai_settings import ConnectionTestOut
from app.services.ai_models import get_text_model
from app.services.secret_store import MemorySecretStore


@pytest.fixture
async def client():
    """异步 API 客户端。"""
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


def test_memory_secret_store_roundtrip() -> None:
    """内存密钥存储应能写入、读取与删除，且不依赖系统钥匙串。"""
    store = MemorySecretStore()
    store.set("1:deepseek", "sk-1234567890")

    assert store.get("1:deepseek") == "sk-1234567890"
    store.delete("1:deepseek")
    assert store.get("1:deepseek") is None


@pytest.mark.asyncio
async def test_get_settings_returns_defaults(client: httpx.AsyncClient) -> None:
    """未配置时应返回默认 Provider 与模型名，且全部未配置。"""
    await _register(client)

    response = await client.get("/api/settings/ai")

    assert response.status_code == 200
    data = response.json()
    assert data["text_provider"] == "deepseek"
    assert data["text_model"] == "deepseek-chat"
    assert data["text_configured"] is False
    assert data["vision_provider"] == "doubao"
    assert data["vision_model"] == "doubao-seed-2-0-lite-260428"
    assert data["vision_configured"] is False


@pytest.mark.asyncio
async def test_save_text_key_is_masked(client: httpx.AsyncClient) -> None:
    """保存密钥后查询只返回尾号，绝不返回完整密钥。"""
    await _register(client)

    saved = await client.put(
        "/api/settings/ai/text",
        json={"api_key": "sk-1234567890abcd"},
    )
    assert saved.status_code == 200
    assert saved.json()["text_configured"] is True
    assert saved.json()["text_key_tail"] == "abcd"

    listed = await client.get("/api/settings/ai")
    assert "sk-1234567890abcd" not in listed.text
    assert listed.json()["text_key_tail"] == "abcd"


@pytest.mark.asyncio
async def test_clear_text_key(client: httpx.AsyncClient) -> None:
    """清除文本密钥后应回到未配置。"""
    await _register(client)
    await client.put("/api/settings/ai/text", json={"api_key": "sk-1234"})

    response = await client.delete("/api/settings/ai/text")

    assert response.status_code == 200
    assert response.json()["text_configured"] is False
    assert response.json()["text_key_tail"] is None


@pytest.mark.asyncio
async def test_vision_key_config(client: httpx.AsyncClient) -> None:
    """视觉密钥可配置并脱敏返回。"""
    await _register(client)

    response = await client.put(
        "/api/settings/ai/vision",
        json={"api_key": "ark-9876543210wxyz"},
    )

    assert response.status_code == 200
    assert response.json()["vision_configured"] is True
    assert response.json()["vision_key_tail"] == "wxyz"


@pytest.mark.asyncio
async def test_workspace_isolation(client: httpx.AsyncClient) -> None:
    """不同 Workspace 的密钥配置互不可见。"""
    await _register(client)
    await client.put("/api/settings/ai/text", json={"api_key": "sk-aaaa"})

    other_transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(
        transport=other_transport, base_url="http://test"
    ) as other:
        await _register(other)
        data = (await other.get("/api/settings/ai")).json()
        assert data["text_configured"] is False
        assert data["text_key_tail"] is None


@pytest.mark.asyncio
async def test_test_connection_updates_available(
    client: httpx.AsyncClient,
    monkeypatch,
) -> None:
    """测试连接成功应把对应配置标记为可用。"""
    await _register(client)
    await client.put("/api/settings/ai/text", json={"api_key": "sk-1234"})

    async def _fake_test(db, workspace_id):
        return ConnectionTestOut(ok=True, message="ok")

    monkeypatch.setattr("app.api.ai_settings.test_text_connection", _fake_test)
    response = await client.post("/api/settings/ai/text/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    data = (await client.get("/api/settings/ai")).json()
    assert data["text_available"] is True


@pytest.mark.asyncio
async def test_test_connection_requires_key(client: httpx.AsyncClient) -> None:
    """未配置密钥时测试连接应返回失败，不发起外部请求。"""
    await _register(client)

    response = await client.post("/api/settings/ai/text/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "未配置" in response.json()["message"]


@pytest.mark.asyncio
async def test_get_text_model_falls_back_offline(client: httpx.AsyncClient) -> None:
    """未配置密钥时应回退到离线确定性模型。"""
    await _register(client)
    me = await client.get("/api/me")
    workspace_id = me.json()["workspace"]["id"]

    # 通过当前请求上下文拿不到 db，改用单独会话直接调用服务。
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        model = await get_text_model(db, workspace_id)
        assert model.model_name == "offline"
