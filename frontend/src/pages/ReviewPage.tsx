import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronLeft, ChevronRight, FileText, Pencil, X } from 'lucide-react'
import { useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  batchDecideCandidates,
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

const TYPE_LABELS: Record<CandidatePayload['main_type'], string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

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

function CandidateCard({
  candidate,
  selected,
  onSelect,
  onEdit,
  onDecide,
}: {
  candidate: CandidatePayload
  selected: boolean
  onSelect: (checked: boolean) => void
  onEdit: () => void
  onDecide: (status: 'confirmed' | 'rejected' | 'pending') => void
}) {
  return (
    <article className={`rounded-md border p-3 ${selected ? 'border-brand bg-brand-soft/40' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              aria-label={`选择 ${candidate.title}`}
              checked={selected}
              disabled={candidate.status !== 'pending'}
              onChange={(event) => onSelect(event.target.checked)}
            />
            <h3 className="truncate text-body font-[650]">{candidate.title}</h3>
          </div>
          <p className="mt-1 text-caption text-muted-foreground">
            {TYPE_LABELS[candidate.main_type]}
            {candidate.info_nature ? ` · ${candidate.info_nature}` : ''}
          </p>
        </div>
        <Badge className={`shrink-0 ${statusClass(candidate.status)}`}>
          {STATUS_LABELS[candidate.status]}
        </Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-body-sm leading-6">{candidate.content}</p>
      {candidate.reason ? (
        <p className="mt-2 text-caption text-muted-foreground">推荐理由：{candidate.reason}</p>
      ) : null}
      {candidate.evidence.length > 0 ? (
        <div className="mt-2 space-y-1 border-t pt-2">
          <p className="text-caption font-medium text-muted-foreground">证据</p>
          {candidate.evidence.map((item, index) => (
            <blockquote
              key={`${item.attachment_id}-${index}`}
              className="border-l-2 px-2 text-caption text-muted-foreground"
            >
              附件 {item.attachment_id} · {item.quote}
            </blockquote>
          ))}
        </div>
      ) : null}
      {candidate.status === 'pending' ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil />
            编辑
          </Button>
          <Button size="sm" variant="outline" onClick={() => onDecide('rejected')}>
            <X />
            拒绝
          </Button>
          <Button size="sm" onClick={() => onDecide('confirmed')}>
            <Check />
            采纳
          </Button>
        </div>
      ) : (
        <div className="mt-3">
          <Button size="sm" variant="ghost" onClick={() => onDecide('pending')}>
            重新打开
          </Button>
        </div>
      )}
    </article>
  )
}

/** 项目内确认台。 */
export function ReviewPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [editCandidate, setEditCandidate] = useState<CandidatePayload | null>(null)
  const [editValues, setEditValues] = useState({
    title: '',
    content: '',
    main_type: 'knowledge' as CandidatePayload['main_type'],
    info_nature: '',
    applicable_condition: '',
    note: '',
  })

  const reviewSources = useQuery({
    queryKey: queryKeys.reviewSources(id),
    queryFn: () => fetchReviewSources(id),
    enabled: Number.isFinite(id),
  })
  const source = useQuery({
    queryKey: [...queryKeys.sources, 'detail', selectedSourceId ?? 0],
    queryFn: () => fetchSource(selectedSourceId as number),
    enabled: selectedSourceId !== null,
  })
  const candidates = useQuery({
    queryKey: queryKeys.sourceCandidates(selectedSourceId ?? 0),
    queryFn: () => fetchSourceCandidates(selectedSourceId as number),
    enabled: selectedSourceId !== null,
  })

  const pendingCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.status === 'pending'),
    [candidates.data],
  )

  const decide = useGroveMutation({
    mutationFn: ({
      candidateId,
      status,
    }: {
      candidateId: number
      status: 'confirmed' | 'rejected' | 'pending'
    }) => decideCandidate(candidateId, status),
    invalidates: [
      queryKeys.sourceCandidates(selectedSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => toast.success('候选已更新'),
    onError: (error) => toast.error(error instanceof Error ? error.message : '操作失败'),
  })
  const batchDecide = useGroveMutation({
    mutationFn: (status: 'confirmed' | 'rejected') =>
      batchDecideCandidates(selectedSourceId as number, Array.from(selectedIds), status),
    invalidates: [
      queryKeys.sourceCandidates(selectedSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      setSelectedIds(new Set())
      toast.success('批量操作已完成')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '批量操作失败'),
  })
  const saveEdit = useGroveMutation({
    mutationFn: () =>
      updateCandidate(editCandidate!.id, {
        title: editValues.title.trim() || null,
        content: editValues.content.trim() || null,
        main_type: editValues.main_type,
        info_nature: (editValues.info_nature.trim() || null) as CandidateUpdatePayload['info_nature'],
        applicable_condition: editValues.applicable_condition.trim() || null,
        note: editValues.note.trim() || null,
      }),
    invalidates: [queryKeys.sourceCandidates(editCandidate?.source_id ?? 0)],
    onSuccess: () => {
      setEditCandidate(null)
      toast.success('候选已更新')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '保存失败'),
  })

  function openEdit(candidate: CandidatePayload) {
    setEditCandidate(candidate)
    setEditValues({
      title: candidate.title,
      content: candidate.content,
      main_type: candidate.main_type,
      info_nature: candidate.info_nature ?? '',
      applicable_condition: candidate.applicable_condition ?? '',
      note: candidate.note ?? '',
    })
  }

  function selectSource(sourceId: number) {
    setSelectedSourceId(sourceId)
    setCurrentIndex(0)
    setSelectedIds(new Set())
  }

  return (
    <section className="w-full px-6 pb-[30px] pt-[22px]">
      <header className="mb-5">
        <div className="flex items-center gap-2">
          <h1 className="text-[22px] font-[650] leading-[30px]">确认台</h1>
          <Badge className="bg-ai-candidate-soft text-ai-candidate">
            {reviewSources.data?.length ?? 0} 条待审来源
          </Badge>
        </div>
        <p className="mt-0.5 text-body text-muted-foreground">
          逐条决定是否采纳当前项目的候选。采纳后的候选不会写入正式知识，后续再形成 Entry。
        </p>
      </header>

      <div className="grid grid-cols-[260px_minmax(0,1fr)] items-start gap-6">
        <aside className="min-w-0 rounded-md border p-3">
          <h2 className="mb-2 text-body font-[650]">待审来源</h2>
          {reviewSources.isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((item) => (
                <div key={item} className="h-10 animate-pulse bg-muted/50" />
              ))}
            </div>
          ) : (reviewSources.data?.length ?? 0) === 0 ? (
            <p className="py-6 text-center text-caption text-muted-foreground">没有待审来源</p>
          ) : (
            <div className="space-y-1">
              {reviewSources.data?.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectSource(item.id)}
                  className={`w-full rounded-md px-2 py-2 text-left transition-colors ${selectedSourceId === item.id ? 'bg-brand-soft text-brand' : 'hover:bg-muted'}`}
                >
                  <span className="block truncate text-body-sm font-medium">{item.title}</span>
                  <span className="mt-0.5 block text-caption text-muted-foreground">
                    {item.candidate_count} 条候选 · {item.review_status === 'partial_review' ? '部分确认' : '待确认'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </aside>

        <div className="min-w-0">
          {selectedSourceId === null ? (
            <div className="flex min-h-[420px] items-center justify-center rounded-md border text-body-sm text-muted-foreground">
              选择左侧来源开始审阅
            </div>
          ) : (
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(320px,.9fr)] gap-5">
              <div className="min-w-0 rounded-md border p-4">
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
                  <div className="space-y-3">
                    {source.data?.attachments.map((attachment) =>
                      attachment.kind === 'image' ? (
                        <img
                          key={attachment.id}
                          src={sourceImageUrl(source.data.id, attachment.id)}
                          alt={attachment.file_name ?? '来源图片'}
                          className="max-h-80 w-full rounded-md border object-contain"
                        />
                      ) : (
                        <div key={attachment.id} className="whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-body-sm">
                          {attachment.text_content}
                        </div>
                      ),
                    )}
                  </div>
                )}
              </div>

              <div className="min-w-0">
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-[16px] font-[650]">AI 候选</h2>
                  <div className="flex items-center gap-2">
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="上一候选"
                      disabled={pendingCandidates.length === 0}
                      onClick={() => setCurrentIndex((value) => Math.max(0, value - 1))}
                    >
                      <ChevronLeft />
                    </Button>
                    <span className="text-caption text-muted-foreground">
                      {pendingCandidates.length > 0 ? currentIndex + 1 : 0} / {pendingCandidates.length}
                    </span>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      aria-label="下一候选"
                      disabled={pendingCandidates.length === 0}
                      onClick={() =>
                        setCurrentIndex((value) => Math.min(pendingCandidates.length - 1, value + 1))
                      }
                    >
                      <ChevronRight />
                    </Button>
                  </div>
                </div>

                {selectedIds.size > 0 ? (
                  <div className="mb-3 flex items-center gap-2">
                    <span className="text-caption text-muted-foreground">已选 {selectedIds.size} 条</span>
                    <Button size="sm" onClick={() => batchDecide.mutate('confirmed')}>
                      <Check />
                      批量采纳
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => batchDecide.mutate('rejected')}>
                      <X />
                      批量拒绝
                    </Button>
                  </div>
                ) : null}

                {candidates.isLoading ? (
                  <div className="h-64 animate-pulse bg-muted/40" />
                ) : (candidates.data?.length ?? 0) === 0 ? (
                  <div className="flex min-h-64 items-center justify-center rounded-md border text-body-sm text-muted-foreground">
                    <FileText className="mr-2 size-4" />
                    没有候选
                  </div>
                ) : (
                  <div className="space-y-3">
                    {(candidates.data ?? []).map((candidate) => (
                      <CandidateCard
                        key={candidate.id}
                        candidate={candidate}
                        selected={selectedIds.has(candidate.id)}
                        onSelect={(checked) =>
                          setSelectedIds((prev) => {
                            const next = new Set(prev)
                            if (checked) next.add(candidate.id)
                            else next.delete(candidate.id)
                            return next
                          })
                        }
                        onEdit={() => openEdit(candidate)}
                        onDecide={(status) => decide.mutate({ candidateId: candidate.id, status })}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <Dialog
        open={editCandidate !== null}
        onOpenChange={(open) => {
          if (!open) setEditCandidate(null)
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>编辑候选</DialogTitle>
            <DialogDescription>修改后仍可作为候选采纳。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="candidate-title" className="text-body-sm font-medium">标题</label>
              <Input
                id="candidate-title"
                value={editValues.title}
                onChange={(event) => setEditValues((prev) => ({ ...prev, title: event.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="candidate-content" className="text-body-sm font-medium">核心内容</label>
              <Textarea
                id="candidate-content"
                rows={5}
                value={editValues.content}
                onChange={(event) => setEditValues((prev) => ({ ...prev, content: event.target.value }))}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="candidate-type" className="text-body-sm font-medium">主类型</label>
                <select
                  id="candidate-type"
                  className="h-9 w-full rounded-md border px-2 text-body-sm"
                  value={editValues.main_type}
                  onChange={(event) =>
                    setEditValues((prev) => ({
                      ...prev,
                      main_type: event.target.value as CandidatePayload['main_type'],
                    }))
                  }
                >
                  <option value="knowledge">知识</option>
                  <option value="method">方法</option>
                  <option value="parameter">参数</option>
                  <option value="reminder">提醒</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="candidate-nature" className="text-body-sm font-medium">信息性质</label>
                <Input
                  id="candidate-nature"
                  value={editValues.info_nature}
                  onChange={(event) => setEditValues((prev) => ({ ...prev, info_nature: event.target.value }))}
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditCandidate(null)}>取消</Button>
            <Button onClick={() => saveEdit.mutate()}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
