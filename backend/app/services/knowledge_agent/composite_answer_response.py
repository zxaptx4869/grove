"""复合回答的模型综合、逐项绑定校验与服务端覆盖派生。"""

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.knowledge_agent import (
    ANSWER_PROMPT_VERSION,
    KnowledgeAnswerDraft,
    run_knowledge_answer_agent,
)
from app.models.knowledge_agent import RUN_COMPLETED, RUN_FAILED, RUN_PARTIAL
from app.schemas.knowledge_agent import KnowledgeAnswerOut, KnowledgeAnswerPointOut
from app.services.knowledge_agent.basis import build_answer_basis
from app.services.knowledge_agent.composite_answer import NormalizedCompositeAnswerPlan
from app.services.knowledge_agent.composite_answer_types import (
    CompositeAnswerCoverageSnapshot,
    CompositeAnswerExecutionSnapshot,
    CompositeRequirementCoverageSnapshot,
)
from app.services.knowledge_agent.evidence import (
    build_validated_answer,
    resolve_evidence_handles,
)
from app.services.knowledge_agent.observability import record_model_invocation

_NUMBER_IN_TEXT = re.compile(r"\d")


@dataclass(frozen=True)
class CompositeAnswerResult:
    """服务端校验后的复合回答终态材料。"""

    answer: KnowledgeAnswerOut
    coverage: CompositeAnswerCoverageSnapshot
    answer_basis: object
    run_status: str
    answer_fallback: bool


def _answer_text(points: list[KnowledgeAnswerPointOut], lead: str | None) -> str:
    """按义务排序后的最终 points 稳定拼接兼容 answer 文本。"""
    lines: list[str] = []
    if lead and lead.strip():
        lines.append(lead.strip())
    current_section: str | None = None
    for point in points:
        if point.section != current_section:
            if lines:
                lines.append("")
            current_section = point.section
            if current_section:
                lines.append(f"**{current_section}**")
        lines.append(f"- {point.text}")
    return "\n".join(lines).strip()


def _binding_maps(
    plan: NormalizedCompositeAnswerPlan,
    execution: CompositeAnswerExecutionSnapshot,
) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """返回义务允许的 Evidence/result 句柄与拥有精确数字事实的义务。"""
    evidence: dict[str, set[str]] = {item.id: set() for item in plan.requirements}
    results: dict[str, set[str]] = {item.id: set() for item in plan.requirements}
    exact_numeric: set[str] = set()
    for item in execution.inputs:
        for requirement_id in item.requirement_ids:
            evidence.setdefault(requirement_id, set()).update(item.evidence_handles)
            results.setdefault(requirement_id, set()).update(item.result_handles)
    for fact in execution.tool_facts:
        for requirement_id in fact.requirement_ids:
            results.setdefault(requirement_id, set()).add(fact.handle)
            if fact.completeness == "complete" and fact.kind in {"count", "group_count"}:
                exact_numeric.add(requirement_id)
    return evidence, results, exact_numeric


def _validated_draft_bindings(
    draft: KnowledgeAnswerDraft,
    plan: NormalizedCompositeAnswerPlan,
    execution: CompositeAnswerExecutionSnapshot,
) -> tuple[KnowledgeAnswerDraft, list[str], int]:
    """拒绝未知/无关句柄与不满足逐义务依据策略的模型 point。"""
    requirement_by_id = {item.id: item for item in plan.requirements}
    evidence_by_requirement, results_by_requirement, exact_numeric = _binding_maps(
        plan, execution
    )
    valid_points = []
    invalid_count = 0
    for point in draft.points:
        requirement_ids = list(dict.fromkeys(point.requirement_ids))
        evidence_handles = list(dict.fromkeys(point.evidence_handles))
        result_handles = list(dict.fromkeys(point.result_handles))
        if not requirement_ids or any(
            requirement_id not in requirement_by_id for requirement_id in requirement_ids
        ):
            invalid_count += 1
            continue
        allowed_evidence = set().union(
            *(evidence_by_requirement[item] for item in requirement_ids)
        )
        allowed_results = set().union(
            *(results_by_requirement[item] for item in requirement_ids)
        )
        if not set(evidence_handles).issubset(allowed_evidence) or not set(
            result_handles
        ).issubset(allowed_results):
            invalid_count += 1
            continue
        if any(
            requirement_by_id[item].basis_policy == "grove_only"
            for item in requirement_ids
        ) and not (evidence_handles or result_handles):
            invalid_count += 1
            continue
        if any(item in exact_numeric for item in requirement_ids) and _NUMBER_IN_TEXT.search(
            point.text or ""
        ):
            # 精确数字只由确定性 tool fact 展示，避免模型改写或制造冲突。
            invalid_count += 1
            continue
        valid_points.append(
            point.model_copy(
                update={
                    "requirement_ids": requirement_ids,
                    "evidence_handles": evidence_handles,
                    "result_handles": result_handles,
                }
            )
        )

    covered = {
        requirement_id
        for point in valid_points
        for requirement_id in point.requirement_ids
    }
    covered.update(
        requirement_id
        for fact in execution.tool_facts
        for requirement_id in fact.requirement_ids
    )
    missing = [item.id for item in plan.requirements if item.id not in covered]
    return draft.model_copy(update={"points": valid_points}), missing, invalid_count


async def _answer_entries(
    db: AsyncSession,
    run_id: int,
    execution: CompositeAnswerExecutionSnapshot,
) -> tuple[list[dict], dict[str, list[str]]]:
    """从当前 Run 已提交 Evidence 快照重新装配有界模型上下文。"""
    evidence_requirements: dict[str, list[str]] = {}
    all_handles: list[str] = []
    for item in execution.inputs:
        for handle in item.evidence_handles:
            all_handles.append(handle)
            evidence_requirements.setdefault(handle, [])
            evidence_requirements[handle].extend(item.requirement_ids)
    evidence_requirements = {
        handle: list(dict.fromkeys(requirement_ids))
        for handle, requirement_ids in evidence_requirements.items()
    }
    rows = await resolve_evidence_handles(db, run_id, all_handles)
    evidence_requirements = {
        handle: requirement_ids
        for handle, requirement_ids in evidence_requirements.items()
        if handle in rows
    }
    by_entry: dict[int, dict] = {}
    for handle in all_handles:
        row = rows.get(handle)
        if row is None or row.entry_id is None:
            continue
        entry = by_entry.setdefault(
            row.entry_id,
            {
                "entry_id": row.entry_id,
                "title": row.entry_title or "已删除 Entry",
                "content": "",
                "project_name": row.project_name or "未知项目",
                "node_path": row.node_path or "",
                "evidences": [],
            },
        )
        entry["evidences"].append(
            {
                "handle": row.handle,
                "quote": row.quote,
                "source_title": row.source_title or "已删除来源",
            }
        )
    return list(by_entry.values()), evidence_requirements


def _execution_gaps(execution: CompositeAnswerExecutionSnapshot) -> list[str]:
    """把失败或不完整输入转成模型可见但不可伪装完成的有界缺口。"""
    gaps: list[str] = []
    for item in execution.inputs:
        if item.status in {"partial", "denied", "error", "cancelled"}:
            gaps.append(f"{item.request_id}：{item.error or '输入请求未完整执行'}")
        elif item.status == "empty":
            gaps.append(f"{item.request_id}：未找到可用的 Grove 内容")
    return gaps[:8]


def _derive_coverage(
    plan: NormalizedCompositeAnswerPlan,
    execution: CompositeAnswerExecutionSnapshot,
    answer: KnowledgeAnswerOut,
    *,
    answer_fallback: bool,
) -> CompositeAnswerCoverageSnapshot:
    """从合法 point、Citation、tool fact 与依据权限逐项派生覆盖。"""
    input_by_requirement = {
        requirement.id: [
            item
            for item in execution.inputs
            if requirement.id in item.requirement_ids
        ]
        for requirement in plan.requirements
    }
    facts_by_requirement = {
        requirement.id: [
            fact
            for fact in execution.tool_facts
            if requirement.id in fact.requirement_ids
        ]
        for requirement in plan.requirements
    }
    rows: list[CompositeRequirementCoverageSnapshot] = []
    for requirement in plan.requirements:
        points = [
            point
            for point in answer.points
            if requirement.id in point.requirement_ids
        ]
        facts = facts_by_requirement[requirement.id]
        evidence_handles = list(
            dict.fromkeys(
                citation.evidence_handle
                for point in points
                for citation in point.citations
            )
        )
        result_handles = [fact.handle for fact in facts]
        has_content = bool(points or facts)
        has_grove = bool(evidence_handles or result_handles)
        has_input_failure = any(
            item.status in {"partial", "denied", "error", "cancelled"}
            for item in input_by_requirement[requirement.id]
        )
        has_limited_fact = any(fact.completeness != "complete" for fact in facts)
        fact_texts = {fact.text for fact in facts}
        model_used = any(
            not point.citations and point.text not in fact_texts for point in points
        ) and (
            requirement.basis_policy in {"model_allowed", "grove_required", "external_required"}
        )
        note = None
        if answer_fallback and not facts:
            status = "failed"
            note = "回答模型不可用"
        elif not has_content:
            status = "insufficient"
            note = "没有合法内容覆盖该回答义务"
        elif requirement.basis_policy == "external_required":
            status = "partial"
            note = "当前未提供可核验的外部材料"
        elif requirement.basis_policy in {"grove_only", "grove_required"} and not has_grove:
            status = "partial"
            note = "未形成该义务需要的 Grove 依据"
        elif has_input_failure or has_limited_fact:
            status = "partial"
            note = "相关输入为部分结果或执行不完整"
        else:
            status = "answered"
        rows.append(
            CompositeRequirementCoverageSnapshot(
                requirement_id=requirement.id,
                status=status,
                evidence_handles=evidence_handles,
                result_handles=result_handles,
                user_message_ids=plan.statement_message_ids if model_used else [],
                model_knowledge_used=model_used,
                note=note,
            )
        )
    return CompositeAnswerCoverageSnapshot(requirements=rows)


async def build_composite_answer(
    db: AsyncSession,
    run,
    plan: NormalizedCompositeAnswerPlan,
    execution: CompositeAnswerExecutionSnapshot,
    *,
    current_message: str,
    standalone_query: str,
    scope_label: str,
    statement_context: list[dict],
    cancel_check,
) -> CompositeAnswerResult:
    """使用同一批输入最多生成两次输出，随后由服务端确定性合并与判定。"""
    entries, evidence_requirements = await _answer_entries(db, run.id, execution)
    requirements = [item.model_dump(mode="json") for item in plan.requirements]
    tool_facts = [item.model_dump(mode="json") for item in execution.tool_facts]
    execution_gaps = _execution_gaps(execution)
    allow_model = any(
        item.basis_policy in {"model_allowed", "grove_required", "external_required"}
        for item in plan.requirements
    )
    external_required = any(
        item.basis_policy == "external_required" for item in plan.requirements
    )
    selected_statements = [
        item for item in statement_context if item["message_id"] in plan.statement_message_ids
    ]

    clean_draft = KnowledgeAnswerDraft(insufficient=True)
    answer_meta = None
    retry_note = None
    for attempt in range(2):
        await cancel_check()
        draft, answer_meta = await run_knowledge_answer_agent(
            db,
            run.workspace_id,
            current_message,
            scope_label,
            entries,
            user_statements=selected_statements or None,
            allow_model_knowledge=allow_model,
            external_material_required=external_required,
            composite_context={
                "current_message": current_message,
                "standalone_query": standalone_query,
                "requirements": requirements,
                "evidence_requirements": evidence_requirements,
                "tool_facts": tool_facts,
                "execution_gaps": execution_gaps,
                "retry_note": retry_note,
            },
        )
        await record_model_invocation(
            db,
            run_id=run.id,
            meta=answer_meta,
            prompt_version=ANSWER_PROMPT_VERSION,
        )
        await db.commit()
        clean_draft, missing, invalid_count = _validated_draft_bindings(
            draft, plan, execution
        )
        if answer_meta.is_fallback or (not missing and invalid_count == 0) or attempt == 1:
            break
        retry_note = (
            f"缺少义务 {', '.join(missing) or '无'}，"
            f"存在 {invalid_count} 个非法绑定 point；请在不改变输入的前提下重新输出。"
        )

    assert answer_meta is not None
    validated, _stats = await build_validated_answer(
        db,
        run.id,
        clean_draft,
        allow_unreferenced=True,
        verifiable_gaps=execution_gaps,
    )
    requirement_order = {item.id: item.order for item in plan.requirements}
    fact_points = [
        KnowledgeAnswerPointOut(
            section=next(
                (
                    item.summary
                    for item in plan.requirements
                    if item.id == fact.requirement_ids[0]
                ),
                "结构化结果",
            ),
            text=fact.text,
            citations=[],
            requirement_ids=fact.requirement_ids,
        )
        for fact in execution.tool_facts
    ]
    combined = [*validated.points, *fact_points]
    combined.sort(
        key=lambda point: min(
            (requirement_order.get(item, 10_000) for item in point.requirement_ids),
            default=10_000,
        )
    )
    merged = validated.model_copy(
        update={
            "points": combined,
            "answer": _answer_text(combined, None) or validated.answer,
        }
    )
    coverage = _derive_coverage(
        plan,
        execution,
        merged,
        answer_fallback=answer_meta.is_fallback,
    )
    statuses = [item.status for item in coverage.requirements]
    if statuses and all(status == "answered" for status in statuses):
        answer_status = "completed"
    elif any(status in {"answered", "partial"} for status in statuses):
        answer_status = "partial"
    elif answer_meta.is_fallback and not execution.tool_facts:
        answer_status = "failed"
    else:
        answer_status = "insufficient"
    gaps = [
        item.note
        for item in coverage.requirements
        if item.status != "answered" and item.note
    ]
    merged = merged.model_copy(
        update={
            "status": answer_status,
            "gaps": list(dict.fromkeys(gaps))[:8],
            "insufficient_note": (
                "所有回答义务均缺少可用依据或合法内容"
                if answer_status == "insufficient"
                else ("回答模型不可用" if answer_status == "failed" else None)
            ),
        }
    )
    model_used = any(item.model_knowledge_used for item in coverage.requirements)
    answer_basis = build_answer_basis(
        answer=merged,
        user_statement_ids=sorted(
            {
                message_id
                for item in coverage.requirements
                for message_id in item.user_message_ids
            }
        ),
        model_knowledge_used=model_used,
        external_material_required=external_required,
        grove_result_used=bool(execution.tool_facts),
    )
    run_status = (
        RUN_FAILED
        if answer_status == "failed"
        else (RUN_PARTIAL if answer_status == "partial" else RUN_COMPLETED)
    )
    return CompositeAnswerResult(
        answer=merged,
        coverage=coverage,
        answer_basis=answer_basis,
        run_status=run_status,
        answer_fallback=answer_meta.is_fallback,
    )
