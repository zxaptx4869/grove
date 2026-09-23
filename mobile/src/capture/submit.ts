/** 采集提交执行器：串行上传，部分失败继续，逐条标记结果。 */

import type { CaptureResult, CaptureSubmitUnit } from "@/src/capture/batch";

export type CaptureSubmitDeps = {
  /** 上传一个提交单元，成功返回来源 id */
  upload: (unit: CaptureSubmitUnit) => Promise<number>;
  triggerProcessing: (sourceId: number) => Promise<void>;
  onUpdate: (key: string, patch: Partial<CaptureResult>) => void;
};

export function toCaptureMessage(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = String((error as { message?: unknown }).message ?? "");
    if (message) return message;
  }
  return "提交未成功，请稍后重试。";
}

/** 依次执行提交单元：单元失败只标记该条，不中断其余条目。 */
export async function submitCaptureUnits(
  units: CaptureSubmitUnit[],
  deps: CaptureSubmitDeps,
): Promise<void> {
  for (const unit of units) {
    deps.onUpdate(unit.key, { status: "uploading", error: undefined, processError: undefined });
    let sourceId: number;
    try {
      sourceId = await deps.upload(unit);
    } catch (error) {
      deps.onUpdate(unit.key, { status: "failed", error: toCaptureMessage(error) });
      continue;
    }
    let processError: string | undefined;
    try {
      await deps.triggerProcessing(sourceId);
    } catch (error) {
      processError = toCaptureMessage(error);
    }
    deps.onUpdate(unit.key, { status: "saved", sourceId, processError });
  }
}
