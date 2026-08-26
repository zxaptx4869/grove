import { useQuery } from '@tanstack/react-query'

import {
  fetchEmbeddingIndexStatus,
  type EmbeddingIndexStatusPayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

/** 查询当前 Workspace（或指定项目）的语义索引状态。 */
export function useEmbeddingIndexStatus(projectId?: number) {
  return useQuery({
    queryKey: queryKeys.embeddingIndexStatus(projectId),
    queryFn: () => fetchEmbeddingIndexStatus(projectId),
    // 索引进行中每 3 秒自动刷新，完成后停止轮询
    refetchInterval: (query) => {
      const data = query.state.data as EmbeddingIndexStatusPayload | undefined
      if (!data || typeof data.total !== 'number') return false
      return data.pending + data.missing > 0 ? 3000 : false
    },
  })
}
