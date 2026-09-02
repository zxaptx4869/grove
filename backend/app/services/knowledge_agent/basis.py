"""知识 Agent 依据规划应用层服务：显式限制优先、有界用户陈述与安全回退。"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.basis import (
    BASIS_ROUTE_PROMPT_VERSION,
    run_basis_planner,
)
from app.models import (
    KnowledgeAgentRun,
    KnowledgeContextVersion,
    KnowledgeConversation,
    KnowledgeMessage,
)
from app.models.knowledge_agent import (
    BASIS_MODE_AUTO,
    BASIS_MODE_KNOWLEDGE_ONLY,
    BASIS_STRATEGIES,
    BASIS_STRATEGY_HYBRID,
    BASIS_STRATEGY_KNOWLEDGE_FIRST,
    BASIS_STRATEGY_KNOWLEDGE_ONLY,
    BASIS_STRATEGY_MODEL_FIRST,
    CONTEXT_DECISION_CONTINUE,
    EXTERNAL_MATERIAL_NOT_USED,
    EXTERNAL_MATERIAL_REQUIRED_UNAVAILABLE,
    MESSAGE_ROLE_USER,
    PURPOSE_BASIS_ROUTE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerBasisExternalMaterialOut,
    KnowledgeAnswerBasisGroveOut,
    KnowledgeAnswerBasisModelKnowledgeOut,
    KnowledgeAnswerBasisOut,
    KnowledgeAnswerBasisUserStatementsOut,
    KnowledgeAnswerOut,
)
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

# 确定性自然语言「仅使用我的知识库」识别：命中后比规划器结果更严格，
# 规划器即使认为通用知识有帮助也不得放宽。
_KNOWLEDGE_ONLY_PHRASES = (
    "只根据我的知识库",
    "只使用我的知识库",
    "仅使用我的知识库",
    "只用我的知识库",
    "只能根据我的知识库",
    "只能使用我的知识库",
    "只依据已确认知识",
    "只靠我的知识库",
)

# 遍历上下文版本链的安全上限（防止异常数据导致无限循环）
_CONTEXT_CHAIN_LIMIT = 100


@dataclass
class UserStatementCandidate:
    """服务端允许集合中的一条用户陈述候选。"""

    message_id: int
    content: str


@dataclass
class BasisPlan:
    """归一化后的依据规划结果（服务端持久化 planned_basis_strategy）。"""

    strategy: str
    needs_grove: bool = True
    requires_external_material: bool = False
    candidate_statement_ids: list[int] = field(default_factory=list)
    degraded: bool = False
    meta: StageMeta | None = None


def basis_route_prompt_version() -> str:
    """返回依据规划 prompt 版本（可观测记录复用）。"""
    return BASIS_ROUTE_PROMPT_VERSION


def _contains_knowledge_only_restriction(*texts: str) -> bool:
    """确定性识别「仅使用我的知识库」等显式限制。"""
    combined = " ".join(text for text in texts if text)
    return any(phrase in combined for phrase in _KNOWLEDGE_ONLY_PHRASES)


def _server_knowledge_only_plan() -> BasisPlan:
    """显式 knowledge_only / 特性关闭时的确定性计划（不产生模型调用）。"""
    return BasisPlan(
        strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY,
        needs_grove=True,
        requires_external_material=False,
        candidate_statement_ids=[],
        degraded=False,
        meta=None,
    )


def basis_strategy_needs_grove(strategy: str) -> bool:
    """策略是否需要执行 Grove 检索/读取（model_first/external_needed 跳过）。"""
    return strategy in {
        BASIS_STRATEGY_KNOWLEDGE_ONLY,
        BASIS_STRATEGY_KNOWLEDGE_FIRST,
        BASIS_STRATEGY_HYBRID,
    }


def basis_strategy_allows_model_knowledge(strategy: str) -> bool:
    """策略是否允许回答模型使用通用知识（knowledge_only 严格禁止）。"""
    return strategy != BASIS_STRATEGY_KNOWLEDGE_ONLY


def basis_strategy_uses_user_statements(strategy: str) -> bool:
    """策略是否允许当前话题用户陈述参与回答。"""
    return strategy in {
        BASIS_STRATEGY_KNOWLEDGE_FIRST,
        BASIS_STRATEGY_HYBRID,
        BASIS_STRATEGY_MODEL_FIRST,
    }


def restore_basis_plan(
    strategy: str,
    allowed_statements: list[UserStatementCandidate],
) -> BasisPlan:
    """崩溃恢复：按已持久化的规划策略重建确定性计划，不重新调用规划器。

    候选用户消息句柄未单独持久化；恢复时对允许使用用户陈述的策略采用当前
    有界允许集合（服务端重新确定性加载，范围/话题链校验一致），策略本身
    不会漂移，也不会从 knowledge_only 放宽到模型通用知识。
    """
    uses_statements = basis_strategy_uses_user_statements(strategy)
    return BasisPlan(
        strategy=strategy,
        needs_grove=basis_strategy_needs_grove(strategy),
        requires_external_material=strategy == "external_needed",
        candidate_statement_ids=(
            [item.message_id for item in allowed_statements]
            if uses_statements
            else []
        ),
        degraded=False,
        meta=None,
    )


def build_answer_basis(
    *,
    answer: KnowledgeAnswerOut,
    user_statement_ids: list[int],
    model_knowledge_used: bool,
    external_material_required: bool,
) -> KnowledgeAnswerBasisOut:
    """服务端装配 AnswerBasis v1：数量只从最终校验后 Citation 派生。

    - Grove 数量来自最终回答 Citation（全部句柄失效时为 0）；
    - 用户消息 ID 只使用服务端允许集合与规划器选择的交集；
    - 模型通用知识由执行分支与提示权限保守标记，不依赖模型自由自报；
    - 外部材料状态只能由服务端写为 not_used 或 required_unavailable。
    """
    citation_count = len(answer.citations)
    entry_count = len(
        {
            citation.entry_id
            for citation in answer.citations
            if citation.entry_id and citation.entry_id != 0
        }
    )
    unique_statement_ids = sorted(set(user_statement_ids))
    return KnowledgeAnswerBasisOut(
        schema_version="v1",
        grove=KnowledgeAnswerBasisGroveOut(
            used=citation_count > 0,
            citation_count=citation_count,
            entry_count=entry_count,
        ),
        user_statements=KnowledgeAnswerBasisUserStatementsOut(
            message_ids=unique_statement_ids
        ),
        model_knowledge=KnowledgeAnswerBasisModelKnowledgeOut(
            used=model_knowledge_used
        ),
        external_material=KnowledgeAnswerBasisExternalMaterialOut(
            status=(
                EXTERNAL_MATERIAL_REQUIRED_UNAVAILABLE
                if external_material_required
                else EXTERNAL_MATERIAL_NOT_USED
            )
        ),
    )


def validate_statement_ids(
    ids: list[int],
    allowed_message_ids: set[int],
) -> tuple[list[int], list[int]]:
    """句柄白名单校验：返回 (合法 ID, 非法 ID)；未知/越权 ID 一律丢弃。"""
    unique = list(dict.fromkeys(ids))
    valid = [message_id for message_id in unique if message_id in allowed_message_ids]
    invalid = [message_id for message_id in unique if message_id not in allowed_message_ids]
    return valid, invalid


async def resolve_basis_plan(
    db: AsyncSession | None,
    *,
    workspace_id: int,
    request_basis_mode: str | None,
    objective: str,
    scope_label: str,
    topic_summary: str | None,
    context_decision: str,
    current_message: str,
    allowed_statements: list[UserStatementCandidate],
    feature_enabled: bool,
) -> BasisPlan:
    """解析依据计划：显式/自然语言限制与特性开关优先，auto 走规划器。

    - knowledge_only、特性关闭或命中确定性「仅知识库」限制时由应用直接固化，
      meta=None，调用方不得记录虚假模型调用；
    - auto 规划失败/非法结构时显式回退 knowledge_only（Grove-only），
      meta 保留 provider/model/fallback/error 供审计；
    - 规划器返回的候选用户消息句柄只保留服务端允许集合内的值。
    """
    effective_mode = request_basis_mode or BASIS_MODE_KNOWLEDGE_ONLY
    if (
        not feature_enabled
        or effective_mode == BASIS_MODE_KNOWLEDGE_ONLY
        or _contains_knowledge_only_restriction(objective, current_message)
    ):
        return _server_knowledge_only_plan()
    if effective_mode != BASIS_MODE_AUTO:
        # 未知请求模式由 schema 拦截；此处防御性回退
        return _server_knowledge_only_plan()
    if db is None:
        return _server_knowledge_only_plan()

    allowed_ids = {item.message_id for item in allowed_statements}
    try:
        draft, meta = await run_basis_planner(
            db,
            workspace_id,
            objective=objective,
            scope_label=scope_label,
            topic_summary=topic_summary,
            context_decision=context_decision,
            user_statements=[
                {"message_id": item.message_id, "content": item.content}
                for item in allowed_statements
            ],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("依据规划调用异常，回退 knowledge_only：%s", exc)
        return BasisPlan(
            strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY,
            needs_grove=True,
            candidate_statement_ids=[],
            degraded=True,
            meta=StageMeta(
                purpose=PURPOSE_BASIS_ROUTE,
                provider="server",
                model=None,
                is_fallback=True,
                error=f"依据规划调用异常：{exc}",
                duration_ms=0,
            ),
        )

    invalid_meta = meta
    if (
        draft is None
        or meta.is_fallback
        or draft.strategy not in BASIS_STRATEGIES
    ):
        # 显式降级：记录规划器状态，不静默开放模型通用知识
        return BasisPlan(
            strategy=BASIS_STRATEGY_KNOWLEDGE_ONLY,
            needs_grove=True,
            candidate_statement_ids=[],
            degraded=True,
            meta=meta,
        )

    # 规划结果再次收紧：命中自然语言「仅知识库」时不允许规划器放宽
    if _contains_knowledge_only_restriction(objective, current_message):
        return _server_knowledge_only_plan()

    valid_ids, invalid_ids = validate_statement_ids(
        draft.user_message_ids,
        allowed_ids,
    )
    if invalid_ids:
        # 非法句柄全部丢弃并记录异常；合法计划仍保留但显示为一次受影响调用
        error_note = (
            f"丢弃 {len(invalid_ids)} 个不在允许集合内的用户消息 ID："
            f"{sorted(invalid_ids)[:5]}"
        )
        invalid_meta = StageMeta(
            purpose=meta.purpose,
            provider=meta.provider,
            model=meta.model,
            is_fallback=True,
            error=(
                f"{meta.error or '依据规划输出含非法句柄'}；{error_note}"
            ),
            duration_ms=meta.duration_ms,
        )
        logger.warning("依据规划输出含非法用户消息句柄：%s", error_note)

    strategy = draft.strategy
    if strategy == BASIS_STRATEGY_KNOWLEDGE_ONLY:
        # 纯知识库策略不使用用户陈述或模型通用知识
        candidate_ids: list[int] = []
        needs_grove = True
        requires_external = False
    elif strategy == BASIS_STRATEGY_MODEL_FIRST:
        # 模型优先：默认跳过 Grove；外部材料不可用
        candidate_ids = valid_ids
        needs_grove = False
        requires_external = False
    else:
        # knowledge_first / hybrid / external_needed：都需要 Grove 或外部边界
        candidate_ids = valid_ids
        needs_grove = strategy in {
            BASIS_STRATEGY_KNOWLEDGE_FIRST,
            BASIS_STRATEGY_HYBRID,
        }
        requires_external = strategy == "external_needed"
    return BasisPlan(
        strategy=strategy,
        needs_grove=needs_grove,
        requires_external_material=requires_external,
        candidate_statement_ids=candidate_ids,
        degraded=invalid_meta.is_fallback,
        meta=invalid_meta,
    )


async def _context_chain_version_ids(
    db: AsyncSession,
    *,
    conversation_id: int,
    input_context_version_id: int | None,
) -> set[int]:
    """沿 parent_version_id 收集当前话题上下文链上的全部版本 ID。

    新话题/范围切换后创建的新版本 parent 链会与旧话题分离，因此旧话题的
    版本不会进入本集合；输入版本缺失或跨对话时不返回任何链成员。
    """
    if input_context_version_id is None:
        return set()
    version = await db.get(KnowledgeContextVersion, input_context_version_id)
    if version is None or version.conversation_id != conversation_id:
        return set()
    chain: set[int] = set()
    current: KnowledgeContextVersion | None = version
    hops = 0
    while current is not None and hops < _CONTEXT_CHAIN_LIMIT:
        if current.id in chain:
            break
        chain.add(current.id)
        if current.parent_version_id is None:
            break
        parent = await db.get(KnowledgeContextVersion, current.parent_version_id)
        current = parent
        hops += 1
    return chain


async def load_allowed_user_statements(
    db: AsyncSession,
    *,
    workspace_id: int,
    owner_user_id: int,
    conversation_id: int,
    scope_type: str,
    project_id: int | None,
    context_decision: str,
    current_message_id: int | None,
    exclude_run_id: int | None = None,
    input_context_version_id: int | None = None,
    limit: int,
    message_chars: int,
) -> list[UserStatementCandidate]:
    """加载当前话题有界用户陈述：只允许当前消息与同话题上下文链成员。

    - 当前用户消息始终可选；
    - continue 才继承同 Conversation、同范围快照、当前上下文链内近期用户消息；
    - new_topic、范围切换（链外）与澄清不继承旧话题陈述；
    - 助手/系统消息不是用户陈述，历史助手回答不得进入事实上下文。
    """
    limit = max(1, limit)
    if current_message_id is None:
        return []
    conversation = await db.get(KnowledgeConversation, conversation_id)
    if (
        conversation is None
        or conversation.workspace_id != workspace_id
        or conversation.owner_user_id != owner_user_id
    ):
        # 跨 Workspace/其他用户：不暴露任何消息内容
        return []
    current = await db.get(KnowledgeMessage, current_message_id)
    if current is None or current.conversation_id != conversation_id:
        return []
    if current.role != MESSAGE_ROLE_USER:
        return []
    if (
        current.scope_type != scope_type
        or current.project_id != project_id
    ):
        # 范围快照不匹配：跨范围消息不作为本轮依据
        return []

    current_statement = UserStatementCandidate(
        message_id=current.id,
        content=current.content[:message_chars],
    )
    if context_decision != CONTEXT_DECISION_CONTINUE:
        return [current_statement]
    chain_ids = await _context_chain_version_ids(
        db,
        conversation_id=conversation_id,
        input_context_version_id=input_context_version_id,
    )
    if not chain_ids:
        # 没有可证明的当前话题链：只允许当前消息，不猜测继承
        return [current_statement]

    # 扫描近期用户消息窗口（含被排除项），再按话题链过滤
    window = max(limit * 4, 24)
    rows = (
        await db.execute(
            select(KnowledgeMessage)
            .where(
                KnowledgeMessage.conversation_id == conversation_id,
                KnowledgeMessage.role == MESSAGE_ROLE_USER,
                KnowledgeMessage.scope_type == scope_type,
                KnowledgeMessage.project_id == project_id,
            )
            .order_by(
                KnowledgeMessage.created_at.desc(),
                KnowledgeMessage.id.desc(),
            )
            .limit(window)
        )
    ).scalars().all()
    if not rows:
        return [current_statement]

    run_ids = {
        row.run_id
        for row in rows
        if row.run_id is not None and row.id != current.id
    }
    runs_by_id: dict[int, KnowledgeAgentRun] = {}
    if run_ids:
        run_rows = (
            await db.execute(
                select(KnowledgeAgentRun).where(
                    KnowledgeAgentRun.id.in_(run_ids),
                    KnowledgeAgentRun.workspace_id == workspace_id,
                    KnowledgeAgentRun.owner_user_id == owner_user_id,
                )
            )
        ).scalars().all()
        runs_by_id = {run.id: run for run in run_rows}

    def _in_current_topic(run_id: int | None) -> bool:
        if run_id is None or run_id == exclude_run_id:
            return False
        run = runs_by_id.get(run_id)
        if run is None:
            return False
        if (
            run.conversation_id != conversation_id
            or run.scope_type != scope_type
            or run.project_id != project_id
        ):
            return False
        if run.output_context_version_id in chain_ids:
            return True
        return bool(
            run.context_decision == CONTEXT_DECISION_CONTINUE
            and run.input_context_version_id in chain_ids
        )

    inherited_desc: list[UserStatementCandidate] = []
    for row in rows:  # 从最近向更早扫描
        if row.id == current.id:
            continue
        if not _in_current_topic(row.run_id):
            continue
        inherited_desc.append(
            UserStatementCandidate(
                message_id=row.id,
                content=row.content[:message_chars],
            )
        )
        if len(inherited_desc) >= limit - 1:
            break
    # 恢复时间正序：继承陈述在前，当前消息最后
    return list(reversed(inherited_desc)) + [current_statement]
