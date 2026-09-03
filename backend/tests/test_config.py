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


def test_composite_answer_defaults_are_bounded_and_disabled(monkeypatch) -> None:
    """复合回答默认关闭，计划与执行预算保持有界。"""
    monkeypatch.delenv("KNOWLEDGE_AGENT_COMPOSITE_ANSWER_ENABLED", raising=False)
    settings = Settings()

    assert settings.knowledge_agent_composite_answer_enabled is False
    assert settings.knowledge_agent_composite_answer_max_requirements == 8
    assert settings.knowledge_agent_composite_answer_max_retrieval_requests == 3
    assert settings.knowledge_agent_composite_answer_max_structured_requests == 2
    assert settings.knowledge_agent_composite_answer_plan_bytes_limit < 65535
    assert settings.knowledge_agent_composite_answer_execution_bytes_limit < 65535


def test_composite_answer_budget_validation() -> None:
    """明显越界的本地配置在启动时直接失败，不留下无界入口。"""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(knowledge_agent_composite_answer_max_requirements=0)
    with pytest.raises(ValidationError):
        Settings(knowledge_agent_composite_answer_execution_bytes_limit=65000)
