import { useQuery } from '@tanstack/react-query'
import { FileText, Loader2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { fetchSourceCandidates, type CandidatePayload } from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const TYPE_LABELS: Record<CandidatePayload['main_type'], string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

function CandidateItem({ candidate }: { candidate: CandidatePayload }) {
  return (
    <article className="rounded-md border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-body font-[650]">{candidate.title}</h3>
          <p className="mt-0.5 text-caption text-muted-foreground">
            {TYPE_LABELS[candidate.main_type]}
            {candidate.info_nature ? ` · ${candidate.info_nature}` : ''}
          </p>
        </div>
        <Badge className="shrink-0 bg-ai-candidate-soft text-ai-candidate">AI 候选</Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-body-sm leading-6 text-foreground">
        {candidate.content}
      </p>
      {candidate.reason ? (
        <p className="mt-2 text-caption text-muted-foreground">推荐理由：{candidate.reason}</p>
      ) : null}
      {candidate.evidence.length > 0 ? (
        <div className="mt-2 space-y-1 border-t pt-2">
          <p className="text-caption font-medium text-muted-foreground">证据</p>
          {candidate.evidence.map((item, index) => (
            <blockquote key={`${item.attachment_id}-${index}`} className="border-l-2 px-2 text-caption text-muted-foreground">
              附件 {item.attachment_id} · {item.quote}
            </blockquote>
          ))}
        </div>
      ) : null}
      {candidate.risk_flags.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {candidate.risk_flags.map((flag) => (
            <Badge key={flag} variant="outline" className="bg-error-soft text-destructive">
              {flag}
            </Badge>
          ))}
        </div>
      ) : null}
    </article>
  )
}

/** Source 候选只读预览。 */
export function SourceCandidatesDialog({
  sourceId,
  open,
  onOpenChange,
}: {
  sourceId: number | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const candidates = useQuery({
    queryKey: queryKeys.sourceCandidates(sourceId ?? 0),
    queryFn: () => fetchSourceCandidates(sourceId as number),
    enabled: open && sourceId !== null,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>AI 候选</DialogTitle>
          <DialogDescription>
            AI 从这条来源中提取的候选，尚未确认，不会写入正式知识。
          </DialogDescription>
        </DialogHeader>

        {candidates.isLoading ? (
          <div className="flex min-h-40 items-center justify-center text-body-sm text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            加载候选…
          </div>
        ) : candidates.isError ? (
          <div className="min-h-40 rounded-md bg-error-soft px-3 py-3 text-body-sm text-destructive">
            候选加载失败，请重试。
            <Button
              className="mt-3"
              variant="outline"
              size="sm"
              onClick={() => candidates.refetch()}
            >
              重试
            </Button>
          </div>
        ) : (candidates.data?.length ?? 0) === 0 ? (
          <div className="flex min-h-40 items-center justify-center text-body-sm text-muted-foreground">
            <FileText className="mr-2 size-4" />
            还没有候选
          </div>
        ) : (
          <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
            {candidates.data?.map((candidate) => (
              <CandidateItem key={candidate.id} candidate={candidate} />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
