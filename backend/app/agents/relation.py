"""关系判断 Agent：为候选判断其与项目内已有 Entry 的关系。"""

from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from app.models import Candidate, Entry
from app.models.extraction import RELATION_NEW
from app.services.ai_models import get_text_model


class EntryRevisionDraft(BaseModel):
    """对目标 Entry 的建议修订草稿。"""

    title: str | None = None
    content: str | None = None
    main_type: Literal["knowledge", "method", "parameter", "reminder"] | None = None
    info_nature: Literal["fact", "experience", "advice", "speculation", "other"] | None = None
    applicable_condition: str | None = None
    note: str | None = None
    change_summary: str = ""


class RelationRecommendationDraft(BaseModel):
    """单条候选的关系建议。"""

    candidate_id: int
    relation_status: Literal["new", "duplicate", "supplement", "conflict"]
    target_entry_id: int | None = None
    reason: str = ""
    revision_draft: EntryRevisionDraft | None = None


class RelationDraft(BaseModel):
    """一次关系判断的结构化结果。"""

    recommendations: list[RelationRecommendationDraft] = []


RELATION_SYSTEM_PROMPT = """你是 Grove 整理 Agent 的关系判断步骤。
请判断每条候选与项目内已有 Entry 的关系。

要求：
1. 只能把候选与给定的已有 Entry 比较；target_entry_id 必须是给定 Entry 的 id。
2. relation_status 只使用：
   - new：没有足够相关的已有 Entry，或关系不成立；
   - duplicate：与目标 Entry 表述同一知识，且不新增实质内容，只需要补充新来源证据；
   - supplement：与目标 Entry 相关，但带来新增或更新信息，需要生成修订草稿；
   - conflict：与目标 Entry 存在矛盾，或重复/补充难以区分但风险明显。
3. duplicate 和 supplement 必须给出 target_entry_id 与简短 reason。
4. supplement 必须给出 revision_draft：字段为建议的最终值；未变化的字段可以留空；
   change_summary 用一句话说明改了什么。
5. conflict 必须给出 target_entry_id 与 reason，可以同时给出 revision_draft 作为「修订现有」的建议。
6. AI 输出永远是候选，不得直接修改正式 Entry。"""


def _format_relation_context(
    candidates: list[Candidate],
    similar_entries: dict[int, list[Entry]],
) -> str:
    """组装候选与相似 Entry 的关系判断上下文。"""
    parts = ["请为以下候选判断与已有 Entry 的关系。", "候选与相似 Entry："]
    for candidate in candidates:
        parts.append(f"\n候选 {candidate.id}：{candidate.title}")
        parts.append(f"内容：{candidate.content[:300]}")
        if candidate.applicable_condition:
            parts.append(f"适用条件：{candidate.applicable_condition}")
        if candidate.note:
            parts.append(f"补充说明：{candidate.note}")
        entries = similar_entries.get(candidate.id, [])
        if entries:
            parts.append("已有 Entry：")
            for entry in entries:
                parts.append(f"- Entry {entry.id}：{entry.title}")
                parts.append(f"  内容：{entry.content[:300]}")
        else:
            parts.append("已有 Entry：无")
    return "\n".join(parts)


def _offline_relation(candidates: list[Candidate]) -> RelationDraft:
    """离线确定性关系判断：一律视为新知识。"""
    return RelationDraft(
        recommendations=[
            RelationRecommendationDraft(
                candidate_id=candidate.id,
                relation_status=RELATION_NEW,
            )
            for candidate in candidates
        ]
    )


async def run_relation_agent(
    db,
    workspace_id: int,
    candidates: list[Candidate],
    similar_entries: dict[int, list[Entry]],
) -> RelationDraft:
    """运行关系判断 Agent，返回结构化的关系建议。"""
    text_model = await get_text_model(db, workspace_id)
    if isinstance(text_model, TestModel):
        return _offline_relation(candidates)

    context = _format_relation_context(candidates, similar_entries)
    agent = Agent(
        text_model,
        output_type=RelationDraft,
        system_prompt=RELATION_SYSTEM_PROMPT,
        retries=1,
    )
    result = await agent.run(context)
    if result.output is None:
        raise RuntimeError("关系判断 Agent 未返回结构化结果")
    return result.output
