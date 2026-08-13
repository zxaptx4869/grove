"""配置模块测试。"""

from app.core.config import Settings


def test_default_database_url_is_sqlite(monkeypatch) -> None:
    """未配置环境变量时，DATABASE_URL 应使用默认 SQLite 连接串。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = Settings()
    assert settings.database_url == "sqlite+aiosqlite:///./grove.db"


def test_cors_origin_list_parsing() -> None:
    """逗号分隔的前端来源应解析为列表。"""
    settings = Settings(frontend_origins="http://a.test, http://b.test")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
