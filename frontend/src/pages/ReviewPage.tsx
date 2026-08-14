import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Check,
  ChevronLeft,
  ChevronRight,
  List,
  Pencil,
  X,
} from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  decideCandidate,
  fetchReviewSources,
  fetchSource,
  fetchSourceCandidates,
  sourceImageUrl,
  updateCandidate,
  type CandidatePayload,
  type CandidateUpdatePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const STATUS_LABELS: Record<CandidatePayload['status'], string> = {
  pending: '待采纳',
  confirmed: '已采纳',
  rejected: '已拒绝',
}

function statusClass(status: CandidatePayload['status']) {
  if (status === 'confirmed') return 'bg-confirmed-soft text-confirmed'
  if (status === 'rejected') return 'bg-error-soft text-destructive'
  return 'bg-ai-candidate-soft text-ai-candidate'
}

function highlightQuote(text: string, quote?: string) {
  if (!quote) return text
  const index = text.indexOf(quote)
  if (index < 0) return text
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-amber-100 text-foreground">{quote}</mark>
      {text.slice(index + quote.length)}
    </>
  )
}

function CandidateEditor({
  candidate,
  onAdopt,
  onReject,
  onSkip,
  isPending,
}: {
  candidate: CandidatePayload
  onAdopt: (payload: {
    content: string
    main_type: CandidatePayload['main_type']
    info_nature: string | null
  }) => void
  onReject: () => void
  onSkip: () => void
  isPending: boolean
}) {
  const [content, setContent] = useState(candidate.content)
  const [mainType, setMainType] = useState<CandidatePayload['main_type']>(candidate.main_type)
  const [infoNature, setInfoNature] = useState(candidate.info_nature ?? '')

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex-1 space-y-4">
        <div>
          <span className="badge-ai">
            <Badge className="bg-ai-candidate-soft text-ai-candidate">推荐候选</Badge>
          </span>
          <h3 className="mt-2 text-[16px] font-[650] leading-6">{candidate.title}</h3>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="candidate-content" className="text-body-sm font-medium">
            内容
          </label>
          <Textarea
            id="candidate-content"
            rows={5}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label htmlFor="candidate-type" className="text-body-sm font-medium">
              主类型
            </label>
            <select
              id="candidate-type"
              className="h-9 w-full rounded-md border px-2 text-body-sm"
              value={mainType}
              onChange={(event) => setMainType(event.target.value as CandidatePayload['main_type'])}
            >
              <option value="knowledge">知识</option>
              <option value="method">方法</option>
              <option value="parameter">参数</option>
              <option value="reminder">提醒</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="candidate-nature" className="text-body-sm font-medium">
              信息性质
            </label>
            <Input
              id="candidate-nature"
              value={infoNature}
              onChange={(event) => setInfoNature(event.target.value)}
            />
          </div>
        </div>
        {candidate.reason ? (
          <p className="text-caption text-muted-foreground">
            推荐理由与风险：{candidate.reason}
          </p>
        ) : null}
      </div>

      <div className="mt-auto flex justify-end gap-2 border-t pt-4">
        <Button size="sm" variant="outline" disabled={isPending} onClick={onReject}>
          <X />
          拒绝
        </Button>
        <Button size="sm" variant="ghost" disabled={isPending} onClick={onSkip}>
          跳过
        </Button>
        <Button
          size="sm"
          disabled={isPending}
          onClick={() =>
            onAdopt({
              content: content.trim(),
              main_type: mainType,
              info_nature: infoNature.trim() || null,
            })
          }
        >
          <Check />
          采纳
        </Button>
      </div>
    </div>
  )
}

/** 项目内确认台。 */
export function ReviewPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [queueOpen, setQueueOpen] = useState(false)

  const reviewSources = useQuery({
    queryKey: queryKeys.reviewSources(id),
    queryFn: () => fetchReviewSources(id),
    enabled: Number.isFinite(id),
  })
  const activeSourceId = selectedSourceId ?? reviewSources.data?.[0]?.id ?? null
  const source = useQuery({
    queryKey: [...queryKeys.sources, 'detail', activeSourceId ?? 0],
    queryFn: () => fetchSource(activeSourceId as number),
    enabled: activeSourceId !== null,
  })
  const candidates = useQuery({
    queryKey: queryKeys.sourceCandidates(activeSourceId ?? 0),
    queryFn: () => fetchSourceCandidates(activeSourceId as number),
    enabled: activeSourceId !== null,
  })

  const pendingCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.status === 'pending'),
    [candidates.data],
  )
  const currentCandidate = pendingCandidates[currentIndex] ?? null
  const singleImage =
    (source.data?.attachments.filter((attachment) => attachment.kind === 'image').length ?? 0) ===
    1

  const adopt = useGroveMutation({
    mutationFn: async ({
      candidate,
      payload,
    }: {
      candidate: CandidatePayload
      payload: { content: string; main_type: CandidatePayload['main_type']; info_nature: string | null }
    }) => {
      await updateCandidate(candidate.id, {
        content: payload.content,
        main_type: payload.main_type,
        info_nature: payload.info_nature as CandidateUpdatePayload['info_nature'],
      })
      return decideCandidate(candidate.id, 'confirmed')
    },
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      setCurrentIndex((value) => Math.max(0, value - 1))
      toast.success('候选已采纳')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '采纳失败'),
  })
  const reject = useGroveMutation({
    mutationFn: (candidate: CandidatePayload) => decideCandidate(candidate.id, 'rejected'),
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      setCurrentIndex((value) => Math.max(0, value - 1))
      toast.success('候选已拒绝')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '操作失败'),
  })
  const reopen = useGroveMutation({
    mutationFn: (candidate: CandidatePayload) => decideCandidate(candidate.id, 'pending'),
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => toast.success('候选已重新打开'),
    onError: (error) => toast.error(error instanceof Error ? error.message : '操作失败'),
  })

  function selectSource(sourceId: number) {
    setSelectedSourceId(sourceId)
    setCurrentIndex(0)
    setQueueOpen(false)
  }

  function moveSource(delta: number) {
    const list = reviewSources.data ?? []
    const index = list.findIndex((item) => item.id === activeSourceId)
    const next = list[index + delta]
    if (next) selectSource(next.id)
    else if (delta < 0) toast('已经是第一条来源')
    else toast('已经是最后一条来源')
  }

  const sourceIndex = (reviewSources.data ?? []).findIndex((item) => item.id === activeSourceId)

  return (
    <section className="flex h-full min-h-0 flex-col">
      <header className="flex min-h-[58px] items-center justify-between gap-4 px-6">
        <div className="flex items-center gap-3">
          <h1 className="text-[22px] font-[650] leading-[30px]">确认台</h1>
          <Badge className="bg-ai-candidate-soft text-ai-candidate">
            {reviewSources.data?.length ?? 0} 条待确认
          </Badge>
        </div>
        <span className="text-body-sm text-muted-foreground">
          逐条决定是否采纳当前项目的候选。
        </span>
      </header>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-[52px] items-center justify-between gap-3 border-y px-6">
          <div>
            <span className="block text-caption text-muted-foreground">当前来源</span>
            <strong className="block truncate text-body">{source.data?.title ?? '未选择'}</strong>
          </div>
          <span className="text-caption text-muted-foreground">
            来源进度 {sourceIndex >= 0 ? sourceIndex + 1 : 0} / {reviewSources.data?.length ?? 0}
          </span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => moveSource(-1)}>
              <ChevronLeft />
              上一来源
            </Button>
            <Button size="sm" variant="outline" onClick={() => moveSource(1)}>
              下一来源
              <ChevronRight />
            </Button>
            <Button size="sm" variant="outline" onClick={() => setQueueOpen(true)}>
              <List />
              待处理来源 {reviewSources.data?.length ?? 0}
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-2">
          <section className="min-h-0 min-w-0 overflow-y-auto border-r p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-[650]">原始材料与证据</h2>
              {source.data?.note ? (
                <span className="text-caption text-muted-foreground">采集说明：{source.data.note}</span>
              ) : null}
            </div>
            {source.isLoading ? (
              <div className="h-64 animate-pulse bg-muted/40" />
            ) : (source.data?.attachments.length ?? 0) === 0 ? (
              <p className="py-10 text-center text-body-sm text-muted-foreground">没有附件</p>
            ) : (
              <div className="flex flex-wrap gap-3">
                {source.data?.attachments.map((attachment) =>
                  attachment.kind === 'image' ? (
                    <figure key={attachment.id} className="min-w-60 flex-1">
                      {attachment.ocr_text ? (
                        <div className="mb-2 max-h-40 overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-body-sm">
                          {highlightQuote(
                            attachment.ocr_text,
                            currentCandidate?.evidence.find(
                              (item) => item.attachment_id === attachment.id,
                            )?.quote,
                          )}
                        </div>
                      ) : null}
                      <img
                        src={sourceImageUrl(source.data.id, attachment.id)}
                        alt={attachment.file_name ?? '来源图片'}
                        className="w-full rounded-md border object-contain"
                        style={{ maxHeight: singleImage ? '70vh' : '45vh' }}
                      />
                    </figure>
                  ) : (
                    <div
                      key={attachment.id}
                      className="w-full whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-body-sm"
                    >
                      {highlightQuote(
                        attachment.text_content ?? '',
                        currentCandidate?.evidence.find(
                          (item) => item.attachment_id === attachment.id,
                        )?.quote,
                      )}
                    </div>
                  ),
                )}
              </div>
            )}
          </section>

          <section className="flex min-h-0 flex-col">
            <div className="flex min-h-[50px] items-center justify-between border-b px-5">
              <h2 className="text-[16px] font-[650]">AI 候选</h2>
              <div className="flex items-center gap-2">
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="上一候选"
                  disabled={pendingCandidates.length === 0}
                  onClick={() => {
                    if (currentIndex === 0) toast('已经是第一条候选')
                    else setCurrentIndex((value) => value - 1)
                  }}
                >
                  <ChevronLeft />
                </Button>
                <span className="text-caption text-muted-foreground">
                  当前候选 {pendingCandidates.length > 0 ? currentIndex + 1 : 0} /{' '}
                  {pendingCandidates.length}
                </span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="下一候选"
                  disabled={pendingCandidates.length === 0}
                  onClick={() => {
                    if (currentIndex >= pendingCandidates.length - 1)
                      toast('已经是最后一条候选')
                    else setCurrentIndex((value) => value + 1)
                  }}
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {candidates.isLoading ? (
                <div className="h-64 animate-pulse bg-muted/40" />
              ) : currentCandidate ? (
                <CandidateEditor
                  key={currentCandidate.id}
                  candidate={currentCandidate}
                  isPending={adopt.isPending || reject.isPending}
                  onAdopt={(payload) => adopt.mutate({ candidate: currentCandidate, payload })}
                  onReject={() => reject.mutate(currentCandidate)}
                  onSkip={() =>
                    setCurrentIndex((value) => Math.min(pendingCandidates.length - 1, value + 1))
                  }
                />
              ) : (
                <div className="flex min-h-64 items-center justify-center text-body-sm text-muted-foreground">
                  没有待采纳候选
                </div>
              )}
            </div>

            {(candidates.data ?? []).some((candidate) => candidate.status !== 'pending') ? (
              <div className="border-t p-4">
                <p className="mb-2 text-caption text-muted-foreground">已决定候选</p>
                <div className="space-y-1.5">
                  {(candidates.data ?? [])
                    .filter((candidate) => candidate.status !== 'pending')
                    .map((candidate) => (
                      <div
                        key={candidate.id}
                        className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-body-sm">{candidate.title}</p>
                          <Badge className={`mt-1 ${statusClass(candidate.status)}`}>
                            {STATUS_LABELS[candidate.status]}
                          </Badge>
                        </div>
                        <Button size="sm" variant="ghost" onClick={() => reopen.mutate(candidate)}>
                          <Pencil />
                          重新打开
                        </Button>
                      </div>
                    ))}
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </div>

      {queueOpen ? (
        <div className="fixed inset-0 z-50 bg-black/40" onClick={() => setQueueOpen(false)}>
          <aside
            className="absolute right-0 top-0 h-full w-[320px] bg-card p-4 shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-body font-[650]">待处理来源</h2>
              <Button size="icon-sm" variant="ghost" aria-label="关闭待处理来源" onClick={() => setQueueOpen(false)}>
                <X />
              </Button>
            </div>
            <div className="space-y-1">
              {reviewSources.data?.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectSource(item.id)}
                  className={`w-full rounded-md px-3 py-2 text-left transition-colors ${activeSourceId === item.id ? 'bg-brand-soft text-brand' : 'hover:bg-muted'}`}
                >
                  <span className="block truncate text-body-sm font-medium">{item.title}</span>
                  <span className="mt-0.5 block text-caption text-muted-foreground">
                    {item.candidate_count} 条候选 · {item.review_status === 'partial_review' ? '部分确认' : '待确认'}
                  </span>
                </button>
              ))}
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  )
}
