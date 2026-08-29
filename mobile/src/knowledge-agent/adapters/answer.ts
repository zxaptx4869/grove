/** 回答卡展示适配：依据 answer.status 区分五种状态，不被 Run 状态掩盖。 */

import type {
  AnswerStatus,
  InvestigationStopReason,
  KnowledgeAnswer,
  KnowledgeRun,
  RunStatus,
} from "@/src/knowledge-agent/types";

export interface AnswerPresentation {
  status: AnswerStatus | "cancelled";
  headline: string;
  note: string | null;
  tone: "positive" | "risk" | "neutral";
}

const STOP_REASON_LABELS: Record<InvestigationStopReason, string> = {
  controller_complete: "控制器已完成调查",
  insufficient: "当前知识不足以继续补充证据",
  no_progress: "没有发现更多可核验证据",
  max_rounds: "已达到调查轮次上限",
  query_budget: "已达到查询数量预算",
  entry_budget: "已达到 Entry 数量预算",
  evidence_budget: "已达到证据数量预算",
  cancelled: "调查已取消",
  failed: "调查执行失败",
};

/** 受限的 Markdown 标记清洗：不渲染任意 Markdown/HTML，只去掉常见标记符号。
 *
 * 后端回答模型可能输出 `**加粗**`、`## 标题`、`- 列表` 等标记；原生 Text
 * 不解析 Markdown，直接展示会裸露星号和井号。这里保留换行与内容顺序，
 * 只移除标记字符，不引入任何富文本渲染。行内单星号不做处理，避免误删
 * 正文中的成对星号（如「100*50」）。
 */
export function cleanAnswerText(text: string): string {
  return text
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/(^|\n)[ \t]*#{1,6}[ \t]+/g, "$1")
    .replace(/(^|\n)[ \t]*[-*][ \t]+/g, "$1")
    .replace(/(^|\n)[ \t]*\d+[.、][ \t]+/g, "$1")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function stopReasonLabel(reason: InvestigationStopReason | null | undefined): string | null {
  return reason ? STOP_REASON_LABELS[reason] ?? "已停止调查" : null;
}

export function presentAnswer(
  answer: KnowledgeAnswer | null,
  runStatus: RunStatus,
): AnswerPresentation {
  if (runStatus === "cancelled" && answer === null) {
    return {
      status: "cancelled",
      headline: "已取消",
      note: "没有生成正常回答，可以重新提问。",
      tone: "neutral",
    };
  }
  const status = answer?.status ?? "failed";
  // 契约上是 insufficient，但回答包含有效引用与实质内容时，按「部分结果」
  // 展示并保留预算/缺口说明，避免与下方完整回答自相矛盾；完全无引用仍为知识不足。
  if (
    status === "insufficient" &&
    answer !== null &&
    answer.citations.length > 0 &&
    answer.answer.trim() !== ""
  ) {
    return {
      status: "partial",
      headline: "部分结果",
      note:
        answer.insufficientNote ??
        "当前知识存在缺口，以下为已有证据范围内的有效内容。",
      tone: "risk",
    };
  }
  switch (status) {
    case "completed":
      return {
        status,
        headline: "基于正式知识",
        note: null,
        tone: "positive",
      };
    case "partial":
      return {
        status,
        headline: "部分结果",
        note: "部分检索或证据步骤降级，保留的有效内容与引用如下。",
        tone: "risk",
      };
    case "insufficient":
      return {
        status,
        headline: "知识不足",
        note:
          answer?.insufficientNote ??
          "当前知识库没有足够可核验的证据，我没有用模型常识补齐。",
        tone: "risk",
      };
    case "clarification":
      return {
        status,
        headline: "需要澄清",
        note: answer?.insufficientNote ?? "请补充必要信息后继续提问。",
        tone: "neutral",
      };
    case "failed":
    default:
      return {
        status,
        headline: "回答失败",
        note: "回答模型或工具暂不可用，可以重新提问。",
        tone: "risk",
      };
  }
}

export function investigationSummaryLine(
  summary: KnowledgeRun["investigationSummary"],
): string | null {
  if (!summary) return null;
  const rounds = summary.roundsCompleted;
  const queries = summary.queriesExecuted;
  return `深度查找 · ${rounds} 轮 / ${queries} 次查询`;
}
