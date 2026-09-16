"""Evidence 校验使用的回答草稿数据合同；不包含模型或执行编排。"""

from pydantic import BaseModel, Field


class KnowledgeCitationDraft(BaseModel):
    evidence_handle: str = ""


class KnowledgeConflictDraft(BaseModel):
    evidence_handle_a: str = ""
    evidence_handle_b: str = ""
    summary: str = ""


class KnowledgeEvidenceSummaryDraft(BaseModel):
    summary: str = ""
    evidence_handles: list[str] = []


class KnowledgeAnswerPointDraft(BaseModel):
    section: str | None = None
    text: str = ""
    evidence_handles: list[str] = []
    answers_core_question: bool | None = None
    requirement_ids: list[str] = Field(default_factory=list, max_length=8)
    result_handles: list[str] = Field(default_factory=list, max_length=16)


class KnowledgeAnswerDraft(BaseModel):
    answer: str = ""
    lead: str | None = None
    points: list[KnowledgeAnswerPointDraft] = []
    citations: list[KnowledgeCitationDraft] = []
    conflicts: list[KnowledgeConflictDraft] = []
    insufficient: bool = False
    insufficient_note: str | None = None
    core_question_answered: bool | None = None
    coverage_complete: bool | None = None
    coverage: list[KnowledgeEvidenceSummaryDraft] = []
    gaps: list[KnowledgeEvidenceSummaryDraft] = []
