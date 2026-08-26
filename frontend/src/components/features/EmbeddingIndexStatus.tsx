import { Loader2, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { useEmbeddingIndexStatus } from '@/hooks/useEmbeddingIndexStatus'
import {
  rebuildEmbedding,
  type EmbeddingIndexStatusPayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

function validStatus(data: EmbeddingIndexStatusPayload | undefined): data is EmbeddingIndexStatusPayload {
  return Boolean(data && typeof data.total === 'number')
}

/** 项目首页的语义索引状态行：常态统计 + 失败时重试按钮。 */
export function EmbeddingIndexLine({ projectId }: { projectId: number }) {
  const status = useEmbeddingIndexStatus(projectId)
  const retry = useGroveMutation({
    mutationFn: (targetProjectId: number) =>
      rebuildEmbedding({ mode: 'failed', project_id: targetProjectId }),
    invalidates: [queryKeys.embeddingIndexStatus(projectId)],
    onSuccess: () => toast.success('已重新提交失败项的语义索引'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '重试失败，请稍后再试'),
  })

  const data = status.data
  if (!validStatus(data) || data.total === 0) return null
  const pendingCount = data.pending + data.missing
  const indexing = pendingCount > 0

  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-body-sm text-muted-foreground">
      <span className="inline-flex items-center gap-1.5">
        {indexing ? <Loader2 className="size-3.5 animate-spin" /> : null}
        {indexing ? '语义索引：正在索引…' : `语义索引：已索引 ${data.ready}/${data.total}`}
      </span>
      {indexing ? <span>· 已索引 {data.ready}/{data.total}</span> : null}
      {pendingCount > 0 ? <span>· 待索引 {pendingCount}</span> : null}
      {data.failed > 0 ? (
        <>
          <span className="text-destructive">· 失败 {data.failed}</span>
          <Button
            size="sm"
            variant="outline"
            disabled={retry.isPending}
            onClick={() => retry.mutate(projectId)}
          >
            <RefreshCw />
            重试失败项
          </Button>
        </>
      ) : null}
    </div>
  )
}

/** 搜索页异常提示：有未就绪或失败时显示一行说明，正常时不出现。 */
export function EmbeddingIndexNotice() {
  const status = useEmbeddingIndexStatus()
  const data = status.data
  if (!validStatus(data) || data.total === 0) return null
  const pendingCount = data.pending + data.missing
  if (pendingCount === 0 && data.failed === 0) return null

  const parts: string[] = []
  if (pendingCount > 0) parts.push(`${pendingCount} 条知识仍在建立语义索引`)
  if (data.failed > 0) parts.push(`${data.failed} 条知识语义索引失败`)
  return (
    <div className="mt-1 flex items-center gap-1.5 text-body-sm text-muted-foreground">
      {pendingCount > 0 ? <Loader2 className="size-3.5 animate-spin" /> : null}
      <p>{parts.join('，')}，关键词搜索不受影响。</p>
    </div>
  )
}
