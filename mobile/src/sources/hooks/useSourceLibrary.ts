/**
 * 来源库状态：最近收集列表（前台轮询）、详情与候选查询、重试处理、改归属与删除。
 *
 * 列表与详情共用同一份查询缓存，改归属或删除后统一失效，避免界面出现两份不一致的数据。
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { useAppStateActive } from "@/src/knowledge-agent/hooks/useAppState";
import {
  deleteSource as deleteSourceRequest,
  getSource,
  listSourceCandidates,
  listSources,
  sourceErrorMessage,
  triggerSourceProcessing,
  updateSourceProject,
} from "@/src/sources/api";
import { sourceKeys } from "@/src/sources/queryKeys";
import { shouldPollSources } from "@/src/sources/state";
import type { SourceFilter, SourceOut } from "@/src/sources/types";

export function useSourceLibrary(token: string | null) {
  const appActive = useAppStateActive();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<SourceFilter>("all");
  const [detailSourceId, setDetailSourceId] = useState<number | null>(null);
  // 只表示用户主动的下拉 / 按钮刷新：轮询触发的重取不应该一直转圈
  const [refreshing, setRefreshing] = useState(false);
  const [movingIds, setMovingIds] = useState<number[]>([]);

  const listQuery = useQuery({
    queryKey: sourceKeys.list(filter),
    queryFn: () => listSources(token as string, filter),
    enabled: Boolean(token) && appActive,
    // 仅前台且存在等待处理 / 处理中的条目时轮询，全部结束即停止
    refetchInterval: (query) => shouldPollSources(query.state.data, appActive),
  });

  const detailQuery = useQuery({
    queryKey: sourceKeys.detail(detailSourceId as number),
    queryFn: () => getSource(token as string, detailSourceId as number),
    enabled: Boolean(token) && appActive && detailSourceId !== null,
    refetchInterval: (query) =>
      shouldPollSources(query.state.data ? [query.state.data] : undefined, appActive),
  });

  const candidatesQuery = useQuery({
    queryKey: sourceKeys.candidates(detailSourceId as number),
    queryFn: () => listSourceCandidates(token as string, detailSourceId as number),
    enabled: Boolean(token) && detailSourceId !== null,
  });

  const refetchList = useCallback(async () => {
    setRefreshing(true);
    try {
      await listQuery.refetch();
    } finally {
      setRefreshing(false);
    }
  }, [listQuery]);

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: sourceKeys.all }),
    [queryClient],
  );

  const retryProcessing = useCallback(
    async (sourceId: number) => {
      if (!token) return;
      // 409（正在处理或已完成）由该函数视为正常，不算失败
      await triggerSourceProcessing(token, sourceId);
      await invalidate();
    },
    [invalidate, token],
  );

  const moveSource = useCallback(
    async (sourceId: number, projectId: number | null) => {
      if (!token) return;
      setMovingIds((previous) =>
        previous.includes(sourceId) ? previous : [...previous, sourceId],
      );
      try {
        await updateSourceProject(token, sourceId, projectId);
        await invalidate();
      } finally {
        setMovingIds((previous) => previous.filter((id) => id !== sourceId));
      }
    },
    [invalidate, token],
  );

  const removeSource = useCallback(
    async (sourceId: number) => {
      if (!token) return;
      await deleteSourceRequest(token, sourceId);
      setDetailSourceId(null);
      await invalidate();
    },
    [invalidate, token],
  );

  const sources: SourceOut[] = listQuery.data ?? [];

  return {
    appActive,
    filter,
    setFilter,
    sources,
    listPending: listQuery.isPending,
    listError: listQuery.isError ? sourceErrorMessage(listQuery.error) : null,
    refreshing,
    refetchList: () => void refetchList(),
    detailSourceId,
    openSource: (sourceId: number) => setDetailSourceId(sourceId),
    closeSource: () => setDetailSourceId(null),
    detail: detailQuery.data ?? null,
    detailPending: detailQuery.isPending,
    detailError: detailQuery.isError ? sourceErrorMessage(detailQuery.error) : null,
    candidates: candidatesQuery.data ?? [],
    candidatesError: candidatesQuery.isError
      ? sourceErrorMessage(candidatesQuery.error)
      : null,
    retryDetail: () => void detailQuery.refetch(),
    /** 采集提交结束后重新取数：新来源必须立刻出现在「最近收集」里。 */
    invalidateSources: () => void invalidate(),
    movingIds,
    retryProcessing,
    moveSource,
    removeSource,
  };
}
