"""模型设置请求/响应模型。"""

from pydantic import BaseModel, Field


class AIProviderSettingsOut(BaseModel):
    """当前 Workspace 的脱敏模型配置。"""

    text_provider: str
    text_model: str
    text_configured: bool
    text_key_tail: str | None
    text_available: bool
    vision_provider: str
    vision_model: str
    vision_configured: bool
    vision_key_tail: str | None
    vision_available: bool
    embedding_provider: str
    embedding_model: str
    embedding_configured: bool
    embedding_key_tail: str | None
    embedding_available: bool


class TextProviderUpdate(BaseModel):
    """保存文本模型密钥；模型名可选覆盖。"""

    api_key: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)


class VisionProviderUpdate(BaseModel):
    """保存视觉模型密钥；模型名可选覆盖。"""

    api_key: str = Field(min_length=1, max_length=512)
    model: str | None = Field(default=None, min_length=1, max_length=128)


class EmbeddingProviderUpdate(BaseModel):
    """保存 embedding 模型名；密钥复用豆包视觉密钥。"""

    model: str | None = Field(default=None, min_length=1, max_length=128)


class ConnectionTestOut(BaseModel):
    """模型连接测试结果。"""

    ok: bool
    message: str
