"""知识 Agent 依据规划应用层服务：显式限制优先、有界用户陈述与安全回退。"""

import json
import logging
import re
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

# 不能仅靠上面的固定短语：用户也可能通过“不要补充 AI 常识”或
# “仅依据 Grove 里的内容”等等价表达收紧依据。这里仅识别明确的限制，
# 同时排除“不要只看知识库”“不限于知识库”等主动放宽表达。
_KNOWLEDGE_TARGET_PATTERN = (
    r"(?:我的|个人|已有|现有|已确认|正式)?"
    r"(?:知识库|知识|记录)|grove|知林"
)
_EXCLUSIVE_KNOWLEDGE_PATTERN = re.compile(
    rf"(?:只|仅|只能|只看|只参考|只依据|仅看|仅参考|仅依据|仅根据)"
    rf".{{0,10}}(?:{_KNOWLEDGE_TARGET_PATTERN})"
    rf"|(?:{_KNOWLEDGE_TARGET_PATTERN}).{{0,8}}(?:即可|就好|为准)"
)
_NEGATIVE_MODEL_KNOWLEDGE_PATTERN = re.compile(
    r"(?:不要|别|不得|禁止|不用|无需|不需要|不使用|不参考|不采用|不补充|别用|别参考|别补充)"
    r".{0,10}(?:ai|模型|通用|外部|网络|联网).{0,6}(?:知识|常识|能力|资料|信息)?"
)
_BROADEN_MODEL_PATTERN = re.compile(
    r"(?:(?:不要|别|不必|无需|不能)(?:只|仅)|不只|不仅)"
    r".{0,8}(?:ai|模型|通用|外部|网络|联网).{0,6}(?:知识|常识|能力|资料|信息)?"
)
_BROADEN_KNOWLEDGE_PATTERN = re.compile(
    rf"(?:不要|别|不必|无需|不能|不只|不仅)(?:只|仅)?"
    rf".{{0,6}}(?:根据|使用|看|参考|依据|依赖)?"
    rf".{{0,6}}(?:{_KNOWLEDGE_TARGET_PATTERN})"
    rf"|(?:不局限于|不限于).{{0,6}}(?:{_KNOWLEDGE_TARGET_PATTERN})"
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
    combined = " ".join(text for text in texts if text).casefold()
    compact = re.sub(r"[\s，。！？、；：,.!?;:]", "", combined)
    # 先移除“不要只用某类依据”这种主动放宽片段，再判断剩余文本中是否
    # 存在真正的排除模型知识或仅限 Grove 约束；同一句中的后续严格约束仍生效。
    without_model_broadening = _BROADEN_MODEL_PATTERN.sub("", compact)
    if _NEGATIVE_MODEL_KNOWLEDGE_PATTERN.search(without_model_broadening):
        return True
    without_knowledge_broadening = _BROADEN_KNOWLEDGE_PATTERN.sub("", compact)
    return bool(
        any(
            phrase in without_knowledge_broadening
            for phrase in _KNOWLEDGE_ONLY_PHRASES
        )
        or _EXCLUSIVE_KNOWLEDGE_PATTERN.search(without_knowledge_broadening)
    )


def contains_knowledge_only_restriction(*texts: str) -> bool:
    """公开复用明确 knowledge-only 自然语言门禁，避免不同规划器规则漂移。"""
    return _contains_knowledge_only_restriction(*texts)


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
    planned_basis_json: str | None,
) -> BasisPlan:
    """崩溃恢复：重放已持久化计划，且只允许收紧用户消息子集。"""
    uses_statements = basis_strategy_uses_user_statements(strategy)
    allowed_ids = {item.message_id for item in allowed_statements}
    restored_ids: list[int] = []
    if planned_basis_json:
        try:
            raw = json.loads(planned_basis_json)
            raw_ids = raw.get("candidate_statement_ids", [])
            if (
                isinstance(raw, dict)
                and raw.get("schema_version") == "v1"
                and raw.get("strategy") == strategy
                and isinstance(raw_ids, list)
                and all(isinstance(item, int) for item in raw_ids)
            ):
                # 消息若在恢复时已不可用只能删除，绝不补入原计划未选择的消息。
                restored_ids, _invalid = validate_statement_ids(raw_ids, allowed_ids)
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.warning("basis 计划快照损坏，恢复时不采用用户陈述")
    return BasisPlan(
        strategy=strategy,
        needs_grove=basis_strategy_needs_grove(strategy),
        requires_external_material=strategy == "external_needed",
        candidate_statement_ids=restored_ids if uses_statements else [],
        degraded=False,
        meta=None,
    )


def dump_basis_plan(plan: BasisPlan) -> str:
    """序列化可恢复的最小 basis 计划，不复制用户消息正文。"""
    return json.dumps(
        {
            "schema_version": "v1",
            "strategy": plan.strategy,
            "candidate_statement_ids": list(
                dict.fromkeys(plan.candidate_statement_ids)
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_answer_basis(
    *,
    answer: KnowledgeAnswerOut,
    user_statement_ids: list[int],
    model_knowledge_used: bool,
    external_material_required: bool,
    grove_result_used: bool = False,
) -> KnowledgeAnswerBasisOut:
    """服务端装配 AnswerBasis v1：数量只从最终校验后 Citation 派生。

    - Grove 数量来自最终回答 Citation（全部句柄失效时为 0）；
      复合回答的确定性结构化事实可单独表明 Grove 已使用；
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
            used=citation_count > 0 or grove_result_used,
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
            current_message=current_message,
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
