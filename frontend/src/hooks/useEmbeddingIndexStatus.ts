import { useQuery } from '@tanstack/react-query'

import { fetchEmbeddingIndexStatus } from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

/** 查询当前 Workspace（或指定项目）的语义索引状态。 */
export function useEmbeddingIndexStatus(projectId?: number) {
  return useQuery({
    queryKey: queryKeys.embeddingIndexStatus(projectId),
    queryFn: () => fetchEmbeddingIndexStatus(projectId),
  })
}
