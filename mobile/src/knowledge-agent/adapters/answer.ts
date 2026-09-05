/** 回答卡展示适配：依据 answer.status 区分五种状态，不被 Run 状态掩盖。 */

import type {
  AnswerStatus,
  ExternalMaterialStatus,
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

export interface DraftActionEligibility {
  eligible: boolean;
  sourceRunId: number | null;
  /** 可选目标项目（来自最终 citations 的项目归属，服务端会再次校验）。 */
  projectOptions: { id: number; name: string | null }[];
  /** 项目范围回答固定目标；Workspace 回答为 null。 */
  fixedProjectId: number | null;
  /** partial 回答只整理有依据部分。 */
  note: string | null;
}

/** 依据概览：只从服务端结构化 answer_basis 派生，不解析正文或工具过程。 */
export interface AnswerBasisView {
  basisKind: "grove" | "model" | "hybrid";
  /** 卡片语义标签：基于你的知识 / AI 即时回答 / 混合依据。 */
  label: string;
  /** 紧凑展示片段（用「 · 」连接）。 */
  segments: string[];
  groveCitationCount: number;
  userStatementIds: number[];
  modelKnowledgeUsed: boolean;
  externalStatus: ExternalMaterialStatus | null;
  /** 是否有可展开详情（Grove/用户陈述/模型知识/外部边界）。 */
  hasDetail: boolean;
}

export interface RevisionTarget {
  entryId: number;
  entryTitle: string;
  projectId: number;
  projectName: string | null;
  nodePath: string | null;
}

export interface RevisionEligibility {
  eligible: boolean;
  sourceRunId: number | null;
  targets: RevisionTarget[];
  /** partial 回答只修订有依据部分。 */
  note: string | null;
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
        note: "已保留可用回答，仍有未覆盖或未核验的内容。",
        tone: "risk",
      };
    case "insufficient":
      return {
        status,
        headline: "知识不足",
        note:
          answer?.insufficientNote ??
          "当前材料尚不足以直接回答核心问题。",
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

/** 依据展示只读派生：旧回答缺少 answer_basis 时返回 null，沿用现有展示。 */
export function answerBasisView(
  run: KnowledgeRun,
): AnswerBasisView | null {
  const basis = run.answerBasis;
  if (!basis) return null;
  const groveCount = basis.grove.citationCount;
  const userStatementIds = [...basis.userStatements.messageIds];
  const modelUsed = basis.modelKnowledge.used;
  const external = basis.externalMaterial;
  const nothingUsed =
    !basis.grove.used &&
    !modelUsed &&
    userStatementIds.length === 0 &&
    external.status === "not_used";
  if (nothingUsed) {
    // 严格知识不足/无实际形成依据：不伪造“AI 即时回答”或“混合依据”。
    return null;
  }
  if (
    !basis.grove.used &&
    !modelUsed &&
    userStatementIds.length === 0 &&
    external.status === "required_unavailable"
  ) {
    return {
      basisKind: "hybrid",
      label: "需要外部材料",
      segments: ["未检索实时外部资料，当前需要外部材料"],
      groveCitationCount: 0,
      userStatementIds,
      modelKnowledgeUsed: false,
      externalStatus: external.status,
      hasDetail: true,
    };
  }
  const groveOnly =
    basis.grove.used && !modelUsed && userStatementIds.length === 0;
  const modelOnly =
    !basis.grove.used && modelUsed && userStatementIds.length === 0;

  const segments: string[] = [];
  if (groveCount > 0) {
    segments.push(`你的知识 ${groveCount} 条`);
  }
  if (userStatementIds.length > 0) {
    segments.push(`结合你提供的 ${userStatementIds.length} 条信息`);
  }
  if (modelUsed) {
    segments.push(groveOnly ? "AI 通用知识" : "AI 通用知识补充");
  }
  if (external.status === "required_unavailable") {
    segments.push("当前需要外部材料，未检索实时外部资料");
  } else if (modelOnly) {
    segments.push("未使用你的知识库", "未检索实时外部资料");
  }

  if (groveOnly) {
    return {
      basisKind: "grove",
      label: "基于你的知识",
      segments: segments.length > 0 ? segments : ["基于你的知识"],
      groveCitationCount: groveCount,
      userStatementIds,
      modelKnowledgeUsed: false,
      externalStatus: external.status,
      hasDetail: groveCount > 0,
    };
  }
  if (modelOnly) {
    return {
      basisKind: "model",
      label: "AI 即时回答",
      segments:
        segments.length > 0
          ? segments
          : ["AI 通用知识", "未检索实时外部资料"],
      groveCitationCount: 0,
      userStatementIds,
      modelKnowledgeUsed: true,
      externalStatus: external.status,
      hasDetail:
        external.status === "required_unavailable" ||
        userStatementIds.length > 0,
    };
  }
  // 混合依据：Grove 与用户陈述/模型知识并存
  return {
    basisKind: "hybrid",
    label: "混合依据",
    segments:
      segments.length > 0
        ? segments
        : ["结合你提供的信息", "AI 通用知识补充"],
    groveCitationCount: groveCount,
    userStatementIds,
    modelKnowledgeUsed: modelUsed,
    externalStatus: external.status,
    hasDetail:
      groveCount > 0 ||
      userStatementIds.length > 0 ||
      external.status === "required_unavailable",
  };
}

export function draftActionEligibility(
  run: KnowledgeRun,
): DraftActionEligibility {
  const answer = run.answer;
  const status = answer?.status ?? null;
  const basis = run.answerBasis;
  // 旧客户端/旧缓存可能缺少 runKind：默认视为普通 answer Run，保持兼容
  const runKind = run.runKind ?? "answer";
  // 新 Run：只有可证明的纯 Grove 依据才能进入旧整理入口；模型知识、
  // 用户陈述或外部材料缺口即使含 Citation 也隐藏入口（服务端仍会再次校验）。
  const openBasisIneligible =
    basis !== undefined &&
    basis !== null &&
    (basis.modelKnowledge.used ||
      basis.userStatements.messageIds.length > 0 ||
      basis.externalMaterial.status === "required_unavailable");
  const eligible =
    runKind === "answer" &&
    (status === "completed" || status === "partial") &&
    (answer?.citations.length ?? 0) > 0 &&
    !openBasisIneligible;
  const options = new Map<number, string | null>();
  for (const citation of answer?.citations ?? []) {
    if (citation.projectId && !options.has(citation.projectId)) {
      options.set(citation.projectId, citation.projectName ?? null);
    }
  }
  return {
    eligible,
    sourceRunId: eligible ? run.id : null,
    projectOptions: [...options.entries()].map(([id, name]) => ({ id, name })),
    fixedProjectId:
      run.scopeType === "project" ? (run.projectId ?? null) : null,
    note:
      eligible && status === "partial"
        ? "只整理有依据部分，未解决的缺口不会进入草稿。"
        : null,
  };
}

/** 单 Entry 修订目标：只从最终 citations 中当前 Entry 快照提取，客户端不自行生成对象 ID。 */
export function revisionEligibility(run: KnowledgeRun): RevisionEligibility {
  const answer = run.answer;
  const status = answer?.status ?? null;
  const runKind = run.runKind ?? "answer";
  const targets: RevisionTarget[] = [];
  const seen = new Set<number>();
  for (const citation of answer?.citations ?? []) {
    if (citation.entryId === 0 || seen.has(citation.entryId)) continue;
    seen.add(citation.entryId);
    targets.push({
      entryId: citation.entryId,
      entryTitle: citation.entryTitle,
      projectId: citation.projectId ?? run.projectId ?? 0,
      projectName: citation.projectName ?? run.projectName ?? null,
      nodePath: citation.nodePath,
    });
  }
  const eligible =
    runKind === "answer" &&
    (status === "completed" || status === "partial") &&
    targets.length > 0;
  return {
    eligible,
    sourceRunId: eligible ? run.id : null,
    targets,
    note:
      eligible && status === "partial"
        ? "只修订有依据部分，未解决的缺口不会写入正式知识。"
        : null,
  };
}

export function investigationSummaryLine(
  summary: KnowledgeRun["investigationSummary"],
): string | null {
  if (!summary) return null;
  const rounds = summary.roundsCompleted;
  const queries = summary.queriesExecuted;
  return `深度查找 · ${rounds} 轮 / ${queries} 次查询`;
}
