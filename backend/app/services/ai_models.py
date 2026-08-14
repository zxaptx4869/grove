"""模型服务层：按 Workspace 配置返回 PydanticAI 模型，并提供连接测试。"""

import struct
import zlib

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryImage
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AIProviderSettings
from app.schemas.ai_settings import ConnectionTestOut
from app.services.secret_store import get_secret_store, secret_key


class _ConnectionPong(BaseModel):
    """连接测试的最小结构化输出。"""

    reply: str


def _make_test_png(width: int = 16, height: int = 16) -> bytes:
    """生成一张不包含用户内容的纯色 PNG，满足视觉模型的最小尺寸要求。"""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + b"\xff\xff\xff\xff" * width
    idat = zlib.compress(row * height)
    return (
        signature
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


# 视觉连接测试用图片，不包含用户内容。
_TEST_PNG = _make_test_png()


def _offline_model() -> Model:
    """离线确定性测试模型，不访问外部 API。"""
    return TestModel(model_name="offline")


async def get_settings_row(db: AsyncSession, workspace_id: int) -> AIProviderSettings:
    """读取当前 Workspace 的模型配置，不存在时惰性建行。"""
    row = (
        await db.execute(
            select(AIProviderSettings).where(AIProviderSettings.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = AIProviderSettings(workspace_id=workspace_id)
        db.add(row)
        await db.flush()
    return row


async def get_text_secret(db: AsyncSession, workspace_id: int) -> str | None:
    """读取当前 Workspace 的文本模型密钥；未配置返回 None。"""
    row = await get_settings_row(db, workspace_id)
    return get_secret_store().get(secret_key(workspace_id, row.text_provider))


async def get_vision_secret(db: AsyncSession, workspace_id: int) -> str | None:
    """读取当前 Workspace 的视觉模型密钥；未配置返回 None。"""
    row = await get_settings_row(db, workspace_id)
    return get_secret_store().get(secret_key(workspace_id, row.vision_provider))


async def get_text_model(db: AsyncSession, workspace_id: int) -> Model:
    """返回文本模型；未配置密钥时回退到离线测试模型。"""
    row = await get_settings_row(db, workspace_id)
    secret = get_secret_store().get(secret_key(workspace_id, row.text_provider))
    if not secret:
        return _offline_model()
    return OpenAIChatModel(row.text_model, provider=DeepSeekProvider(api_key=secret))


async def get_vision_model(db: AsyncSession, workspace_id: int) -> Model:
    """返回视觉模型；未配置密钥时回退到离线测试模型。"""
    settings = get_settings()
    row = await get_settings_row(db, workspace_id)
    secret = get_secret_store().get(secret_key(workspace_id, row.vision_provider))
    if not secret:
        return _offline_model()
    return OpenAIChatModel(
        row.vision_model,
        provider=OpenAIProvider(base_url=settings.doubao_base_url, api_key=secret),
    )


async def test_text_connection(db: AsyncSession, workspace_id: int) -> ConnectionTestOut:
    """用最小文本补全测试 DeepSeek 连接。"""
    secret = await get_text_secret(db, workspace_id)
    if not secret:
        return ConnectionTestOut(ok=False, message="未配置文本模型密钥")
    row = await get_settings_row(db, workspace_id)
    model: Model = OpenAIChatModel(row.text_model, provider=DeepSeekProvider(api_key=secret))
    return await _run_connection_test(model, "请只回复 ok")


async def test_vision_connection(db: AsyncSession, workspace_id: int) -> ConnectionTestOut:
    """用最小图片理解测试豆包视觉连接。"""
    settings = get_settings()
    secret = await get_vision_secret(db, workspace_id)
    if not secret:
        return ConnectionTestOut(ok=False, message="未配置视觉模型密钥")
    row = await get_settings_row(db, workspace_id)
    model: Model = OpenAIChatModel(
        row.vision_model,
        provider=OpenAIProvider(base_url=settings.doubao_base_url, api_key=secret),
    )
    image = BinaryImage(data=_TEST_PNG, media_type="image/png")
    return await _run_connection_test(model, "请只回复 ok", image)


async def _run_connection_test(
    model: Model,
    prompt: str,
    image: BinaryImage | None = None,
) -> ConnectionTestOut:
    """执行一次最小连接测试，成功返回结构化回复。"""
    agent = Agent(model, output_type=_ConnectionPong, system_prompt="连接测试")
    try:
        content = [prompt, image] if image is not None else [prompt]
        result = await agent.run(content)
        reply = result.output.reply if result.output else "ok"
        return ConnectionTestOut(ok=True, message=reply)
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestOut(ok=False, message=str(exc))
