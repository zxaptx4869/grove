/** 采集上传通道：独立 multipart 请求，不复用固定 JSON 头与 12 秒超时的通用请求函数。 */

import { apiBaseUrl, request } from "@/src/api";
import type { CaptureSubmitUnit } from "@/src/capture/batch";

export type UploadedSource = { id: number };

/** 单次上传超时：覆盖压缩失效时 10MB 在弱网上传的最坏情况（约 80 秒）。 */
export const UPLOAD_TIMEOUT_MS = 90_000;

export class CaptureSubmitError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "CaptureSubmitError";
    this.status = status;
  }
}

export type UploadSourceInput = {
  token: string;
  unit: CaptureSubmitUnit;
  note?: string;
  projectId?: number | null;
  timeoutMs?: number;
};

export async function uploadSource(input: UploadSourceInput): Promise<UploadedSource> {
  if (!apiBaseUrl) {
    throw new CaptureSubmitError("未配置 EXPO_PUBLIC_API_BASE_URL，请在 .env 中填写后端地址。");
  }
  const form = new FormData();
  // React Native 用 { uri, name, type } 传文件；不手动设置 Content-Type，交给平台生成 boundary
  input.unit.files.forEach((file) => form.append("files", file as unknown as Blob));
  form.append("capture_key", input.unit.key);
  if (input.unit.text) form.append("text", input.unit.text);
  if (input.unit.title) form.append("title", input.unit.title);
  if (input.note) form.append("note", input.note);
  if (input.projectId != null) form.append("project_id", String(input.projectId));

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), input.timeoutMs ?? UPLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(`${apiBaseUrl}/api/sources`, {
      method: "POST",
      headers: { Authorization: `Bearer ${input.token}` },
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      const detail = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const message =
        typeof detail?.detail === "string" && detail.detail
          ? detail.detail
          : `上传失败（HTTP ${response.status}）`;
      throw new CaptureSubmitError(message, response.status);
    }
    // 201 新建与 200 幂等命中都表示成功，响应体都是同一条来源
    const payload = (await response.json()) as { id: number };
    return { id: payload.id };
  } catch (error) {
    if (error instanceof CaptureSubmitError) throw error;
    if ((error as { name?: string } | null)?.name === "AbortError") {
      throw new CaptureSubmitError("上传超时，材料没有保存到 Grove，请检查网络后重试。");
    }
    throw new CaptureSubmitError("网络连接中断，材料没有保存到 Grove，已填写的内容仍在表单里。");
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 采集后逐条触发处理。
 * 409 表示该来源正在处理或已处理完成，状态本身没有问题（幂等重试命中旧来源时会出现），
 * 因此不算失败、不提示「处理启动失败」。
 */
export async function triggerSourceProcessing(token: string, sourceId: number): Promise<void> {
  try {
    await request<{ id: number }>(`/api/sources/${sourceId}/process`, { method: "POST" }, token);
  } catch (error) {
    if ((error as { status?: number } | null)?.status === 409) return;
    throw error;
  }
}
