/**
 * 附件图片读取：先用带认证头的下载通道把图片落到缓存目录，再交给 Image 渲染本地文件。
 *
 * 不能依赖 `Image` 自带的请求头：真机验收时附件端点收到的是 401，
 * 说明图片组件的请求头在 Expo Go 下没有真正发出。
 */

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { File, Paths } from "expo-file-system";

import { useAuth } from "@/src/auth";
import { sourceAttachmentUrl } from "@/src/sources/api";
import { sourceKeys } from "@/src/sources/queryKeys";

/** 缓存文件名：同一附件在详情里重复渲染（网格与放大层）时复用已下载的文件。 */
function cacheFileName(sourceId: number, attachmentId: number, fileName?: string | null) {
  const matched = /\.([A-Za-z0-9]{1,5})$/.exec(fileName ?? "");
  const extension = matched ? `.${matched[1].toLowerCase()}` : ".jpg";
  return `grove-source-${sourceId}-${attachmentId}${extension}`;
}

export async function downloadAttachmentImage(options: {
  sourceId: number;
  attachmentId: number;
  token: string;
  fileName?: string | null;
}): Promise<string> {
  const url = sourceAttachmentUrl(options.sourceId, options.attachmentId);
  if (!url) throw new Error("未配置 EXPO_PUBLIC_API_BASE_URL，无法读取图片。");

  const target = new File(
    Paths.cache,
    cacheFileName(options.sourceId, options.attachmentId, options.fileName),
  );
  if (target.exists) return target.uri;

  try {
    const file = await File.downloadFileAsync(url, target, {
      headers: { Authorization: `Bearer ${options.token}` },
      idempotent: true,
    });
    return file.uri;
  } catch (error) {
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
): AttachmentImageState {
  const { token } = useAuth();
  const query = useQuery({
    queryKey: sourceKeys.attachmentImage(sourceId, attachmentId),
    // 附件内容不可变，读到的就是同一张图；已落盘的缓存文件直接用，不重复下载
    staleTime: Infinity,
    // 图片失败要立刻给重试入口，不自动重试掩盖失败
    retry: false,
    enabled: Boolean(token),
    queryFn: () => downloadAttachmentImage({ sourceId, attachmentId, token: token as string, fileName }),
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
