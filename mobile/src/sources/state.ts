/**
 * 来源库的纯派生逻辑：状态徽标、`done` 副状态、时间文案、重试与两个操作的阻断判定。
 *
 * 这些口径都能被单测直接覆盖，界面组件只负责渲染，避免展示规则散落在 JSX 里。
 */

import type { Project } from "@/src/api";
import type { BadgeTone } from "@/src/knowledge-agent/components/ui";
import type { SourceIconName } from "@/src/sources/components/SourceIcon";
import type { CandidateOut, SourceOut } from "@/src/sources/types";

export const WAITING = "waiting";
export const PROCESSING = "processing";
export const DONE = "done";
export const FAILED = "failed";

/**
 * 列表轮询间隔（前台）。
 * 处理链路包含抽取、项目路由与关系判定多次模型调用，正常耗时在数十秒量级；
 * 对话 Run 的 2 秒是逐字输出的即时感要求，后台任务状态用 4 秒即可让完成反馈及时，
 * 同时把移动网络请求量减半。依据见 change 的 design.md。
 */
export const SOURCE_POLL_INTERVAL_MS = 4000;

export function hasActiveSources(sources: SourceOut[] | undefined): boolean {
  // 处理中一定会变（Worker 正在跑）；等待处理只有存在处理任务才会变，
  // 「处理未启动」的条目需要用户手动重试，没有任务时轮询只会空转。
  return Boolean(
    sources?.some(
      (source) =>
        source.status === PROCESSING ||
        (source.status === WAITING && source.has_processing_task),
    ),
  );
}

/** 仅前台且存在处理中或「等待处理且有处理任务」的条目时轮询，否则返回 false 停止定时请求。 */
export function shouldPollSources(
  sources: SourceOut[] | undefined,
  appActive: boolean,
): number | false {
  return appActive && hasActiveSources(sources) ? SOURCE_POLL_INTERVAL_MS : false;
}

/** 等待处理但没有处理任务：处理 Worker 永远不会轮询到它，必须给出重试入口。 */
export function isProcessingNotStarted(source: SourceOut): boolean {
  return source.status === WAITING && !source.has_processing_task;
}

export type BadgeDescriptor = { label: string; tone: BadgeTone; icon: SourceIconName };

export function sourceStatusBadge(source: SourceOut): BadgeDescriptor {
  if (isProcessingNotStarted(source)) {
    return { label: "处理未启动", tone: "risk", icon: "alert" };
  }
  if (source.status === PROCESSING) return { label: "处理中", tone: "ai", icon: "clock" };
  if (source.status === WAITING) return { label: "等待处理", tone: "neutral", icon: "clock" };
  if (source.status === FAILED) return { label: "处理失败", tone: "error", icon: "alert" };
  if (source.status === DONE) return { label: "提取完成", tone: "confirmed", icon: "check" };
  return { label: source.status, tone: "neutral", icon: "info" };
}

/** `done` 副状态：待确认 N 条 / 部分确认 · N 条正式知识 / N 条正式知识 / 还没有候选。 */
export function sourceSubStatus(source: SourceOut): BadgeDescriptor | null {
  if (source.status !== DONE) return null;
  const pending = source.pending_candidate_count;
  const evidence = source.evidence_entry_count;
  if (pending > 0 && evidence > 0) {
    return {
      label: `部分确认 · ${evidence} 条正式知识`,
      tone: "ai",
      icon: "info",
    };
  }
  if (pending > 0) return { label: `待确认 ${pending} 条`, tone: "ai", icon: "info" };
  if (evidence > 0) return { label: `${evidence} 条正式知识`, tone: "confirmed", icon: "check" };
  return { label: "还没有候选", tone: "neutral", icon: "info" };
}

export function sourceKind(source: SourceOut): "image" | "text" {
  return source.attachments.some((item) => item.kind === "text") ? "text" : "image";
}

export function imageAttachments(source: SourceOut) {
  return source.attachments.filter((item) => item.kind === "image");
}

/** 放大查看里切换图片：到头就停住，不做首尾环绕（与系统相册一致）。 */
export function nextImageIndex(current: number | null, total: number, delta: number) {
  if (current === null || total <= 0) return current;
  return Math.min(Math.max(current + delta, 0), total - 1);
}

export function textContent(source: SourceOut): string {
  return source.attachments.find((item) => item.kind === "text")?.text_content ?? "";
}

export function ocrText(source: SourceOut): string {
  return source.attachments
    .map((item) => item.ocr_text?.trim())
    .filter((value): value is string => Boolean(value))
    .join("\n\n");
}

export function sourceMaterialSummary(source: SourceOut): string {
  if (sourceKind(source) === "text") return "文字";
  return `${imageAttachments(source).length} 张图片`;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function isSameDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

/** 列表时间文案：今天 10:12 / 昨天 18:05 / 9 月 20 日 15:20 / 2025 年 9 月 20 日。 */
export function formatSourceTime(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (isSameDay(date, now)) return `今天 ${clock}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(date, yesterday)) return `昨天 ${clock}`;
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${clock}`;
  }
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`;
}

export function sourceProjectLabel(source: SourceOut, projects: Project[]): string {
  if (source.project_id === null) return "未归属";
  return projects.find((project) => project.id === source.project_id)?.name ?? "未归属";
}

/** 失败文案原样展示服务端 `failure_reason`，不自造替代文案。 */
export function failureLine(source: SourceOut): string | null {
  if (source.status !== FAILED) return null;
  return source.failure_reason;
}

/** 列表行只能对「处理失败」与「等待处理但未启动」提供重试。 */
export function needsProcessingRetry(source: SourceOut): boolean {
  return source.status === FAILED || isProcessingNotStarted(source);
}

export function retryLabel(source: SourceOut): string {
  return isProcessingNotStarted(source) ? "重试处理" : "重试";
}

export type BlockedNotice = { title: string; detail: string; hint?: string };

/** 改归属打开前的预判；服务端 409 仍作为兜底（列表数据可能已过期）。 */
export function moveBlockedReason(source: SourceOut): BlockedNotice | null {
  if (source.project_locked) {
    return {
      title: "不能修改归属",
      detail: "该来源已被正式知识引用，如需移动，请先到桌面工作台处理关联的正式知识。",
    };
  }
  if (source.status === PROCESSING) {
    return {
      title: "不能修改归属",
      detail: "来源正在处理中，等处理结束后再修改归属。",
    };
  }
  return null;
}

/** 删除的三类阻止：前两类由服务端 409 拒绝，第三类（有待确认候选）放行但需二次确认。 */
export function deleteBlockedReason(source: SourceOut): BlockedNotice | null {
  if (source.project_locked) {
    return {
      title: "不能删除",
      detail: "该来源已被正式知识引用，不能删除；请先处理关联 Entry",
      hint: "请先在桌面工作台处理关联的正式知识。",
    };
  }
  if (source.status === PROCESSING) {
    return {
      title: "不能删除",
      detail: "来源正在处理中，不能删除",
      hint: "等处理结束后再删除。",
    };
  }
  return null;
}

export function deleteConfirmCopy(source: SourceOut): { title: string; detail: string } {
  const title = `删除「${source.title}」？`;
  if (source.pending_candidate_count > 0) {
    return {
      title,
      detail: `这条来源有 ${source.pending_candidate_count} 条待确认候选，删除将一并移除这些候选。确认删除？`,
    };
  }
  return { title, detail: "删除后这条来源的原始材料与已经生成的候选都会移除，无法恢复。" };
}

export type DeleteNotice = {
  title: string;
  detail: string;
  hint: string | null;
  /** 是否给「重试删除」入口：只有本次请求失败（非业务阻断）才值得重试。 */
  retryable: boolean;
};

/** 服务端 409 与本地预判同类，都是「这条来源现在不能删」的业务阻断。 */
export function isDeleteConflict(error: unknown): boolean {
  return (error as { status?: number } | null)?.status === 409;
}

/**
 * 删除弹层当前要展示的提示。
 *
 * - 本地预判（已被正式知识引用 / 处理中）：只读阻断，不给重试。
 * - 服务端 409：同样是业务阻断，用服务端原文但不给重试，避免诱导用户反复点。
 * - 其他失败（网络 / 5xx）：标题「删除失败」并保留重试入口，否则用户会被困在弹层里。
 */
export function deleteFailureNotice(
  blocked: BlockedNotice | null,
  failure: { message: string; conflict: boolean } | null,
): DeleteNotice | null {
  if (blocked) {
    return { title: blocked.title, detail: blocked.detail, hint: blocked.hint ?? null, retryable: false };
  }
  if (!failure) return null;
  if (failure.conflict) {
    return { title: "不能删除", detail: failure.message, hint: null, retryable: false };
  }
  return { title: "删除失败", detail: failure.message, hint: null, retryable: true };
}

/** 候选的目录建议文案：只展示能读懂的内容，不暴露无名称的节点编号以外的内部字段。 */
export function candidateDirectoryLine(candidate: CandidateOut): string {
  if (candidate.new_node_suggestion) return `建议新增节点：${candidate.new_node_suggestion.name}`;
  if (candidate.recommended_node_id !== null) {
    return `建议归入已有目录节点（编号 ${candidate.recommended_node_id}）`;
  }
  return "这次没有给出目录建议";
}
