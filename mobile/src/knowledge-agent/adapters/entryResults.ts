/** 结构化 Entry 结果展示适配：完整性文案与状态语义。 */

import type {
  KnowledgeCountResult,
  KnowledgeEntrySetSummary,
  KnowledgeEntryResultSnapshot,
  KnowledgeGroupCountResult,
  KnowledgeEntrySort,
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

const MAIN_TYPE_LABELS: Record<string, string> = {
  knowledge: "知识",
  method: "方法",
  parameter: "参数",
  reminder: "提醒",
};

const INFO_NATURE_LABELS: Record<string, string> = {
  fact: "事实",
  experience: "经验",
  advice: "建议",
  speculation: "推测",
  other: "其他",
  unspecified: "未标注",
};

function listLabels(values: string[], labels: Record<string, string>): string {
  return values.map((value) => labels[value] ?? value).join("、");
}

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}

export function structuredFilterCopies(
  summary: KnowledgeEntrySetSummary | null | undefined,
): string[] {
  if (!summary) return [];
  const copies: string[] = [];
  if (summary.semanticQuery) copies.push(`语义：${summary.semanticQuery}`);
  if (summary.mainTypes.length > 0) {
    copies.push(`类型：${listLabels(summary.mainTypes, MAIN_TYPE_LABELS)}`);
  }
  if (summary.infoNatures.length > 0) {
    copies.push(`性质：${listLabels(summary.infoNatures, INFO_NATURE_LABELS)}`);
  }
  if (summary.updatedAtFrom || summary.updatedAtTo) {
    const start = summary.updatedAtFrom ? dateLabel(summary.updatedAtFrom) : "不限";
    const end = summary.updatedAtTo ? dateLabel(summary.updatedAtTo) : "至今";
    copies.push(`更新时间：${start} 至 ${end}`);
  }
  return copies;
}

export function structuredCompletenessCopy(
  completeness: ResultCompleteness,
): string {
  if (completeness === "complete") {
    return "筛选集合可精确统计；知识列表按计划有界展示";
  }
  if (completeness === "limited") {
    return "统计只覆盖本次匹配结果，不代表当前范围内的全部知识";
  }
  return "本次集合完整性未知，统计结果可能不完整";
}

export function countCopy(count: KnowledgeCountResult): string {
  return count.completeness === "complete"
    ? `共 ${count.value} 条`
    : `本次匹配到 ${count.value} 条`;
}

export function groupLabel(group: KnowledgeGroupCountResult): string {
  if (group.groupBy === "main_type") return "按知识类型";
  if (group.groupBy === "info_nature") return "按信息性质";
  return "按更新月份";
}

export function groupBucketLabel(
  group: KnowledgeGroupCountResult,
  key: string,
): string {
  if (group.groupBy === "main_type") return MAIN_TYPE_LABELS[key] ?? key;
  if (group.groupBy === "info_nature") return INFO_NATURE_LABELS[key] ?? key;
  return key;
}

export function sortCopy(sort: KnowledgeEntrySort | null | undefined): string {
  if (!sort) return "";
  const direction = sort.direction === "desc" ? "倒序" : "正序";
  if (sort.field === "relevance") return `按相关性${direction}`;
  if (sort.field === "created_at") return `按创建时间${direction}`;
  return `按更新时间${direction}`;
}
