/**
 * 来源库 API：列表、详情、候选、改归属与删除。
 *
 * 处理触发复用采集链路已有的 `triggerSourceProcessing`（它把 409 视为正常的重复触发），
 * 避免两处对同一端点的状态码口径不一致。
 */

import { apiBaseUrl, request } from "@/src/api";
import type { CandidateOut, SourceFilter, SourceOut } from "@/src/sources/types";

/** 列表规模：与原型「最近收集」一致，不做分页。 */
export const SOURCE_LIST_LIMIT = 20;

export { triggerSourceProcessing } from "@/src/capture/upload";

export function listSources(
  token: string,
  filter: SourceFilter,
  limit: number = SOURCE_LIST_LIMIT,
): Promise<SourceOut[]> {
  const query = [`limit=${limit}`];
  if (filter === "unassigned") query.push("unassigned=true");
  return request<SourceOut[]>(`/api/sources?${query.join("&")}`, {}, token);
}

export function getSource(token: string, sourceId: number): Promise<SourceOut> {
  return request<SourceOut>(`/api/sources/${sourceId}`, {}, token);
}

export function listSourceCandidates(token: string, sourceId: number): Promise<CandidateOut[]> {
  return request<CandidateOut[]>(`/api/sources/${sourceId}/candidates`, {}, token);
}

export function updateSourceProject(
  token: string,
  sourceId: number,
  projectId: number | null,
): Promise<SourceOut> {
  return request<SourceOut>(
    `/api/sources/${sourceId}`,
    { method: "PATCH", body: JSON.stringify({ project_id: projectId }) },
    token,
  );
}

export function deleteSource(token: string, sourceId: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/sources/${sourceId}`, { method: "DELETE" }, token);
}

/** 图片附件地址：读取时需要携带认证头，由调用方放进 Image 的 headers。 */
export function sourceAttachmentUrl(sourceId: number, attachmentId: number): string | null {
  if (!apiBaseUrl) return null;
  return `${apiBaseUrl}/api/sources/${sourceId}/attachments/${attachmentId}/file`;
}

/** 网络类失败没有服务端文案时使用；有 `detail` 的 4xx 一律原样透传。 */
export const SOURCE_NETWORK_ERROR = "网络连接中断，请检查网络后重试。";

export function sourceErrorMessage(error: unknown): string {
  const status = (error as { status?: number } | null)?.status;
  if (status && error instanceof Error && error.message) return error.message;
  if (error instanceof Error && /EXPO_PUBLIC_API_BASE_URL/.test(error.message)) return error.message;
  return SOURCE_NETWORK_ERROR;
}
