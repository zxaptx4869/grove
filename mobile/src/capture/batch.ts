/** 采集批次与提交单元的纯逻辑：键派生、标题、进度与汇总文案。 */

export type CaptureKind = "camera" | "album-separate" | "album-merged" | "text";

export type UploadFile = { uri: string; name: string; type: string };

export type CaptureSubmitUnit = {
  /** 幂等键，形如 `{batchId}:{序号}`，序号从 1 开始 */
  key: string;
  /** 图片提交单元显式传标题；文本不传，由后端取正文首行 */
  title?: string;
  files: UploadFile[];
  text?: string;
};

export type CaptureResultStatus = "pending" | "uploading" | "saved" | "failed";

export type CaptureResult = {
  key: string;
  status: CaptureResultStatus;
  sourceId?: number;
  error?: string;
  /** 上传失败时的 HTTP 状态码，用于区分服务端业务拒绝与网络类失败 */
  httpStatus?: number;
  /** 已保存但处理未启动的提示，来源本身仍然有效 */
  processError?: string;
};

export type CaptureSummary = {
  total: number;
  saved: number;
  failed: number;
  pending: number;
  /** 已保存但处理未启动的条目数 */
  processError: number;
};

export const MAX_CAPTURE_KEY_LENGTH = 128;
export const MAX_SELECTION = 5;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** 第 index 个提交单元的幂等键；批次内序号从 1 开始。 */
export function buildCaptureKey(batchId: string, index: number): string {
  if (!Number.isInteger(index) || index < 1) throw new Error("采集序号必须从 1 开始");
  const key = `${batchId}:${index}`;
  if (key.length > MAX_CAPTURE_KEY_LENGTH) throw new Error("采集键超过 128 个字符");
  return key;
}

/** 图片标题：原文件名不适合进列表，用采集时间生成可读标题。 */
export function formatImageTitle(
  now: Date,
  options: { index?: number; total: number; merged: boolean },
): string {
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
  if (options.merged) return `图片 ${stamp} · ${options.total} 张`;
  if (options.total > 1 && options.index) return `图片 ${stamp} · ${options.index}/${options.total}`;
  return `图片 ${stamp}`;
}

/** 按采集形态派生提交单元：「每张一条」N 个单文件单元，合并与文字各 1 个。 */
export function createCaptureSubmitUnits(input: {
  batchId: string;
  kind: CaptureKind;
  files?: UploadFile[];
  text?: string;
  now?: Date;
}): CaptureSubmitUnit[] {
  const now = input.now ?? new Date();
  if (input.kind === "text") {
    const text = (input.text ?? "").trim();
    if (!text) throw new Error("请先输入要收集的文字");
    return [{ key: buildCaptureKey(input.batchId, 1), files: [], text }];
  }
  const files = input.files ?? [];
  if (files.length === 0) throw new Error("请先选择图片");
  if (files.length > MAX_SELECTION) throw new Error(`一次最多上传 ${MAX_SELECTION} 张图片`);
  if (input.kind === "album-merged") {
    return [
      {
        key: buildCaptureKey(input.batchId, 1),
        files,
        title: formatImageTitle(now, { total: files.length, merged: true }),
      },
    ];
  }
  return files.map((file, position) => ({
    key: buildCaptureKey(input.batchId, position + 1),
    files: [file],
    title: formatImageTitle(now, {
      index: position + 1,
      total: files.length,
      merged: false,
    }),
  }));
}

export function createCaptureResults(units: CaptureSubmitUnit[]): CaptureResult[] {
  return units.map((unit) => ({ key: unit.key, status: "pending" as const }));
}

export function summarizeCapture(results: CaptureResult[]): CaptureSummary {
  const saved = results.filter((item) => item.status === "saved").length;
  const failed = results.filter((item) => item.status === "failed").length;
  return {
    total: results.length,
    saved,
    failed,
    pending: results.length - saved - failed,
    processError: results.filter((item) => item.processError).length,
  };
}

/** 汇总文案：全部成功为「已提交 N 条」，否则按「已提交 M 条，N−M 条未成功」。 */
export function summaryText(summary: CaptureSummary): string {
  if (summary.failed === 0) return `已提交 ${summary.saved} 条`;
  return `已提交 ${summary.saved} 条，${summary.failed} 条未成功`;
}

/** 提交全部成功后回入口页的轻提示；有处理未启动的条目时带上数量。 */
export function successToastText(summary: CaptureSummary): string {
  if (summary.processError > 0) {
    return `已提交 ${summary.saved} 条，其中 ${summary.processError} 条处理未启动`;
  }
  return `已提交 ${summary.saved} 条，正在后台处理`;
}

/** 本次是否「全是服务端业务拒绝（4xx）且没有一条成功」：这类失败回采集页改后重提。 */
export function isBusinessRejection(results: CaptureResult[]): boolean {
  const failed = results.filter((item) => item.status === "failed");
  return (
    failed.length > 0 &&
    failed.length === results.length &&
    failed.every((item) => (item.httpStatus ?? 0) >= 400 && (item.httpStatus ?? 0) < 500)
  );
}

/** 回到采集页时展示的服务端原文：去重后按行拼接，不改写文案。 */
export function rejectionText(results: CaptureResult[]): string {
  const messages = results
    .map((item) => item.error)
    .filter((message): message is string => Boolean(message));
  return [...new Set(messages)].join("\n");
}

/** 进度文案：不做百分比。 */
export function progressText(kind: CaptureKind, options: { total: number; current: number }): string {
  if (kind === "text") return "正在提交文字来源…";
  if (kind === "album-merged") return `正在上传 ${options.total} 张图片…`;
  if (options.total > 1) return `正在上传 ${options.total} 张中的第 ${options.current} 张…`;
  return "正在上传 1 张图片…";
}
