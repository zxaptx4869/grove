/** 结构化 Entry 结果展示适配：完整性文案与状态语义。 */

import type {
  KnowledgeEntryResultSnapshot,
  ResultCompleteness,
  ResultMode,
} from "@/src/knowledge-agent/types";

export const ENTRY_RESULT_PAGE_SIZE = 6;

export function resultModeLabel(mode: ResultMode | null | undefined): string {
  if (mode === "entries") return "知识列表";
  if (mode === "answer") return "综合回答";
  return "";
}

export function completenessCopy(
  completeness: ResultCompleteness,
): string {
  switch (completeness) {
    case "complete":
      return "已完整列出当前范围匹配的正式知识";
    case "limited":
      return "本次结果可能不完整，可缩小条件再找";
    case "unknown":
      return "本次结果完整性未知，可缩小条件再找";
  }
}

export function resultStatusCopy(
  snapshot: KnowledgeEntryResultSnapshot | null,
): string {
  if (!snapshot) return "";
  if (snapshot.status === "partial") {
    return "部分匹配对象当前不可用，结果可能不完整";
  }
  return "";
}

export function firstPageItems(
  snapshot: KnowledgeEntryResultSnapshot | null,
): KnowledgeEntryResultSnapshot["items"] {
  if (!snapshot) return [];
  return snapshot.items.slice(0, ENTRY_RESULT_PAGE_SIZE);
}

export function snapshotHasMore(
  snapshot: KnowledgeEntryResultSnapshot | null,
): boolean {
  if (!snapshot) return false;
  return snapshot.items.length > ENTRY_RESULT_PAGE_SIZE;
}
