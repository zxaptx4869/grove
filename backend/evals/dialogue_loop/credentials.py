"""实验 demo 密码的系统钥匙串适配。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

DEMO_PASSWORD_PROVIDER = "dialogue-loop-demo-password"


class SecretStoreLike(Protocol):
    """仅声明实验需要的密钥存储操作，便于无钥匙串测试。"""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...


def _default_store_and_key(workspace_id: int) -> tuple[SecretStoreLike, str]:
    # 延迟导入，避免隔离子进程在设置副本 DATABASE_URL 前加载应用配置。
    from app.services.secret_store import get_secret_store, secret_key

    return get_secret_store(), secret_key(workspace_id, DEMO_PASSWORD_PROVIDER)


def _store_and_key(
    workspace_id: int, store: SecretStoreLike | None
) -> tuple[SecretStoreLike, str]:
    if store is None:
        return _default_store_and_key(workspace_id)
    return store, f"{workspace_id}:{DEMO_PASSWORD_PROVIDER}"


def load_demo_password(
    workspace_id: int, *, store: SecretStoreLike | None = None
) -> tuple[str | None, str | None]:
    """读取密码；钥匙串错误只返回类型，不暴露异常中的敏感内容。"""
    backend, key = _store_and_key(workspace_id, store)
    try:
        password = backend.get(key)
    except Exception as exc:
        return None, f"系统钥匙串读取失败（{type(exc).__name__}）"
    return (password or None), None


def password_for_run(
    workspace_id: int,
    *,
    prompt: Callable[[str], str],
    store: SecretStoreLike | None = None,
) -> tuple[str, bool, str | None]:
    """优先读取钥匙串，缺失或失败时才隐藏询问。"""
    password, error = load_demo_password(workspace_id, store=store)
    if password is not None:
        return password, True, None
    return prompt("demo 密码（仅内存传递，不写入报告）："), False, error


def save_demo_password(
    workspace_id: int, password: str, *, store: SecretStoreLike | None = None
) -> None:
    """将已验证密码保存到 Workspace 专用钥匙串项。"""
    if not password:
        raise ValueError("demo 密码不能为空")
    backend, key = _store_and_key(workspace_id, store)
    backend.set(key, password)


def delete_demo_password(workspace_id: int, *, store: SecretStoreLike | None = None) -> None:
    """删除 Workspace 专用钥匙串项。"""
    backend, key = _store_and_key(workspace_id, store)
    backend.delete(key)
