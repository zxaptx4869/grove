"""安全工具：密码哈希与会话令牌。"""

import hashlib
import secrets

from argon2 import PasswordHasher

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """使用 argon2id 生成密码哈希。"""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码；任何失败均返回 False，避免时序与异常泄露。"""
    try:
        return _password_hasher.verify(password_hash, password)
    except Exception:
        return False


def generate_session_token() -> str:
    """生成 256 位随机会话令牌（放入 Cookie）。"""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """会话令牌入库前做 SHA-256 哈希。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
