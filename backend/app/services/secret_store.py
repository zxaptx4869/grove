"""密钥安全存储抽象：默认系统钥匙串，测试使用内存实现。"""

from abc import ABC, abstractmethod
from functools import lru_cache

import keyring
from keyring.errors import PasswordDeleteError

from app.core.config import get_settings


class SecretStore(ABC):
    """保存第三方模型密钥的存储接口，数据库不落明文。"""

    @abstractmethod
    def get(self, key: str) -> str | None:
        """读取密钥；不存在返回 None。"""

    @abstractmethod
    def set(self, key: str, value: str) -> None:
        """写入或覆盖密钥。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除密钥；不存在时静默成功。"""


class KeychainSecretStore(SecretStore):
    """macOS Keychain / Windows Credential Manager 等系统钥匙串实现。"""

    service_name = "grove-ai"

    def get(self, key: str) -> str | None:
        return keyring.get_password(self.service_name, key)

    def set(self, key: str, value: str) -> None:
        keyring.set_password(self.service_name, key, value)

    def delete(self, key: str) -> None:
        try:
            keyring.delete_password(self.service_name, key)
        except PasswordDeleteError:
            pass


class MemorySecretStore(SecretStore):
    """进程内内存实现，仅用于测试。"""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)


@lru_cache
def get_secret_store() -> SecretStore:
    """按配置返回密钥存储；测试环境使用内存实现。"""
    settings = get_settings()
    if settings.secret_store == "memory":
        return MemorySecretStore()
    return KeychainSecretStore()


def secret_key(workspace_id: int, provider: str) -> str:
    """构造密钥存储的命名空间键，按 Workspace 与 Provider 隔离。"""
    return f"{workspace_id}:{provider}"
