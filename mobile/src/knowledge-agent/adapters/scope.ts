import type { KnowledgeScopeType } from "@/src/knowledge-agent/types";

export function scopeLabel(
  scopeType: KnowledgeScopeType,
  projectName: string | null | undefined,
): string {
  if (scopeType === "project") {
    return projectName ?? "项目";
  }
  return "全部知识";
}
