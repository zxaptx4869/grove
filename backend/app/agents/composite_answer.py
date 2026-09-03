"""知识 Agent quick 复合回答规划器与闭合候选协议。

本模块中的类型只描述模型可以提出的候选回答义务和只读输入请求，不包含
owner、Workspace、项目、目录或知识对象标识。服务端规范化结果才可执行。
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.agents.structured_query import EntrySetSpecDraft, StructuredQueryOutputDraft
from app.core.config import get_settings
from app.models.knowledge_agent import PURPOSE_COMPOSITE_ANSWER_PLAN
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

COMPOSITE_ANSWER_PLAN_PROMPT_VERSION = "v1"

CompositeRequirementKind = Literal[
    "explain",
    "retrieve",
    "aggregate",
    "compare",
    "recommend",
    "other",
]
CompositeBasisPolicy = Literal[
    "grove_only",
    "grove_required",
    "model_allowed",
    "external_required",
]


class StrictCompositeDraft(BaseModel):
    """所有模型可控复合规划类型都拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class CompositeRequirementDraft(StrictCompositeDraft):
    """一个待回答义务，不直接等同于工具调用。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    order: int = Field(ge=0, le=99)
    summary: str = Field(min_length=1, max_length=300)
    kind: CompositeRequirementKind
    basis_policy: CompositeBasisPolicy


class CompositeRetrievalRequestDraft(StrictCompositeDraft):
    """有界 Grove 语义检索输入候选。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=500)
    requirement_ids: list[str] = Field(min_length=1, max_length=8)


class CompositeStructuredRequestDraft(StrictCompositeDraft):
    """复用 B1 EntrySetSpec 与输出的结构化输入候选。"""

    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    entry_set: EntrySetSpecDraft = Field(default_factory=EntrySetSpecDraft)
    outputs: list[StructuredQueryOutputDraft] = Field(min_length=1, max_length=3)
    requirement_ids: list[str] = Field(min_length=1, max_length=8)


class CompositeAnswerPlanDraft(StrictCompositeDraft):
    """CompositeAnswerPlan v1 模型候选；应用层会再次严格校验。"""

    schema_version: Literal["v1"] = "v1"
    requirements: list[CompositeRequirementDraft] = Field(min_length=1, max_length=8)
    statement_message_ids: list[int] = Field(default_factory=list, max_length=6)
    retrieval_requests: list[CompositeRetrievalRequestDraft] = Field(
        default_factory=list,
        max_length=3,
    )
    structured_requests: list[CompositeStructuredRequestDraft] = Field(
        default_factory=list,
        max_length=2,
    )
    reason: str = Field(default="", max_length=300)


COMPOSITE_ANSWER_PLAN_SYSTEM_PROMPT = (
    "你是 Grove 知识 Agent 的 quick 复合回答规划器。你只拆解一条原始请求中的回答义务"
    "并提出有界只读输入候选，不回答问题、不执行工具、不决定授权范围。"
    "\n"
    "必须以用户原始消息为准保留需要回答的内容、自然顺序和依据限制；独立问题只用于"
    "补全指代和生成检索表达，绝不能覆盖原始消息。不要按标点机械拆分：相同数据需求"
    "可以归并，一份输入请求可以关联多个回答义务。"
    "\n"
    "回答义务 kind 只允许 explain/retrieve/aggregate/compare/recommend/other。逐项依据："
    "grove_only 只能用 Grove，grove_required 必须包含 Grove 但可用通用知识补充，"
    "model_allowed 可使用模型通用知识，external_required 表示依赖当前外部材料且本阶段"
    "无法真实检索。若输入声明‘仅使用知识库’，所有义务都必须 grove_only。"
    "\n"
    "Grove 普通知识读取用 retrieval_requests；统计、分组、排序或有界对象列表使用"
    "structured_requests。EntrySetSpec 只允许 semantic_query、main_types、info_natures、"
    "带时区 UTC updated_at 闭开区间；输出只允许 entries/count/group_count。"
    "\n"
    "绝对不要输出 owner、Workspace、项目、目录、Entry、Source 或其他对象 id，不要输出"
    "SQL、正则、任意运算符、未知工具、写操作、第二轮计划或自主循环。"
)


def _model_name(text_model) -> str:
    """从 Provider 模型对象提取可观测模型名。"""
    return str(
        getattr(text_model, "model_name", None)
        or getattr(text_model, "model", "unknown")
    )


def _format_user_statements(statements: list[dict]) -> str:
    """只向模型提供服务端允许的用户消息句柄和有界正文。"""
    if not statements:
        return "（无）"
    return "\n".join(
        f"- 消息 {item['message_id']}：{item['content']}" for item in statements
    )


async def run_composite_answer_planner(
    db,
    workspace_id: int,
    *,
    current_message: str,
    standalone_query: str,
    scope_label: str,
    context_decision: str,
    topic_summary: str | None,
    user_statements: list[dict],
    knowledge_only: bool,
    now: datetime | None = None,
) -> tuple[CompositeAnswerPlanDraft | None, StageMeta]:
    """运行一次复合规划；失败返回 None 与真实 fallback 元数据。"""
    started = perf_counter()
    settings = get_settings()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return (
            None,
            StageMeta(
                purpose=PURPOSE_COMPOSITE_ANSWER_PLAN,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    context = "\n".join(
        [
            f"用户原始消息：{current_message}",
            f"独立检索问题：{standalone_query}",
            f"可信范围标签：{scope_label}",
            f"上下文决策：{context_decision}",
            f"主题摘要：{topic_summary or '（无）'}",
            f"仅使用 Grove：{'是' if knowledge_only else '否'}",
            f"当前 UTC 时间：{current.astimezone(UTC).isoformat()}",
            "允许的用户消息：",
            _format_user_statements(user_statements),
            "请输出 CompositeAnswerPlan v1 候选。",
        ]
    )
    agent = Agent(
        text_model,
        output_type=CompositeAnswerPlanDraft,
        system_prompt=COMPOSITE_ANSWER_PLAN_SYSTEM_PROMPT,
        retries=1,
        model_settings={
            "temperature": 0,
            "timeout": settings.knowledge_agent_composite_answer_planner_timeout_seconds,
        },
    )
    model_name = _model_name(text_model)
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("复合回答规划模型调用失败：%s", exc)
        return (
            None,
            StageMeta(
                purpose=PURPOSE_COMPOSITE_ANSWER_PLAN,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    usage = asdict(result.usage)
    if result.output is None:
        return (
            None,
            StageMeta(
                purpose=PURPOSE_COMPOSITE_ANSWER_PLAN,
                provider="llm",
                model=model_name,
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
                usage=usage,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=PURPOSE_COMPOSITE_ANSWER_PLAN,
            provider="llm",
            model=model_name,
            is_fallback=False,
            error=None,
            duration_ms=duration,
            usage=usage,
        ),
    )
