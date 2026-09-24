/** 来源库查询键：列表按筛选分键，详情与候选按来源分键。 */

import type { SourceFilter } from "@/src/sources/types";

export const sourceKeys = {
  all: ["sources"] as const,
  list: (filter: SourceFilter) => ["sources", "list", filter] as const,
  detail: (sourceId: number) => ["sources", "detail", sourceId] as const,
  candidates: (sourceId: number) => ["sources", "candidates", sourceId] as const,
};
