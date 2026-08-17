"""Candidate 响应模型。"""

from pydantic import BaseModel


class EvidenceRefOut(BaseModel):
    """候选证据引用。"""

    attachment_id: int
    quote: str


class NodeAlternativeOut(BaseModel):
    """候选目录备选。"""

    node_id: int
    reason: str = ""


class CandidateOut(BaseModel):
    """AI 候选，非正式知识。"""

    id: int
    source_id: int
    candidate_kind: str
    title: str
    content: str
    main_type: str
    info_nature: str | None
    applicable_condition: str | None
    note: str | None
    evidence: list[EvidenceRefOut] = []
    reason: str | None
    risk_flags: list[str] = []
    status: str
    recommended_node_id: int | None
    node_alternatives: list[NodeAlternativeOut] = []
    node_reason: str | None
    routing_status: str
