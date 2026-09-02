"""知识 Agent 回答组织器：基于已核验 Evidence 句柄生成结构化回答草稿。"""

import logging
from time import perf_counter

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models.knowledge_agent import PURPOSE_ANSWER
from app.services.ai_models import get_text_model
from app.services.knowledge_agent.observability import StageMeta

logger = logging.getLogger(__name__)

ANSWER_PROMPT_VERSION = "v3"

# 开放讨论追加提示：由服务端依据计划控制是否附加（prompt 版本随 ANSWER 观测）
OPEN_ANSWER_PROMPT_SUFFIX = (
    "\n"
    "本回答允许使用模型通用知识："
    "\n"
    "1. 没有当前 Run Evidence 支撑的一般解释、示例或通用概念要点可以直接保留，"
    "该要点不要挂 evidence_handles，也不要生成 Citation；"
    "\n"
    "2. 只要引用给定的 Grove Evidence，仍必须原样使用 ev_ 句柄并挂在对应要点上；"
    "不得改写、编造句柄，也不得把通用知识伪装成引用；"
    "\n"
    "3. “用户提供的信息”只能作为个人前提表达（例如“你提供的信息”），"
    "不得生成 Citation、Source 引文或把它当成正式知识；"
    "\n"
    "4. 本阶段没有实时外部工具：不得声称已经联网、已核验当前政策/价格/规则，"
    "也不得把模型训练知识描述为实时结果；"
    "\n"
    "5. 用户陈述与 Grove Entry 冲突时，并列说明双方及依据，不替用户裁决。"
)


class KnowledgeCitationDraft(BaseModel):
    """回答模型选择的 Evidence 句柄；服务端最终校验。"""

    evidence_handle: str = ""


class KnowledgeConflictDraft(BaseModel):
    """冲突双方（Evidence 句柄）与说明。"""

    evidence_handle_a: str = ""
    evidence_handle_b: str = ""
    summary: str = ""


class KnowledgeEvidenceSummaryDraft(BaseModel):
    """终态覆盖或缺口候选；服务端会复核句柄或可信缺失维度。"""

    summary: str = ""
    evidence_handles: list[str] = []


class KnowledgeAnswerPointDraft(BaseModel):
    """回答要点：服务端会逐条重验句柄并派生 citations。"""

    section: str | None = None
    text: str = ""
    evidence_handles: list[str] = []


class KnowledgeAnswerDraft(BaseModel):
    """一次问答的结构化草稿。"""

    answer: str = ""
    # v3：结论摘要与结构化要点；answer 文本由服务端从 lead + points 拼接
    lead: str | None = None
    points: list[KnowledgeAnswerPointDraft] = []
    citations: list[KnowledgeCitationDraft] = []
    conflicts: list[KnowledgeConflictDraft] = []
    insufficient: bool = False
    insufficient_note: str | None = None
    # 只概括当前 Evidence 是否足够回答核心问题；服务端仍按实际句柄复核。
    core_question_answered: bool | None = None
    coverage_complete: bool | None = None
    coverage: list[KnowledgeEvidenceSummaryDraft] = []
    gaps: list[KnowledgeEvidenceSummaryDraft] = []


KNOWLEDGE_ANSWER_SYSTEM_PROMPT = (
    "你是 Grove 的知识 Agent，负责基于已确认知识与服务端核验的原文证据回答用户问题。"
    "\n"
    "要求："
    "\n"
    "1. 只能基于给定的已确认 Entry 与核验原文回答；知识不足时明确标记 insufficient，"
    "不得使用模型自身知识悄悄补齐。"
    "\n"
    "2. 关键结论必须通过 citations 引用给定的 Evidence 句柄（形如 ev_xxxxxxxx），"
    "句柄必须原样使用，不得改写或编造。"
    "\n"
    "3. 不得自行生成 quote 或引号原文；引用原文以服务端提供的核验片段为准。"
    "\n"
    "4. 多条 Entry 说法矛盾时，用 conflicts 并列展示双方各自的 Evidence 句柄与各自观点，"
    "不要替用户裁决。"
    "\n"
    "5. 即时回答不是正式知识，不得修改任何正式数据。"
    "\n"
    "6. 正文首句必须直接回答：决策先给推荐、对比先给主要差异、操作先给步骤、"
    "事实先给答案。不得复述问题，不得使用“关于这个问题”“根据当前已确认知识”"
    "“以下是基于正式知识的回答”等没有新增信息的开场。"
    "\n"
    "7. 范围、来源数、部分结果、预算、轮次、停止原因和 coverage/gaps 由结构化卡片展示，"
    "不要在正文重复。只在多维长回答时先给一至两句有实际信息的结论摘要。"
    "\n"
    "8. 请给出 core_question_answered、coverage_complete、coverage 与 gaps。coverage 的每一项"
    "必须包含 summary 和用于支持该项的 evidence_handles，且句柄只能使用最终回答实际采用的"
    "当前 Run Evidence。gap 若对应综合上下文中列出的未解决缺口，必须原样使用该缺口文本，"
    "可以不附 Evidence；其他 gap 必须关联用于证明其边界的最终 Evidence。"
    "边缘证据不能视为已回答核心问题。"
    "\n"
    "9. insufficient 只能用于完全没有可确认证据或没有任何部分能直接回答核心问题的情况；"
    "只要你能基于证据直接回答核心问题的任何一部分，就必须 core_question_answered=True 且"
    "insufficient=False，已确认部分用 coverage 表达、未覆盖部分用 gaps 表达，"
    "不得用 insufficient 掩盖已有的可确认结论。"
    "\n"
    "10. 正文（lead 与每条 point 的 text）中绝对禁止出现 ev_ 开头的句柄字符串或任何"
    "引用标识；引用只通过结构化的 citations/conflicts 字段表达，不得在内联文本中追加"
    "句柄、编号或括号标记。"
    "\n"
    "11. 用 points 表达正文结构：每个独立的关键事实点必须是一个 point，且该 point 的"
    "evidence_handles 至少挂一个对应句柄；不要为一段多个结论只挂一个句柄，也不要让"
    "point 出现无引用的关键结论。多个事实点主题相同时用相同的 section 分组；"
    "section 使用简短主题词（如「客厅/卧室区域」「厨房区域」），不使用序号。"
    "\n"
    "12. lead 只写一至两句直接回答核心问题的结论摘要；详细分点全部放入 points，"
    "lead 与 points 之间不要重复展开。answer 字段与顶层 citations 由服务端生成，"
    "请留空；引用只通过每个 point 的 evidence_handles 表达，不要输出顶层 citations。"
)


def _format_context(
    query: str,
    scope_label: str,
    entries: list[dict],
    user_statements: list[dict] | None = None,
) -> str:
    """组装回答上下文：只包含已发现 Entry、可引用句柄与允许的用户陈述。"""
    parts = [f"问题：{query}", f"问答范围：{scope_label}", "可用已确认知识："]
    for item in entries:
        parts.append(f"- Entry {item['entry_id']}：{item['title']}")
        parts.append(f"  项目：{item['project_name']}")
        if item.get("node_path"):
            parts.append(f"  目录：{item['node_path']}")
        parts.append(f"  内容：{item['content'][:600]}")
        for evidence in item.get("evidences", []):
            parts.append(
                f"  来源「{evidence['source_title']}」核验原文："
                f"句柄 {evidence['handle']} 「{evidence['quote']}」"
            )
    parts.append(
        "引用规则：citations 只能使用上面列出的句柄；句柄必须完整原样返回；不要把原文片段当成句柄。"
    )
    statements = user_statements or []
    if statements:
        parts.append("用户提供的信息（只作个人前提，不是正式知识）：")
        for item in statements:
            parts.append(f"- 消息 {item['message_id']}：「{item['content']}」")
        parts.append(
            "规则：只能把上述用户信息表达为“你提供的信息”；不得为它们生成 "
            "Citation/Source 引文，不得把它们升级为正式知识或“已验证事实”。"
        )
    return "\n".join(parts)


def _offline_answer() -> KnowledgeAnswerDraft:
    """离线确定性兜底：明确提示模型不可用，不编造内容。"""
    return KnowledgeAnswerDraft(
        answer="当前没有可用的文本模型，无法基于知识库生成带引用的回答。请先配置文本模型密钥，或检查模型服务状态。",
        insufficient=True,
        insufficient_note="文本模型不可用",
    )


async def run_knowledge_answer_agent(
    db,
    workspace_id: int,
    query: str,
    scope_label: str,
    entries: list[dict],
    *,
    purpose: str = PURPOSE_ANSWER,
    synthesis_context: str | None = None,
    user_statements: list[dict] | None = None,
    allow_model_knowledge: bool = False,
    external_material_required: bool = False,
) -> tuple[KnowledgeAnswerDraft, StageMeta]:
    """运行回答 Agent，返回 (草稿, 阶段元数据)。

    `purpose` 允许调查最终综合阶段使用独立阶段标识；`synthesis_context`
    携带调查停止原因、未解决缺口与冲突提示，回答不得声称穷尽全部知识。
    """
    started = perf_counter()
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        duration = int((perf_counter() - started) * 1000)
        return (
            _offline_answer(),
            StageMeta(
                purpose=purpose,
                provider="offline",
                model=None,
                is_fallback=True,
                error="未配置文本模型密钥",
                duration_ms=duration,
            ),
        )

    context = _format_context(query, scope_label, entries, user_statements)
    system_prompt = KNOWLEDGE_ANSWER_SYSTEM_PROMPT
    if allow_model_knowledge:
        system_prompt = system_prompt + OPEN_ANSWER_PROMPT_SUFFIX
        if external_material_required:
            system_prompt = (
                system_prompt
                + "\n"
                + "本问题的核心依赖当前外部材料且当前不可用：只提供一般概念框架与"
                "待核对事项，明确说明未检索实时外部资料，并按实际完成度返回状态。"
            )
    if synthesis_context:
        system_prompt = (
            system_prompt
            + "\n"
            + "调查已停止，请按以下摘要组织回答："
            + "\n"
            + synthesis_context
            + "\n"
            + "要求：正文不要复述停止原因、预算或范围；只能直接回答可支持的内容。"
            "coverage/gaps 用结构化字段表达终态覆盖与未解决缺口；"
            "只能引用上方给出的当前 Run Evidence 句柄。"
        )
    agent = Agent(
        text_model,
        output_type=KnowledgeAnswerDraft,
        system_prompt=system_prompt,
        retries=1,
        model_settings={"temperature": 0.4},
    )
    model_name = getattr(text_model, "model_name", None) or getattr(text_model, "model", "unknown")
    try:
        result = await agent.run(context)
        duration = int((perf_counter() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        duration = int((perf_counter() - started) * 1000)
        logger.warning("知识 Agent 回答模型调用失败：%s", exc)
        return (
            _offline_answer(),
            StageMeta(
                purpose=purpose,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error=f"模型调用失败：{exc}",
                duration_ms=duration,
            ),
        )
    if result.output is None:
        return (
            _offline_answer(),
            StageMeta(
                purpose=purpose,
                provider="llm",
                model=str(model_name),
                is_fallback=True,
                error="模型未返回结构化结果",
                duration_ms=duration,
            ),
        )
    return (
        result.output,
        StageMeta(
            purpose=purpose,
            provider="llm",
            model=str(model_name),
            is_fallback=False,
            error=None,
            duration_ms=duration,
        ),
    )
