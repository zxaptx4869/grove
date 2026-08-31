/** Run current_step → 用户可验证的有限过程文案，不展示隐藏推理。 */

import type { KnowledgeRun } from "@/src/knowledge-agent/types";

export interface StepPresentation {
  title: string;
}

const STEP_TITLES: Record<string, string> = {
  waiting: "准备",
  claim: "准备",
  context_decision: "理解问题",
  result_mode_route: "判断结果形式",
  answer_mode_route: "选择回答方式",
  investigation_route: "选择回答方式",
  search: "检索正式知识",
  entry_search: "查找正式知识",
  entry_assemble: "整理结果",
  read_entries: "读取 Entry",
  read_evidence: "核验证据",
  round_plan: "深度查找",
  round_search: "深度查找",
  round_evidence: "深度查找",
  synthesize: "综合回答",
  organize_answer: "综合回答",
  validate_references: "综合回答",
  finalize: "综合回答",
};

export function presentRunStep(
  run: Pick<
    KnowledgeRun,
    "currentStep" | "currentRound" | "actualAnswerMode" | "actualResultMode"
  >,
): StepPresentation {
  const step = run.currentStep ?? "waiting";
  if (run.actualResultMode === "entries") {
    const titles: Record<string, string> = {
      waiting: "准备",
      claim: "准备",
      context_decision: "理解问题",
      result_mode_route: "判断结果形式",
      entry_search: "查找正式知识",
      entry_assemble: "整理结果",
      finalize: "整理结果",
    };
    return { title: titles[step] ?? "正在处理" };
  }
  const title = STEP_TITLES[step] ?? "正在处理";
  if (step.startsWith("round_") && run.actualAnswerMode === "investigate") {
    const round = Math.max(1, run.currentRound || 1);
    return { title: `深度查找 · 第 ${round} 轮` };
  }
  return { title };
}
