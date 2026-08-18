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


class NewNodeSuggestionOut(BaseModel):
    """候选的新节点建议。"""

    name: str
    parent_id: int | None = None
    reason: str | None = None


class EntryRevisionDraftOut(BaseModel):
    """候选对已有 Entry 的修订草稿。"""

    title: str | None = None
    content: str | None = None
    main_type: str | None = None
    info_nature: str | None = None
    applicable_condition: str | None = None
    note: str | None = None
    change_summary: str = ""


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
    new_node_suggestion: NewNodeSuggestionOut | None = None
    relation_status: str
    relation_target_entry_id: int | None
    relation_target_entry_title: str | None
    relation_target_entry_node_name: str | None
    relation_reason: str | None
    revision_draft: EntryRevisionDraftOut | None = None
