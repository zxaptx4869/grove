"""复合回答内部快照到公开 API 摘要的脱敏投影。"""

import json
import logging

from pydantic import ValidationError

from app.schemas.knowledge_agent import (
    KnowledgeCompositeAnswerCoverageOut,
    KnowledgeCompositeAnswerPlanSummaryOut,
)

logger = logging.getLogger(__name__)


def _plan_out(raw: str | None) -> KnowledgeCompositeAnswerPlanSummaryOut | None:
    """内部计划只投影义务与输入类型，不返回查询、句柄或 prompt。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        requirements = data.get("requirements", [])
        input_kinds: list[str] = []
        if data.get("retrieval_requests"):
            input_kinds.append("retrieval")
        if data.get("structured_requests"):
            input_kinds.append("structured")
        return KnowledgeCompositeAnswerPlanSummaryOut.model_validate(
            {
                "schema_version": data.get("schema_version"),
                "requirements": [
                    {
                        "id": item.get("id"),
                        "order": item.get("order"),
                        "summary": item.get("summary"),
                        "kind": item.get("kind"),
                        "basis_policy": item.get("basis_policy"),
                    }
                    for item in requirements
                    if isinstance(item, dict)
                ],
                "input_kinds": input_kinds,
            }
        )
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        logger.warning("Run 复合回答计划快照无法解析，已从公开响应省略")
        return None


def _coverage_out(
    raw: str | None,
    plan: KnowledgeCompositeAnswerPlanSummaryOut | None,
) -> KnowledgeCompositeAnswerCoverageOut | None:
    """内部覆盖句柄只投影为依据类别，损坏快照不对外猜测。"""
    if not raw or plan is None:
        return None
    summaries = {item.id: item.summary for item in plan.requirements}
    policies = {item.id: item.basis_policy for item in plan.requirements}
    try:
        data = json.loads(raw)
        output: list[dict] = []
        for item in data.get("requirements", []):
            if not isinstance(item, dict):
                continue
            requirement_id = item.get("requirement_id")
            if requirement_id not in summaries:
                raise ValueError("覆盖快照引用未知回答义务")
            basis_kinds: list[str] = []
            if item.get("evidence_handles"):
                basis_kinds.append("grove_evidence")
            if item.get("result_handles"):
                basis_kinds.append("structured_result")
            if item.get("user_message_ids"):
                basis_kinds.append("user_statement")
            if item.get("model_knowledge_used"):
                basis_kinds.append("model_knowledge")
            if policies[requirement_id] == "external_required":
                basis_kinds.append("external_gap")
            output.append(
                {
                    "requirement_id": requirement_id,
                    "summary": summaries[requirement_id],
                    "status": item.get("status"),
                    "basis_kinds": basis_kinds,
                    "note": item.get("note"),
                }
            )
        return KnowledgeCompositeAnswerCoverageOut.model_validate(
            {
                "schema_version": data.get("schema_version"),
                "requirements": output,
            }
        )
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        logger.warning("Run 复合回答覆盖快照无法解析，已从公开响应省略")
        return None


def composite_answer_out(
    plan_raw: str | None,
    coverage_raw: str | None,
) -> tuple[
    KnowledgeCompositeAnswerPlanSummaryOut | None,
    KnowledgeCompositeAnswerCoverageOut | None,
]:
    """统一生成 Run 与消息页的生成时快照投影。"""
    plan = _plan_out(plan_raw)
    return plan, _coverage_out(coverage_raw, plan)
