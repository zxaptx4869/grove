"""知识 Agent 调查账本：当前 Run 的受控派生状态、去重、序列化与重建。

账本只服务当前 Run 的恢复、审计与最终综合，不是正式知识或跨对话记忆；
对象只保存稳定 ID、短摘要与轮次归属，不复制整份 Entry/Attachment/prompt。
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeAgentEvidence
from app.models.knowledge_agent import (
    KnowledgeInvestigation,
    KnowledgeInvestigationQuery,
    KnowledgeInvestigationRound,
)

logger = logging.getLogger(__name__)

# 账本中的文本只保留受限摘要长度
LEDGER_ENTRY_TITLE_CHARS = 255
LEDGER_QUOTE_CHARS = 120


def clean_query_text(text: str) -> str:
    """去除查询文本首尾与内部多余空白。"""
    return " ".join(str(text).split())


def normalize_query_text(text: str) -> str:
    """规范化查询文本：去全部空白 + 小写，用于指纹与全局去重。

    空白差异（包括字间空格）不产生新查询；执行时仍使用保留单空格的
    `clean_query_text` 文本。
    """
    return clean_query_text(text).replace(" ", "").lower()


def query_fingerprint(text: str) -> str:
    """计算规范化查询的 sha256 指纹（Run 内唯一）。"""
    return hashlib.sha256(normalize_query_text(text).encode("utf-8")).hexdigest()


def dedupe_proposed_queries(
    proposed: list[str],
    executed_hashes: set[str],
    *,
    max_queries: int,
) -> tuple[list[str], list[str]]:
    """把控制器提出的查询去重：返回 (合法新查询, 重复/空白查询)。

    重复查询不执行、不计实际查询数；空白查询直接丢弃；部分重复只保留
    去重后的合法新查询，直到达到每轮上限。
    """
    new_queries: list[str] = []
    duplicates: list[str] = []
    seen = set(executed_hashes)
    for raw in proposed:
        text = clean_query_text(raw)
        if not text:
            continue
        fingerprint = query_fingerprint(text)
        if fingerprint in seen:
            duplicates.append(text)
            continue
        seen.add(fingerprint)
        new_queries.append(text)
        if len(new_queries) >= max_queries:
            break
    return new_queries, duplicates


@dataclass
class LedgerEntryRef:
    """已发现 Entry 的紧凑线索。"""

    entry_id: int
    entry_title: str = ""
    project_name: str | None = None
    node_path: str = ""
    round_number: int = 0


@dataclass
class LedgerEvidenceRef:
    """当前 Run 可引用 Evidence 的紧凑线索。"""

    evidence_id: int
    handle: str
    entry_id: int
    source_id: int
    source_title: str = ""
    attachment_id: int | None = None
    quote: str = ""
    round_number: int = 0


@dataclass
class InvestigationLedger:
    """跨轮次账本：查询、已发现 Entry、Evidence、观察摘要与不可用对象。"""

    executed_queries: list[dict] = field(default_factory=list)
    executed_query_hashes: set[str] = field(default_factory=set)
    discovered_entries: dict[int, LedgerEntryRef] = field(default_factory=dict)
    evidences: dict[int, LedgerEvidenceRef] = field(default_factory=dict)
    evidence_handles: set[str] = field(default_factory=set)
    coverage: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)

    def add_executed_query(self, *, fingerprint: str, text: str, round_number: int) -> bool:
        """记录一条实际/已持久化查询；重复指纹返回 False。"""
        if fingerprint in self.executed_query_hashes:
            return False
        self.executed_query_hashes.add(fingerprint)
        self.executed_queries.append(
            {"hash": fingerprint, "text": text, "round_number": round_number}
        )
        return True

    def add_entry(self, ref: LedgerEntryRef) -> bool:
        """按 Entry 身份去重；同 Entry 多次命中只保留首条线索。"""
        if ref.entry_id in self.discovered_entries:
            return False
        self.discovered_entries[ref.entry_id] = ref
        return True

    def add_evidence(self, ref: LedgerEvidenceRef) -> bool:
        """按 Evidence 身份去重；跨轮命中同一 Evidence 幂等复用。"""
        if ref.evidence_id in self.evidences:
            return False
        self.evidences[ref.evidence_id] = ref
        if ref.handle:
            self.evidence_handles.add(ref.handle)
        return True

    def add_unavailable(
        self,
        *,
        kind: str,
        obj_id: int | None,
        reason: str,
        round_number: int,
    ) -> None:
        """记录不可用/越权对象（不进已发现集合，不影响可引用 Evidence）。"""
        self.unavailable.append(
            {"kind": kind, "id": obj_id, "reason": reason, "round_number": round_number}
        )

    def set_observations(
        self,
        *,
        coverage: list[str],
        gaps: list[str],
        conflicts: list[str],
    ) -> None:
        """用控制器本轮观察覆盖账本摘要（过程元数据，不是事实）。"""
        self.coverage = list(coverage)
        self.gaps = list(gaps)
        self.conflicts = list(conflicts)

    def distinct_entry_count(self) -> int:
        return len(self.discovered_entries)

    def discovered_entry_count(self) -> int:
        """本轮及后续新发现 Entry 数（工作集种子 round=0 不计入预算）。"""
        return sum(1 for ref in self.discovered_entries.values() if ref.round_number > 0)

    def distinct_evidence_count(self) -> int:
        return len(self.evidences)

    def controller_summary(self, *, max_chars: int) -> str:
        """紧凑账本文本：只含 ID、短摘要与轮次归属，不复制整份原文。"""
        parts = [
            f"已发现 Entry {len(self.discovered_entries)} 条；"
            f"可引用 Evidence {len(self.evidences)} 条"
        ]
        if self.discovered_entries:
            entries = "；".join(
                f"#{ref.entry_id} {ref.entry_title[:30]}"
                for ref in sorted(
                    self.discovered_entries.values(), key=lambda item: item.entry_id
                )
            )
            parts.append("Entry：" + entries[:600])
        if self.evidences:
            evidence = "；".join(
                f"#{ref.evidence_id} {ref.quote[:LEDGER_QUOTE_CHARS]}"
                for ref in sorted(
                    self.evidences.values(), key=lambda item: item.evidence_id
                )
            )
            parts.append("Evidence：" + evidence[:600])
        if self.coverage:
            parts.append("已覆盖：" + "；".join(self.coverage)[:300])
        if self.gaps:
            parts.append("缺口：" + "；".join(self.gaps)[:300])
        if self.conflicts:
            parts.append("冲突线索：" + "；".join(self.conflicts)[:300])
        return "\n".join(parts)[:max_chars]

    def round_entries_payload(self, round_number: int) -> list[dict]:
        """本轮新增 Entry 的持久化短快照（账本重建线索）。"""
        return [
            {
                "entry_id": ref.entry_id,
                "entry_title": ref.entry_title[:LEDGER_ENTRY_TITLE_CHARS],
                "project_name": ref.project_name,
                "node_path": ref.node_path,
                "round_number": ref.round_number,
            }
            for ref in self.discovered_entries.values()
            if ref.round_number == round_number
        ]

    def round_payload(self, round_number: int) -> dict:
        """本轮账本持久化载荷：Entry 线索、不可用对象与观察摘要。"""
        return {
            "entries": self.round_entries_payload(round_number),
            "unavailable": [
                item
                for item in self.unavailable
                if item["round_number"] == round_number
            ],
            "coverage": self.coverage,
            "gaps": self.gaps,
            "conflicts": self.conflicts,
        }

    def restore_round_payload(self, payload: dict, round_number: int) -> None:
        """把一轮持久化载荷恢复到账本（重建时使用）。"""
        for item in payload.get("entries", []):
            self.add_entry(
                LedgerEntryRef(
                    entry_id=int(item["entry_id"]),
                    entry_title=item.get("entry_title", ""),
                    project_name=item.get("project_name"),
                    node_path=item.get("node_path", ""),
                    round_number=int(item.get("round_number", round_number)),
                )
            )
        for item in payload.get("unavailable", []):
            self.add_unavailable(
                kind=item.get("kind", "unknown"),
                obj_id=item.get("id"),
                reason=item.get("reason", ""),
                round_number=int(item.get("round_number", round_number)),
            )
        if payload.get("coverage") is not None:
            self.coverage = list(payload["coverage"])
            self.gaps = list(payload.get("gaps", []))
            self.conflicts = list(payload.get("conflicts", []))


async def rebuild_ledger(
    db: AsyncSession,
    investigation: KnowledgeInvestigation,
    run_id: int,
) -> InvestigationLedger:
    """从已提交轮次、查询与 Evidence 确定性重建当前 Run 账本。

    崩溃恢复复用该结果：已执行查询、已发现 Entry、Evidence、观察摘要
    与剩余预算都能从持久化行重建，不重复提交已完成的轮次。
    """
    ledger = InvestigationLedger()
    rounds = (
        await db.execute(
            select(KnowledgeInvestigationRound)
            .where(KnowledgeInvestigationRound.investigation_id == investigation.id)
            .order_by(KnowledgeInvestigationRound.round_number)
        )
    ).scalars().all()
    queries = (
        await db.execute(
            select(KnowledgeInvestigationQuery)
            .where(KnowledgeInvestigationQuery.investigation_id == investigation.id)
            .order_by(
                KnowledgeInvestigationQuery.round_number,
                KnowledgeInvestigationQuery.sequence,
            )
        )
    ).scalars().all()
    evidences = (
        await db.execute(
            select(KnowledgeAgentEvidence)
            .where(
                KnowledgeAgentEvidence.run_id == run_id,
                KnowledgeAgentEvidence.is_citable.is_(True),
            )
            .order_by(KnowledgeAgentEvidence.id)
        )
    ).scalars().all()

    for query in queries:
        ledger.add_executed_query(
            fingerprint=query.normalized_query_hash,
            text=query.normalized_query,
            round_number=query.round_number,
        )
    for round_row in rounds:
        if round_row.entries_json:
            try:
                payload = json.loads(round_row.entries_json)
            except (json.JSONDecodeError, TypeError):
                payload = None
            if payload is not None:
                ledger.restore_round_payload(
                    {"entries": payload},
                    round_row.round_number,
                )
        if round_row.unavailable_json:
            try:
                unavailable = json.loads(round_row.unavailable_json)
            except (json.JSONDecodeError, TypeError):
                unavailable = None
            if isinstance(unavailable, list):
                for item in unavailable:
                    ledger.add_unavailable(
                        kind=item.get("kind", "unknown"),
                        obj_id=item.get("id"),
                        reason=item.get("reason", ""),
                        round_number=int(item.get("round_number", round_row.round_number)),
                    )
        # 观察摘要取最近一轮（控制器视角的最新覆盖/缺口/冲突）；
        # 空数组也是有效观察（本轮明确无覆盖/缺口/冲突），不能回退到旧轮
        if round_row.coverage_json is not None:
            try:
                coverage = json.loads(round_row.coverage_json)
                gaps = json.loads(round_row.gaps_json or "[]")
                conflicts = json.loads(round_row.conflicts_json or "[]")
            except (json.JSONDecodeError, TypeError):
                coverage, gaps, conflicts = [], [], []
            ledger.set_observations(
                coverage=coverage,
                gaps=gaps,
                conflicts=conflicts,
            )
    for evidence in evidences:
        ledger.add_evidence(
            LedgerEvidenceRef(
                evidence_id=evidence.id,
                handle=evidence.handle,
                entry_id=evidence.entry_id or 0,
                source_id=evidence.source_id or 0,
                source_title=evidence.source_title or "",
                attachment_id=evidence.attachment_id,
                quote=evidence.quote[:LEDGER_QUOTE_CHARS],
                round_number=evidence.round_number or 0,
            )
        )
    return ledger
