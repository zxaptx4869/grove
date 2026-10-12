"""响应时间口径契约：全部 schema 继承 ApiModel，datetime 统一 UTC 带偏移输出。

前提：数据库按 UTC 写入（开发 SQLite 的 CURRENT_TIMESTAMP 与生产 MySQL 已核对的
存量值），驱动返回的是不带偏移的 naïve datetime，因此 naïve 值按 UTC 解释。
"""

import importlib
import logging
import pkgutil
from datetime import datetime, timedelta, timezone, tzinfo

import pydantic
import pytest

import app.schemas
from app.schemas.base import ApiModel


def _schema_models() -> list[type[pydantic.BaseModel]]:
    """收集 app.schemas 各模块里定义的模型类。"""
    models: list[type[pydantic.BaseModel]] = []
    for module_info in pkgutil.iter_modules(app.schemas.__path__):
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, pydantic.BaseModel)
                and value.__module__ == module.__name__
            ):
                models.append(value)
    return models


class _Probe(ApiModel):
    """测试用模型：模拟响应模型新增时间字段的场景。"""

    created_at: datetime
    updated_at: datetime | None = None
    stamps: list[datetime] = []
    labels: dict[str, datetime] = {}


class _ProbeChild(ApiModel):
    created_at: datetime


class _ProbeParent(ApiModel):
    child: _ProbeChild
    children: list[_ProbeChild] = []


class _BoomTz(tzinfo):
    """时区信息在归一化时抛错，用于验证异常可观测。"""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        raise RuntimeError("时区信息不可用")

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str:
        return "boom"


def test_every_schema_model_inherits_api_model() -> None:
    """新增 schema 模型必须继承 ApiModel，否则时间口径会漏出裸串。"""
    models = _schema_models()
    assert models, "未收集到任何 schema 模型，测试本身失效"
    missing = [model.__name__ for model in models if not issubclass(model, ApiModel)]
    assert missing == []


def test_naive_datetime_is_serialized_as_utc_with_offset() -> None:
    """不带时区的值按 UTC 解释，JSON 输出带 Z。"""
    payload = _Probe(created_at=datetime(2026, 9, 29, 7, 23, 51)).model_dump(mode="json")

    assert payload["created_at"] == "2026-09-29T07:23:51Z"


def test_offset_datetime_is_converted_to_utc() -> None:
    """带偏移的值换算为同一时刻的 UTC。"""
    aware = datetime(2026, 9, 29, 15, 23, 51, tzinfo=timezone(timedelta(hours=8)))

    payload = _Probe(created_at=aware).model_dump(mode="json")

    assert payload["created_at"] == "2026-09-29T07:23:51Z"


def test_string_datetime_is_normalized_too() -> None:
    """直接以字符串给出的时间同样归一化（兼容驱动或序列化层透传字符串）。"""
    payload = _Probe(created_at="2026-09-29T07:23:51").model_dump(mode="json")

    assert payload["created_at"] == "2026-09-29T07:23:51Z"


def test_python_mode_dump_keeps_aware_datetime() -> None:
    """python 模式 dump 仍是 datetime 对象（带 UTC），内部逻辑不受影响。"""
    dumped = _Probe(created_at=datetime(2026, 9, 29, 7, 23, 51)).model_dump()

    assert isinstance(dumped["created_at"], datetime)
    assert dumped["created_at"].utcoffset() == timedelta(0)


def test_container_and_nested_fields_are_normalized() -> None:
    """容器与嵌套模型里的时间字段同样归一化。"""
    parent = _ProbeParent(
        child=_ProbeChild(created_at=datetime(2026, 9, 29, 7, 23, 51)),
        children=[_ProbeChild(created_at=datetime(2026, 9, 29, 8, 0, 0))],
    )

    payload = parent.model_dump(mode="json")

    assert payload["child"]["created_at"] == "2026-09-29T07:23:51Z"
    assert payload["children"][0]["created_at"] == "2026-09-29T08:00:00Z"


def test_list_and_dict_datetimes_are_normalized() -> None:
    """list / dict 字段里的 datetime 也被归一化。"""
    payload = _Probe(
        created_at=datetime(2026, 9, 29, 7, 23, 51),
        stamps=[datetime(2026, 9, 29, 1, 0, 0)],
        labels={"a": datetime(2026, 9, 29, 2, 0, 0)},
    ).model_dump(mode="json")

    assert payload["stamps"] == ["2026-09-29T01:00:00Z"]
    assert payload["labels"] == {"a": "2026-09-29T02:00:00Z"}


def test_normalization_failure_is_logged_and_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """归一化失败必须留下 warning 日志并向上抛出，不静默返回裸值。"""
    broken = datetime(2026, 9, 29, 7, 23, 51, tzinfo=_BoomTz())

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError):
        _Probe(created_at=broken)

    assert any("时间字段归一化失败" in record.message for record in caplog.records)


def test_unparsable_value_raises_validation_error() -> None:
    """无法解析为时间的值必须校验失败，并保留字段路径。"""
    with pytest.raises(pydantic.ValidationError) as excinfo:
        _Probe(created_at="不是时间")

    assert "created_at" in str(excinfo.value)


def test_openapi_keeps_datetime_format() -> None:
    """口径收口不把 OpenAPI 的 date-time 格式退化成纯字符串。"""
    properties = _Probe.model_json_schema()["properties"]

    assert properties["created_at"]["format"] == "date-time"
