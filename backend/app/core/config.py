"""应用配置：基于 pydantic-settings 的统一配置入口。

所有环境变量集中在这里定义；密钥类键位在本骨架阶段只保留占位，
真实接入（AI、认证）由后续 change 填充。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Grove 后端配置。

    读取顺序：环境变量 > backend/.env > 默认值。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 应用信息
    app_name: str = "知林 Grove 后端"
    app_version: str = "0.1.0"

    # 数据库：开发默认 SQLite；生产通过环境变量切换 MySQL 8
    database_url: str = "sqlite+aiosqlite:///./grove.db"

    # 允许跨域的前端来源（逗号分隔）
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # AI 供应商：demo（默认）/ deepseek / doubao
    ai_provider: str = Field(default="demo", description="AI 供应商标识")

    # 处理 Provider：demo（默认）/ 其他占位
    processing_provider: str = Field(default="demo", description="处理 Provider 标识")

    # 进程内处理 Worker：应用启动时是否开启（测试环境可关闭）
    processing_worker_enabled: bool = Field(default=True, description="是否启用处理 Worker")

    # 附件存储目录：默认相对 backend 运行目录，由存储服务解析
    attachment_dir: str = Field(default="uploads", description="本地附件存储目录")

    # ---- 会话与 Cookie ----
    session_cookie_name: str = Field(default="grove_session", description="会话 Cookie 名称")
    session_max_age_days: int = Field(default=30, description="会话有效期（天）")
    cookie_secure: bool = Field(default=False, description="生产环境置 True，Cookie 仅 HTTPS 传输")

    # ---- 占位键：真实接入时填充，骨架阶段不连接外部服务 ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    doubao_api_key: str = ""
    doubao_base_url: str = ""
    auth_secret_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        """将逗号分隔的前端来源解析为列表。"""
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()
