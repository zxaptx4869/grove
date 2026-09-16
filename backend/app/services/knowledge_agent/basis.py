"""依据限制与历史 AnswerBasis 的确定性兼容工具。"""

import re

from app.models.knowledge_agent import (
    EXTERNAL_MATERIAL_NOT_USED,
    EXTERNAL_MATERIAL_REQUIRED_UNAVAILABLE,
)
from app.schemas.knowledge_agent import (
    KnowledgeAnswerBasisExternalMaterialOut,
    KnowledgeAnswerBasisGroveOut,
    KnowledgeAnswerBasisModelKnowledgeOut,
    KnowledgeAnswerBasisOut,
    KnowledgeAnswerBasisUserStatementsOut,
    KnowledgeAnswerOut,
)

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


def contains_knowledge_only_restriction(*texts: str) -> bool:
    """识别明确的 knowledge-only 自然语言限制。"""
    combined = " ".join(text for text in texts if text).casefold()
    compact = re.sub(r"[\s，。！？、；：,.!?;:]", "", combined)
    without_model_broadening = _BROADEN_MODEL_PATTERN.sub("", compact)
    if _NEGATIVE_MODEL_KNOWLEDGE_PATTERN.search(without_model_broadening):
        return True
    compact = re.sub(r"(?:通用|模型|ai|外部|公共)知识", "通用常识", compact)
    without_knowledge_broadening = _BROADEN_KNOWLEDGE_PATTERN.sub("", compact)
    return bool(
        any(
            phrase in without_knowledge_broadening
            for phrase in _KNOWLEDGE_ONLY_PHRASES
        )
        or _EXCLUSIVE_KNOWLEDGE_PATTERN.search(without_knowledge_broadening)
    )


def contains_no_grove_restriction(*texts: str) -> bool:
    """识别明确禁止查询 Grove 的约束，放宽“不要只查”不算禁止。"""
    compact = re.sub(r"[\s，。！？、；：,.!?;:]", "", " ".join(texts).casefold())
    compact = re.sub(r"(?:不要|不用|无需|不必|别)(?:只|仅)", "允许", compact)
    return bool(
        re.search(
            r"(?:不要|不用|无需|不必|别|不)(?:再|去|用)?(?:查|查询|检索|搜索|读取|使用|参考)"
            r"(?:我的|个人|已有)?(?:知识库|grove|知林)",
            compact,
        )
    )


def build_answer_basis(
    *,
    answer: KnowledgeAnswerOut,
    user_statement_ids: list[int],
    model_knowledge_used: bool,
    external_material_required: bool,
    grove_result_used: bool = False,
) -> KnowledgeAnswerBasisOut:
    """从最终回答装配历史兼容的 AnswerBasis v1。"""
    citation_count = len(answer.citations)
    entry_count = len(
        {
            citation.entry_id
            for citation in answer.citations
            if citation.entry_id and citation.entry_id != 0
        }
    )
    return KnowledgeAnswerBasisOut(
        schema_version="v1",
        grove=KnowledgeAnswerBasisGroveOut(
            used=citation_count > 0 or grove_result_used,
            citation_count=citation_count,
            entry_count=entry_count,
        ),
        user_statements=KnowledgeAnswerBasisUserStatementsOut(
            message_ids=sorted(set(user_statement_ids))
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
