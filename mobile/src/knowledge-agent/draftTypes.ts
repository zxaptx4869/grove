/** 草稿主类型枚举与中文标签：草稿卡与编辑 Sheet 共用。 */

export const DRAFT_MAIN_TYPES = [
  "knowledge",
  "method",
  "parameter",
  "reminder",
] as const;

export const DRAFT_MAIN_TYPE_LABELS: Record<string, string> = {
  knowledge: "知识",
  method: "方法",
  parameter: "参数",
  reminder: "提醒",
};

export function draftMainTypeLabel(mainType: string | null | undefined): string {
  if (!mainType) return "";
  return DRAFT_MAIN_TYPE_LABELS[mainType] ?? mainType;
}
