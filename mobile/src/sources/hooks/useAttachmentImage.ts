/**
 * 附件图片读取：先用带认证头的下载通道把图片落到缓存目录，再交给 Image 渲染本地文件。
 *
 * 不能依赖 `Image` 自带的请求头：真机验收时附件端点收到的是 401，
 * 说明图片组件的请求头在 Expo Go 下没有真正发出。
 */

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Directory, File, Paths } from "expo-file-system";

import { useAuth } from "@/src/auth";
import { sourceAttachmentUrl } from "@/src/sources/api";
import { sourceKeys } from "@/src/sources/queryKeys";
import { ATTACHMENT_CACHE_PREFIX, attachmentCacheFileName } from "@/src/sources/state";

/** 已落盘的缓存文件：尺寸为 0 的（Android 上下载中断留下的半截文件）不算命中。 */
function existingCacheUri(target: File): string | null {
  if (!target.exists) return null;
  try {
    return (target.info().size ?? 0) > 0 ? target.uri : null;
  } catch {
    return null;
  }
}

/**
 * 删掉同一附件的旧缓存：库重置后 (来源 id, 附件 id) 会复用，旧文件必须让位。
 * 同时覆盖不带版本串的旧命名（`grove-source-1-11.jpg`），让它们不再占着缓存目录。
 */
function removeStaleAttachments(sourceId: number, attachmentId: number, keep: string) {
  try {
    const versioned = `${ATTACHMENT_CACHE_PREFIX}${sourceId}-${attachmentId}-`;
    const legacy = `${ATTACHMENT_CACHE_PREFIX}${sourceId}-${attachmentId}.`;
    for (const entry of new Directory(Paths.cache).list()) {
      if (!(entry instanceof File) || entry.name === keep) continue;
      const stale =
        entry.name.startsWith(versioned) || entry.name.startsWith(legacy);
      if (stale) entry.delete();
    }
  } catch (error) {
    console.warn("[sources] 清理附件图片旧缓存失败", { sourceId, attachmentId, error });
  }
}

export async function downloadAttachmentImage(options: {
  sourceId: number;
  attachmentId: number;
  token: string;
  fileName?: string | null;
  cacheVersion?: string | null;
}): Promise<string> {
  const url = sourceAttachmentUrl(options.sourceId, options.attachmentId);
  if (!url) throw new Error("未配置 EXPO_PUBLIC_API_BASE_URL，无法读取图片。");

  const targetName = attachmentCacheFileName(options);
  const target = new File(Paths.cache, targetName);
  const cached = existingCacheUri(target);
  if (cached) return cached;

  removeStaleAttachments(options.sourceId, options.attachmentId, targetName);

  try {
    const file = await File.downloadFileAsync(url, target, {
      headers: { Authorization: `Bearer ${options.token}` },
      idempotent: true,
    });
    return file.uri;
  } catch (error) {
    // Android 上失败可能在目标位置留下半截文件，留着下次会被当成缓存命中
    try {
      if (target.exists) target.delete();
    } catch {
      // 清理失败不影响把真实错误抛给界面
    }
    // 失败必须留现场：图片不显示时要知道是请求失败还是渲染问题
    console.warn("[sources] 读取附件图片失败", { url, sourceId: options.sourceId, error });
    throw error;
  }
}

export type AttachmentImageState = {
  uri: string | null;
  loading: boolean;
  failed: boolean;
  retry: () => void;
};

export function useAttachmentImage(
  sourceId: number,
  attachmentId: number,
  fileName?: string | null,
  cacheVersion?: string | null,
): AttachmentImageState {
  const { token } = useAuth();
  const query = useQuery({
    // 版本串进键：库重置后同号来源换了内容，必须重新下载而不是复用旧查询结果
    queryKey: sourceKeys.attachmentImage(sourceId, attachmentId, cacheVersion),
    // 附件内容不可变，同一版本读到的就是同一张图；已落盘的缓存文件直接用，不重复下载
    staleTime: Infinity,
    // 图片失败要立刻给重试入口，不自动重试掩盖失败
    retry: false,
    enabled: Boolean(token),
    queryFn: () =>
      downloadAttachmentImage({
        sourceId,
        attachmentId,
        token: token as string,
        fileName,
        cacheVersion,
      }),
  });

  const retry = useCallback(() => {
    void query.refetch();
  }, [query]);

  return {
    uri: query.data ?? null,
    loading: Boolean(token) && query.isPending,
    failed: query.isError,
    retry,
  };
}
