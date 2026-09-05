"""知识 Agent 一次覆盖缺口补查的闭合模型候选。"""

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.agents.composite_answer import (
    CompositeRetrievalRequestDraft,
    CompositeStructuredRequestDraft,
)
from app.core.config import get_settings
from app.models.knowledge_agent import PURPOSE_COVERAGE_REPAIR_PLAN
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

COVERAGE_REPAIR_PLAN_PROMPT_VERSION = "v2"


class StrictCoverageRepairDraft(BaseModel):
    """模型候选不得夹带范围、节点或写操作字段。"""

    model_config = ConfigDict(extra="forbid")


class CoverageRepairPlanDraft(StrictCoverageRepairDraft):
    """只引用既有 requirement id 并提出新只读请求。"""

    schema_version: Literal["v1"] = "v1"
    target_requirement_ids: list[str] = Field(default_factory=list, max_length=8)
    retrieval_requests: list[CompositeRetrievalRequestDraft] = Field(
        default_factory=list, max_length=4
    )
    structured_requests: list[CompositeStructuredRequestDraft] = Field(
        default_factory=list, max_length=2
    )
    reason: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def validate_request_targets(self):
        targets = set(self.target_requirement_ids)
        request_targets = [
            item
            for request in [*self.retrieval_requests, *self.structured_requests]
            for item in request.requirement_ids
        ]
        if any(item not in targets for item in request_targets):
            raise ValueError("补查请求引用了未声明的目标义务")
        return self


COVERAGE_REPAIR_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的一次覆盖缺口补查规划器。首次回答计划"
    "已经固化，你只能针对服务端列出的可修复 requirement id 提出最多一"
    "份有界只读补查候选，不回答问题，不修改首次计划。\n"
    "你不能新增、删除、重排或改写回答义务，不能改变依据策略。"
    "target_requirement_ids 和每份请求的 requirement_ids 只能选自可修复 id。\n"
    "普通知识补查只用 retrieval_requests；统计、分组、排序或有界列表只用"
    "structured_requests，其 EntrySetSpec 和 outputs 必须遵守 Grove 现有 B1 闭合"
    "协议。候选必须在输入预算内。\n"
    "同一统计义务必须保留首次类型、性质、时间过滤，不能扩大条件增加数量；"
    "只能在原口径内改写语义表达。阅读已执行 parameters/facts 避免重复或误解结果。\n"
    "不要重复已执行请求；如果闭合工具内没有可能增加依据的新请求，"
    "返回空 target 和空请求列表。\n"
    "绝对不要输出 owner、Workspace、项目、目录、Entry、Source 或其他对象 id，"
    "不要输出 SQL、正则、外部搜索、未知工具、写操作、节点/依赖/指纹、"
    "预算或第二轮计划。"
)


def _model_name(text_model) -> str:
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


async def run_coverage_repair_planner(
    db,
    workspace_id: int,
    *,
    current_message: str,
    requirements: list[dict],
    eligible_requirement_ids: list[str],
    executed_inputs: list[dict],
    budget: dict,
    now: datetime | None = None,
) -> tuple[CoverageRepairPlanDraft | None, StageMeta]:
    """最多运行一次补查 planner；失败返回真实 fallback。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return None, StageMeta(
            purpose=PURPOSE_COVERAGE_REPAIR_PLAN,
            provider="offline",
            model=None,
            is_fallback=True,
            error="未配置文本模型密钥",
            duration_ms=int((perf_counter() - started) * 1000),
        )
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    context = "\n".join(
        [
            f"用户原始问题：{current_message}",
            f"当前 UTC 时间：{current.astimezone(UTC).isoformat()}",
            f"不可变回答义务：{json.dumps(requirements, ensure_ascii=False)}",
            f"可修复 requirement id：{json.dumps(eligible_requirement_ids)}",
            f"首次已执行输入：{json.dumps(executed_inputs, ensure_ascii=False)}",
            f"补查冻结预算：{json.dumps(budget, ensure_ascii=False)}",
            "请输出 CoverageRepairPlan v1 候选。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=CoverageRepairPlanDraft,
        system_prompt=COVERAGE_REPAIR_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_coverage_repair_planner_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("覆盖补查规划模型调用失败：%s", exc)
        return None, StageMeta(
            purpose=PURPOSE_COVERAGE_REPAIR_PLAN,
            provider="llm",
            model=model_name,
            is_fallback=True,
            error=f"模型调用失败：{exc}",
            duration_ms=duration,
        )
    usage = asdict(result.usage)
    if result.output is None:
        return None, StageMeta(
            purpose=PURPOSE_COVERAGE_REPAIR_PLAN,
            provider="llm",
            model=model_name,
            is_fallback=True,
            error="模型未返回结构化结果",
            duration_ms=duration,
            usage=usage,
        )
    return result.output, StageMeta(
        purpose=PURPOSE_COVERAGE_REPAIR_PLAN,
        provider="llm",
        model=model_name,
        is_fallback=False,
        error=None,
        duration_ms=duration,
        usage=usage,
    )
