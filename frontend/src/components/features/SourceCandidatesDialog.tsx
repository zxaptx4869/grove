import { useEffect, useMemo, useRef, useState } from 'react'
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
import {
  fetchSource,
  fetchSourceCandidates,
  sourceImageUrl,
  type CandidateDecisionStatus,
  type CandidatePayload,
} from '@/lib/api'
import { highlightEvidence } from '@/lib/evidenceHighlight'
import { queryKeys } from '@/lib/queryKeys'

const TYPE_LABELS: Record<CandidatePayload['main_type'], string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

const DECISION_LABELS: Record<CandidateDecisionStatus, string> = {
  pending: '待确认',
  confirmed: '已确认',
  rejected: '已拒绝',
}

const DECISION_CLASS: Record<CandidateDecisionStatus, string> = {
  pending: 'bg-ai-candidate-soft text-ai-candidate',
  confirmed: 'bg-confirmed-soft text-confirmed',
  rejected: 'bg-muted text-muted-foreground',
}

function CandidateItem({
  candidate,
  selected,
  onSelect,
}: {
  candidate: CandidatePayload
  selected: boolean
  onSelect: () => void
}) {
  return (
    <article
      className={`cursor-pointer rounded-md border p-3 transition-colors ${selected ? 'border-brand bg-brand-soft/30' : 'hover:bg-muted/40'}`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-body font-[650]">{candidate.title}</h3>
          <p className="mt-0.5 text-caption text-muted-foreground">
            {TYPE_LABELS[candidate.main_type]}
            {candidate.info_nature ? ` · ${candidate.info_nature}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Badge className={`shrink-0 ${DECISION_CLASS[candidate.status]}`}>
            {DECISION_LABELS[candidate.status]}
          </Badge>
          <Badge className="shrink-0 bg-ai-candidate-soft text-ai-candidate">AI 候选</Badge>
        </div>
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
  const source = useQuery({
    queryKey: [...queryKeys.sources, 'detail', sourceId ?? 0],
    queryFn: () => fetchSource(sourceId as number),
    enabled: open && sourceId !== null,
  })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const evidenceAreaRef = useRef<HTMLElement>(null)

  // 未显式选择时默认选中第一条候选（渲染期派生，避免 effect 内 setState）
  const effectiveSelectedId = selectedId ?? candidates.data?.[0]?.id ?? null
  const selectedCandidate = useMemo(
    () => candidates.data?.find((candidate) => candidate.id === effectiveSelectedId) ?? null,
    [candidates.data, effectiveSelectedId],
  )

  // 切换候选后，原文区自动滚动定位到第一个高亮片段（无命中不滚动）
  useEffect(() => {
    const mark = evidenceAreaRef.current?.querySelector<HTMLElement>('[data-evidence-highlight]')
    if (mark && typeof mark.scrollIntoView === 'function') {
      mark.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [effectiveSelectedId])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl">
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
          <div className="grid min-h-0 grid-cols-2 gap-4">
            <section ref={evidenceAreaRef} className="min-h-0 max-h-[65vh] overflow-y-auto rounded-md border p-4">
              <h3 className="mb-2 text-body font-[650]">原始材料与证据</h3>
              {source.isLoading ? (
                <div className="h-40 animate-pulse rounded-md bg-muted/40" />
              ) : ((source.data?.attachments ?? []).length) === 0 ? (
                <p className="py-8 text-center text-body-sm text-muted-foreground">没有附件</p>
              ) : (
                source.data?.attachments.map((attachment) =>
                  attachment.kind === 'image' ? (
                    <figure key={attachment.id} className="mb-3">
                      {attachment.ocr_text ? (
                        <div className="mb-2 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-body-sm">
                          {highlightEvidence(
                            attachment.ocr_text,
                            selectedCandidate?.evidence.find(
                              (item) => item.attachment_id === attachment.id,
                            )?.quote,
                          )}
                        </div>
                      ) : null}
                      <img
                        src={sourceImageUrl(source.data.id, attachment.id)}
                        alt={attachment.file_name ?? '来源图片'}
                        className="w-full rounded-md border object-contain"
                        style={{ maxHeight: '40vh' }}
                      />
                    </figure>
                  ) : (
                    <div
                      key={attachment.id}
                      className="mb-3 whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-body-sm"
                    >
                      {highlightEvidence(
                        attachment.text_content ?? '',
                        selectedCandidate?.evidence.find(
                          (item) => item.attachment_id === attachment.id,
                        )?.quote,
                      )}
                    </div>
                  ),
                )
              )}
            </section>
            <div className="max-h-[65vh] space-y-3 overflow-y-auto pr-1">
              {candidates.data?.map((candidate) => (
                <CandidateItem
                  key={candidate.id}
                  candidate={candidate}
                  selected={candidate.id === effectiveSelectedId}
                  onSelect={() => setSelectedId(candidate.id)}
                />
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
