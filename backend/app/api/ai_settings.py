"""模型设置 API：BYOK 密钥配置、脱敏查询与连接测试。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, get_current_workspace
from app.models import Workspace
from app.schemas.ai_settings import (
    AIProviderSettingsOut,
    ConnectionTestOut,
    EmbeddingProviderUpdate,
    TextProviderUpdate,
    VisionProviderUpdate,
)
from app.services.ai_models import (
    get_settings_row,
    test_text_connection,
    test_vision_connection,
)
from app.services.embedding import test_embedding_connection
from app.services.secret_store import get_secret_store, secret_key

router = APIRouter(prefix="/api/settings/ai", tags=["ai-settings"])
CurrentWorkspace = Annotated[Workspace, Depends(get_current_workspace)]


def _masked_out(row) -> AIProviderSettingsOut:
    """组装脱敏响应，绝不返回完整密钥。"""
    return AIProviderSettingsOut(
        text_provider=row.text_provider,
        text_model=row.text_model,
        text_configured=row.text_key_tail is not None,
        text_key_tail=row.text_key_tail,
        text_available=row.text_available,
        vision_provider=row.vision_provider,
        vision_model=row.vision_model,
        vision_configured=row.vision_key_tail is not None,
        vision_key_tail=row.vision_key_tail,
        vision_available=row.vision_available,
        embedding_provider=row.embedding_provider,
        embedding_model=row.embedding_model,
        embedding_configured=row.embedding_key_tail is not None,
        embedding_key_tail=row.embedding_key_tail,
        embedding_available=row.embedding_available,
    )


@router.get("", response_model=AIProviderSettingsOut)
async def get_ai_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """返回当前 Workspace 的脱敏模型配置。"""
    row = await get_settings_row(db, workspace.id)
    await db.commit()
    return _masked_out(row)


@router.put("/text", response_model=AIProviderSettingsOut)
async def save_text_settings(
    payload: TextProviderUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """保存文本模型密钥与可选模型名。"""
    row = await get_settings_row(db, workspace.id)
    store = get_secret_store()
    store.set(secret_key(workspace.id, row.text_provider), payload.api_key)
    if payload.model is not None:
        row.text_model = payload.model
    row.text_key_tail = payload.api_key[-4:]
    row.text_available = False
    await db.commit()
    return _masked_out(row)


@router.put("/vision", response_model=AIProviderSettingsOut)
async def save_vision_settings(
    payload: VisionProviderUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """保存视觉模型密钥与可选模型名。"""
    row = await get_settings_row(db, workspace.id)
    store = get_secret_store()
    store.set(secret_key(workspace.id, row.vision_provider), payload.api_key)
    if payload.model is not None:
        row.vision_model = payload.model
    row.vision_key_tail = payload.api_key[-4:]
    row.vision_available = False
    await db.commit()
    return _masked_out(row)


@router.delete("/text", response_model=AIProviderSettingsOut)
async def clear_text_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """清除文本模型密钥。"""
    row = await get_settings_row(db, workspace.id)
    get_secret_store().delete(secret_key(workspace.id, row.text_provider))
    row.text_key_tail = None
    row.text_available = False
    await db.commit()
    return _masked_out(row)


@router.delete("/vision", response_model=AIProviderSettingsOut)
async def clear_vision_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """清除视觉模型密钥。"""
    row = await get_settings_row(db, workspace.id)
    get_secret_store().delete(secret_key(workspace.id, row.vision_provider))
    row.vision_key_tail = None
    row.vision_available = False
    await db.commit()
    return _masked_out(row)


@router.put("/embedding", response_model=AIProviderSettingsOut)
async def save_embedding_settings(
    payload: EmbeddingProviderUpdate,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """保存 embedding 模型名；密钥复用豆包视觉密钥，不接收新密钥。"""
    row = await get_settings_row(db, workspace.id)
    if payload.model is not None:
        row.embedding_model = payload.model
    # 复用豆包视觉密钥尾号作为已配置标记；视觉未配置时 embedding 保持未配置
    row.embedding_key_tail = row.vision_key_tail
    row.embedding_available = False
    await db.commit()
    return _masked_out(row)


@router.post("/embedding/test", response_model=ConnectionTestOut)
async def test_embedding_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ConnectionTestOut:
    """测试 embedding 连接并更新可用状态。"""
    result = await test_embedding_connection(db, workspace.id)
    row = await get_settings_row(db, workspace.id)
    row.embedding_available = result.ok
    if result.ok and row.embedding_key_tail is None:
        row.embedding_key_tail = row.vision_key_tail
    await db.commit()
    return result


@router.delete("/embedding", response_model=AIProviderSettingsOut)
async def clear_embedding_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> AIProviderSettingsOut:
    """停用 embedding，语义功能退回确定性链路。"""
    row = await get_settings_row(db, workspace.id)
    row.embedding_key_tail = None
    row.embedding_available = False
    await db.commit()
    return _masked_out(row)


@router.post("/text/test", response_model=ConnectionTestOut)
async def test_text_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ConnectionTestOut:
    """测试文本模型连接并更新可用状态。"""
    result = await test_text_connection(db, workspace.id)
    row = await get_settings_row(db, workspace.id)
    row.text_available = result.ok
    await db.commit()
    return result


@router.post("/vision/test", response_model=ConnectionTestOut)
async def test_vision_settings(
    db: DbSession,
    workspace: CurrentWorkspace,
) -> ConnectionTestOut:
    """测试视觉模型连接并更新可用状态。"""
    result = await test_vision_connection(db, workspace.id)
    row = await get_settings_row(db, workspace.id)
    row.vision_available = result.ok
    await db.commit()
    return result
