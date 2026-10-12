"""对外 schema 基类：统一时间序列化口径。

后端所有 `created_at` / `updated_at` 都由数据库按 UTC 写入（开发 SQLite 的
`CURRENT_TIMESTAMP` 与生产 MySQL 已核对的存量值都是 UTC），但 SQLite 与 MySQL
驱动取回来的是不带偏移的 naïve `datetime`，直接序列化会输出裸串，客户端只能各自
补 Z 兜底。这里把「naive 值按 UTC 解释、统一输出 UTC 带偏移」收在一处，新增字段
自动同口径。
"""

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator

logger = logging.getLogger(__name__)


def normalize_utc(value: datetime) -> datetime:
    """把 datetime 归一化到 UTC：naive 值按 UTC 解释，带偏移值换算为 UTC。"""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_utc_values(value: Any) -> Any:
    """递归归一化容器里的 datetime；没有 datetime 的值原样返回。"""
    if isinstance(value, datetime):
        return normalize_utc(value)
    if isinstance(value, list):
        return [normalize_utc_values(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_utc_values(item) for item in value)
    if isinstance(value, dict):
        return {key: normalize_utc_values(item) for key, item in value.items()}
    return value


class ApiModel(BaseModel):
    """全部对外 schema 的基类（请求与响应）。

    时间字段在输出前归一化到 UTC，JSON 串统一带 `Z`；python 模式 dump 仍是带
    UTC 的 `datetime`，不影响内部逻辑。归一化异常先记 warning 日志再向上抛出，
    不静默返回裸串或错误值。
    """

    @field_validator("*", mode="after")
    @classmethod
    def _normalize_datetime_fields(cls, value: Any, info: ValidationInfo) -> Any:
        try:
            return normalize_utc_values(value)
        except Exception:
            logger.warning(
                "时间字段归一化失败，按失败处理：字段=%s 值=%r",
                info.field_name,
                value,
                exc_info=True,
            )
            raise
