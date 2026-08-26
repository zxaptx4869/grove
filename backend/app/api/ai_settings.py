"""模型设置 API：BYOK 密钥配置、脱敏查询与连接测试。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, get_current_workspace
from app.models import Project, Workspace
from app.schemas.ai_settings import (
    AIProviderSettingsOut,
    ConnectionTestOut,
    EmbeddingIndexStatusOut,
    EmbeddingProviderUpdate,
    EmbeddingRebuildRequest,
    TextProviderUpdate,
    VisionProviderUpdate,
)
from app.services.ai_models import (
    get_settings_row,
    test_text_connection,
    test_vision_connection,
)
from app.services.embedding import (
    get_embedding_index_status,
    probe_embedding_model,
    rebuild_all_embeddings,
    retry_failed_embeddings,
    test_embedding_connection,
)
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
        embedding_tested=row.embedding_tested,
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
    model_changed = False
    if payload.model is not None:
        model_changed = payload.model != row.embedding_model
        if model_changed:
            # 切换前先用新模型做探针：不可用则拒绝切换，保留旧配置与旧索引
            probe = await probe_embedding_model(db, workspace.id, payload.model)
            if not probe.ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"新模型不可用，未切换，旧索引已保留：{probe.message}",
                )
            row.embedding_model = payload.model
    # 复用豆包视觉密钥尾号作为已配置标记；视觉未配置时 embedding 保持未配置
    row.embedding_key_tail = row.vision_key_tail
    row.embedding_available = model_changed
    row.embedding_tested = model_changed
    if model_changed:
        # 换模型后向量空间不同：删除旧向量并按新模型全量重建，避免混用与重复行
        await rebuild_all_embeddings(db, workspace.id)
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
    row.embedding_tested = True
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
    row.embedding_tested = False
    await db.commit()
    return _masked_out(row)


async def _owned_project_or_404(
    db: DbSession,
    workspace: Workspace,
    project_id: int,
) -> Project:
    """校验项目属于当前 Workspace，否则 404。"""
    project = await db.get(Project, project_id)
    if project is None or project.workspace_id != workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.get("/embedding/index-status", response_model=EmbeddingIndexStatusOut)
async def embedding_index_status_endpoint(
    db: DbSession,
    workspace: CurrentWorkspace,
    project_id: int | None = None,
) -> EmbeddingIndexStatusOut:
    """返回当前 Workspace 或指定项目的语义索引状态。"""
    if project_id is not None:
        await _owned_project_or_404(db, workspace, project_id)
    result = await get_embedding_index_status(db, workspace.id, project_id)
    await db.commit()
    return result


@router.post("/embedding/rebuild", response_model=EmbeddingIndexStatusOut)
async def embedding_rebuild_endpoint(
    payload: EmbeddingRebuildRequest,
    db: DbSession,
    workspace: CurrentWorkspace,
) -> EmbeddingIndexStatusOut:
    """重试失败项或全量重建向量。"""
    if payload.project_id is not None:
        await _owned_project_or_404(db, workspace, payload.project_id)
    if payload.mode == "all":
        # 全量重建会清空旧向量，先验证当前模型可用再动手
        settings_row = await get_settings_row(db, workspace.id)
        probe = await probe_embedding_model(db, workspace.id, settings_row.embedding_model)
        if not probe.ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"当前模型不可用，未重建，旧索引保留：{probe.message}",
            )
        await rebuild_all_embeddings(db, workspace.id, payload.project_id)
    else:
        await retry_failed_embeddings(db, workspace.id, payload.project_id)
    await db.commit()
    return await get_embedding_index_status(db, workspace.id, payload.project_id)


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
