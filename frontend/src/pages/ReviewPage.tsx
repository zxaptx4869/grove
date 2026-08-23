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
import { BatchReviewView } from '@/components/features/BatchReviewView'
import { DirectoryTreeSelect } from '@/components/features/DirectoryTreeSelect'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  addEvidence,
  applyRevision,
  archiveCandidate,
  archiveCandidateWithNewNode,
  decideCandidate,
  fetchReviewSources,
  fetchProjectTree,
  fetchSource,
  fetchSourceCandidates,
  sourceImageUrl,
  updateCandidate,
  type ApplyRevisionPayload,
  type CandidatePayload,
  type CandidateUpdatePayload,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

function formatTime(value: string) {
  const normalized = /(Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(date)
}

function relationLabel(status: CandidatePayload['relation_status']): string {
  if (status === 'duplicate') return '疑似重复'
  if (status === 'supplement') return '可以补充'
  if (status === 'conflict') return '可能冲突'
  return '新知识'
}

function flattenNodesWithParent(
  nodes: readonly TreeNodePayload[],
  parentId: number | null = null,
  prefix = '',
): Array<{ id: number; parentId: number | null; name: string; label: string }> {
  return nodes.flatMap((node) => [
    { id: node.id, parentId, name: node.name, label: `${prefix}${node.name}` },
    ...flattenNodesWithParent(node.children, node.id, `${prefix}${node.name} / `),
  ])
}

function findSuggestionNodeId(
  candidate: CandidatePayload,
  nodes: Array<{ id: number; parentId: number | null; name: string }>,
) {
  const suggestion = candidate.new_node_suggestion
  if (!suggestion?.name) return null
  const name = suggestion.name.trim().toLowerCase()
  const parentId = suggestion.parent_id ?? null
  return nodes.find(
    (node) => node.name.trim().toLowerCase() === name && node.parentId === parentId,
  )?.id ?? null
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
  nodeOptions,
  treeNodes,
  treeLoading = false,
  suggestionMatchNodeId,
  suggestionMatchLabel,
  onAdopt,
  onArchiveWithNewNode,
  onAddEvidence,
  onApplyRevision,
  onReject,
  onSkip,
  isPending,
}: {
  candidate: CandidatePayload
  nodeOptions: Array<{ value: number; label: string }>
  treeNodes: TreeNodePayload[]
  treeLoading?: boolean
  suggestionMatchNodeId: number | null
  suggestionMatchLabel: string | null
  onAdopt: (payload: {
    content: string
    main_type: CandidatePayload['main_type']
    info_nature: string | null
    node_id: number
  }) => void
  onArchiveWithNewNode: (payload: {
    content: string
    main_type: CandidatePayload['main_type']
    info_nature: string | null
    name: string
    parent_id: number | null
    description: string | null
  }) => void
  onAddEvidence: () => void
  onApplyRevision: () => void
  onReject: () => void
  onSkip: () => void
  isPending: boolean
}) {
  const [content, setContent] = useState(candidate.content)
  const [mainType, setMainType] = useState<CandidatePayload['main_type']>(candidate.main_type)
  const [infoNature, setInfoNature] = useState(candidate.info_nature ?? '')
  const [nodeId, setNodeId] = useState<number | null>(() => {
    if (candidate.routing_status === 'no_suitable') {
      return suggestionMatchNodeId ?? null
    }
    return candidate.recommended_node_id ?? null
  })
  const suggestion = candidate.new_node_suggestion
  const isNoSuitable = candidate.routing_status === 'no_suitable'
  const showNewNodeForm = isNoSuitable && suggestionMatchNodeId === null
  const [newNodeName, setNewNodeName] = useState(suggestion?.name ?? '')
  const recommendedLabel = nodeOptions.find(
    (option) => option.value === candidate.recommended_node_id,
  )?.label

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        <div>
          <span className="badge-ai">
            <Badge className="bg-ai-candidate-soft text-ai-candidate">推荐候选</Badge>
          </span>
          <h3 className="mt-2 text-[16px] font-[650] leading-6">{candidate.title}</h3>
        </div>
        {candidate.relation_status !== 'pending' && candidate.relation_status !== 'new' ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center gap-2">
              <Badge className="bg-amber-100 text-amber-700">
                {relationLabel(candidate.relation_status)}
              </Badge>
              {candidate.relation_target_entry_title ? (
                <span className="text-body-sm text-muted-foreground">
                  与「{candidate.relation_target_entry_title}」
                </span>
              ) : null}
            </div>
            {candidate.relation_reason ? (
              <p className="mt-1 text-caption text-muted-foreground">
                {candidate.relation_reason}
              </p>
            ) : null}
            {candidate.revision_draft?.change_summary ? (
              <p className="mt-1 text-caption text-muted-foreground">
                修订说明：{candidate.revision_draft.change_summary}
              </p>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-2">
              {candidate.relation_status === 'duplicate' ? (
                <Button
                  size="sm"
                  disabled={isPending || candidate.relation_target_entry_id == null}
                  onClick={onAddEvidence}
                >
                  补充来源证据
                </Button>
              ) : null}
              {candidate.relation_status === 'supplement' ? (
                <Button
                  size="sm"
                  disabled={isPending || !candidate.revision_draft}
                  onClick={onApplyRevision}
                >
                  应用修订草稿
                </Button>
              ) : null}
              {candidate.relation_status === 'conflict' ? (
                <>
                  <Button
                    size="sm"
                    disabled={isPending || nodeId === null}
                    onClick={() =>
                      onAdopt({
                        content: content.trim(),
                        main_type: mainType,
                        info_nature: infoNature.trim() || null,
                        node_id: nodeId as number,
                      })
                    }
                  >
                    并列保留
                  </Button>
                  <Button
                    size="sm"
                    disabled={isPending || !candidate.revision_draft}
                    onClick={onApplyRevision}
                  >
                    修订现有
                  </Button>
                  <Button size="sm" variant="outline" disabled={isPending} onClick={onReject}>
                    忽略
                  </Button>
                </>
              ) : null}
            </div>
          </div>
        ) : null}
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
        <div className="space-y-1.5">
          <span className="text-body-sm font-medium">归档目录</span>
          <DirectoryTreeSelect
            nodes={treeNodes}
            value={nodeId}
            loading={treeLoading}
            placeholder={nodeOptions.length > 0 ? '选择目录节点' : '项目还没有目录节点'}
            ariaLabel="归档目录"
            onSelect={(id) => setNodeId(id)}
          />
          {candidate.routing_status !== 'pending' ? (
            <p className="text-caption text-muted-foreground">
              {candidate.routing_status === 'no_suitable'
                ? '暂无合适目录，可手动选择或新增节点'
                : `AI 推荐${candidate.routing_status === 'needs_review' ? '（需确认）' : ''}：${recommendedLabel ?? '—'}`}
              {candidate.node_reason ? ` · ${candidate.node_reason}` : ''}
            </p>
          ) : (
            <p className="text-caption text-muted-foreground">目录推荐生成中…</p>
          )}
          {suggestionMatchNodeId !== null ? (
            <p className="text-caption text-muted-foreground">
              已有节点「{suggestionMatchLabel}」，将直接归档到该节点
            </p>
          ) : null}
          {showNewNodeForm ? (
            <div className="flex items-center gap-2">
              {suggestion?.name ? (
                <Button
                  size="sm"
                  variant="link"
                  disabled={isPending}
                  onClick={() =>
                    onArchiveWithNewNode({
                      content: content.trim(),
                      main_type: mainType,
                      info_nature: infoNature.trim() || null,
                      name: suggestion.name,
                      parent_id: suggestion.parent_id ?? null,
                      description: null,
                    })
                  }
                >
                  新增「{suggestion.name}」并归档
                </Button>
              ) : (
                <>
                  <Input
                    id="new-node-name"
                    aria-label="新节点名称"
                    placeholder="节点名称"
                    className="h-8"
                    value={newNodeName}
                    onChange={(event) => setNewNodeName(event.target.value)}
                  />
                  <Button
                    size="sm"
                    variant="link"
                    disabled={isPending || newNodeName.trim().length === 0}
                    onClick={() =>
                      onArchiveWithNewNode({
                        content: content.trim(),
                        main_type: mainType,
                        info_nature: infoNature.trim() || null,
                        name: newNodeName.trim(),
                        parent_id: null,
                        description: null,
                      })
                    }
                  >
                    新增并归档
                  </Button>
                </>
              )}
            </div>
          ) : null}
        </div>
        {candidate.reason ? (
          <p className="text-caption text-muted-foreground">
            推荐理由与风险：{candidate.reason}
          </p>
        ) : null}
      </div>

      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button size="sm" variant="outline" disabled={isPending} onClick={onReject}>
          <X />
          拒绝
        </Button>
        <Button size="sm" variant="ghost" disabled={isPending} onClick={onSkip}>
          跳过
        </Button>
        <Button
          size="sm"
          disabled={isPending || nodeId === null}
          onClick={() =>
            onAdopt({
              content: content.trim(),
              main_type: mainType,
              info_nature: infoNature.trim() || null,
              node_id: nodeId as number,
            })
          }
        >
          <Check />
          {candidate.relation_status === 'pending' || candidate.relation_status === 'new'
            ? '采纳'
            : '仍按新知识创建'}
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
  const [reviewMode, setReviewMode] = useState<'source' | 'batch'>('source')
  const [focusCandidateId, setFocusCandidateId] = useState<number | null>(null)

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
  const tree = useQuery({
    queryKey: queryKeys.projectTree(id),
    queryFn: () => fetchProjectTree(id),
    enabled: Number.isFinite(id),
  })
  const nodesWithParent = useMemo(
    () => flattenNodesWithParent(tree.data ?? []),
    [tree.data],
  )
  const nodeOptions = useMemo(
    () => nodesWithParent.map(({ id, label }) => ({ value: id, label })),
    [nodesWithParent],
  )

  const pendingCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.status === 'pending'),
    [candidates.data],
  )
  const rejectedCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.status === 'rejected'),
    [candidates.data],
  )
  const focusIndex =
    focusCandidateId != null
      ? pendingCandidates.findIndex((candidate) => candidate.id === focusCandidateId)
      : -1
  const effectiveIndex = focusIndex >= 0 ? focusIndex : currentIndex
  const currentCandidate = pendingCandidates[effectiveIndex] ?? null
  const suggestionMatchNodeId = currentCandidate
    ? findSuggestionNodeId(currentCandidate, nodesWithParent)
    : null
  const suggestionMatchLabel =
    suggestionMatchNodeId !== null
      ? (nodeOptions.find((option) => option.value === suggestionMatchNodeId)?.label ?? null)
      : null
  const groupedNodeSuggestions = useMemo(
    () => {
      const groups = new Map<
        string,
        { name: string; parentId: number | null; count: number }
      >()
      for (const candidate of pendingCandidates) {
        const suggestion = candidate.new_node_suggestion
        if (!suggestion?.name || candidate.routing_status !== 'no_suitable') continue
        const key = `${suggestion.parent_id ?? 'root'}::${suggestion.name.trim().toLowerCase()}`
        const existing = groups.get(key)
        if (existing) {
          existing.count += 1
        } else {
          groups.set(key, {
            name: suggestion.name.trim(),
            parentId: suggestion.parent_id ?? null,
            count: 1,
          })
        }
      }
      return Array.from(groups.values())
    },
    [pendingCandidates],
  )
  const singleImage =
    (source.data?.attachments.filter((attachment) => attachment.kind === 'image').length ?? 0) ===
    1

  const adopt = useGroveMutation({
    mutationFn: async ({
      candidate,
      payload,
    }: {
      candidate: CandidatePayload
      payload: {
        content: string
        main_type: CandidatePayload['main_type']
        info_nature: string | null
        node_id: number
      }
    }) => {
      await updateCandidate(candidate.id, {
        content: payload.content,
        main_type: payload.main_type,
        info_nature: payload.info_nature as CandidateUpdatePayload['info_nature'],
      })
      return archiveCandidate(candidate.id, payload.node_id)
    },
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      goToIndex((value) => Math.max(0, value - 1))
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
      goToIndex((value) => Math.max(0, value - 1))
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
    onSuccess: () => {
      goToIndex(0)
      toast.success('候选已重新打开')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '操作失败'),
  })
  const archiveNewNode = useGroveMutation({
    mutationFn: async ({
      candidate,
      payload,
    }: {
      candidate: CandidatePayload
      payload: {
        content: string
        main_type: CandidatePayload['main_type']
        info_nature: string | null
        name: string
        parent_id: number | null
        description: string | null
      }
    }) => {
      await updateCandidate(candidate.id, {
        content: payload.content,
        main_type: payload.main_type,
        info_nature: payload.info_nature as CandidateUpdatePayload['info_nature'],
      })
      return archiveCandidateWithNewNode(candidate.id, {
        name: payload.name,
        parent_id: payload.parent_id ?? null,
        description: payload.description ?? null,
      })
    },
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
      queryKeys.projectTree(id),
    ],
    onSuccess: () => {
      goToIndex((value) => Math.max(0, value - 1))
      toast.success('候选已归档并创建节点')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '创建节点失败'),
  })
  const addEvidenceRelation = useGroveMutation({
    mutationFn: (candidate: CandidatePayload) =>
      addEvidence(candidate.id, {
        entry_id: candidate.relation_target_entry_id as number,
      }),
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      goToIndex((value) => Math.max(0, value - 1))
      toast.success('已补充来源证据')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '补充来源失败'),
  })
  const applyRevisionRelation = useGroveMutation({
    mutationFn: ({
      candidate,
      payload,
    }: {
      candidate: CandidatePayload
      payload: ApplyRevisionPayload
    }) => applyRevision(candidate.id, payload),
    invalidates: [
      queryKeys.sourceCandidates(activeSourceId ?? 0),
      queryKeys.reviewSources(id),
    ],
    onSuccess: () => {
      goToIndex((value) => Math.max(0, value - 1))
      toast.success('已应用修订')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '应用修订失败'),
  })
  function selectSource(sourceId: number) {
    setFocusCandidateId(null)
    setSelectedSourceId(sourceId)
    setCurrentIndex(0)
    setQueueOpen(false)
  }

  function handleReviewCandidate(candidateId: number, sourceId: number) {
    setReviewMode('source')
    setSelectedSourceId(sourceId)
    setFocusCandidateId(candidateId)
    setCurrentIndex(0)
  }

  function goToIndex(index: number | ((value: number) => number)) {
    setFocusCandidateId(null)
    setCurrentIndex(index)
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
      <header className="grid min-h-[58px] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 px-6">
        <h1 className="text-[22px] font-[650] leading-[30px]">确认台</h1>
        <div className="flex items-center justify-self-center gap-[7px] rounded-md border bg-muted/50 p-[3px]">
          <button
            type="button"
            onClick={() => setReviewMode('source')}
            className={`flex h-[30px] items-center rounded-[4px] px-[9px] text-caption transition-colors ${reviewMode === 'source' ? 'bg-card font-medium text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-muted-foreground hover:text-foreground'}`}
          >
            按采集审阅
          </button>
          <button
            type="button"
            onClick={() => setReviewMode('batch')}
            className={`flex h-[30px] items-center rounded-[4px] px-[9px] text-caption transition-colors ${reviewMode === 'batch' ? 'bg-card font-medium text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-muted-foreground hover:text-foreground'}`}
          >
            批量处理
          </button>
        </div>
        <Badge className="bg-ai-candidate-soft text-ai-candidate">
          {reviewSources.data?.length ?? 0} 条待确认
        </Badge>
      </header>

      {reviewMode === 'batch' ? (
        <BatchReviewView projectId={id} onReviewCandidate={handleReviewCandidate} />
      ) : (
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
                    if (effectiveIndex === 0) toast('已经是第一条候选')
                    else goToIndex((value) => value - 1)
                  }}
                >
                  <ChevronLeft />
                </Button>
                <span className="text-caption text-muted-foreground">
                  当前候选 {pendingCandidates.length > 0 ? effectiveIndex + 1 : 0} /{' '}
                  {pendingCandidates.length}
                </span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label="下一候选"
                  disabled={pendingCandidates.length === 0}
                  onClick={() => {
                    if (effectiveIndex >= pendingCandidates.length - 1)
                      toast('已经是最后一条候选')
                    else goToIndex((value) => value + 1)
                  }}
                >
                  <ChevronRight />
                </Button>
              </div>
            </div>

            {groupedNodeSuggestions.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5 border-b px-5 py-2">
                {groupedNodeSuggestions.map((item) => (
                  <span
                    key={`${item.parentId ?? 'root'}:${item.name}`}
                    className="text-caption text-muted-foreground"
                  >
                    建议新增「{item.name}」{item.count > 1 ? ` · ${item.count} 条` : ''}
                  </span>
                ))}
              </div>
            ) : null}

            {candidates.isLoading ? (
              <div className="min-h-0 flex-1 p-5">
                <div className="h-64 animate-pulse bg-muted/40" />
              </div>
            ) : currentCandidate ? (
              <CandidateEditor
                key={currentCandidate.id}
                candidate={currentCandidate}
                nodeOptions={nodeOptions}
                treeNodes={tree.data ?? []}
                treeLoading={tree.isLoading}
                suggestionMatchNodeId={suggestionMatchNodeId}
                suggestionMatchLabel={suggestionMatchLabel}
                isPending={
                  adopt.isPending ||
                  reject.isPending ||
                  archiveNewNode.isPending ||
                  addEvidenceRelation.isPending ||
                  applyRevisionRelation.isPending
                }
                onAdopt={(payload) => adopt.mutate({ candidate: currentCandidate, payload })}
                onArchiveWithNewNode={(payload) =>
                  archiveNewNode.mutate({ candidate: currentCandidate, payload })
                }
                onAddEvidence={() => addEvidenceRelation.mutate(currentCandidate)}
                onApplyRevision={() => {
                  const draft = currentCandidate.revision_draft
                  if (!draft) return
                  applyRevisionRelation.mutate({
                    candidate: currentCandidate,
                    payload: {
                      entry_id: currentCandidate.relation_target_entry_id as number,
                      title: draft.title ?? undefined,
                      content: draft.content ?? undefined,
                      main_type: draft.main_type ?? undefined,
                      info_nature:
                        (draft.info_nature as ApplyRevisionPayload['info_nature']) ?? undefined,
                      applicable_condition: draft.applicable_condition ?? undefined,
                      note: draft.note ?? undefined,
                      change_summary: draft.change_summary ?? undefined,
                    },
                  })
                }}
                onReject={() => reject.mutate(currentCandidate)}
                onSkip={() =>
                  goToIndex((value) => Math.min(pendingCandidates.length - 1, value + 1))
                }
              />
            ) : rejectedCandidates.length > 0 ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <p className="mb-2 text-caption text-muted-foreground">已拒绝候选</p>
                <div className="space-y-2">
                  {rejectedCandidates.map((candidate) => (
                    <div
                      key={candidate.id}
                      className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-body-sm">{candidate.title}</p>
                        <Badge className="mt-1 bg-error-soft text-destructive">已拒绝</Badge>
                      </div>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={reopen.isPending}
                        aria-label={`重新打开「${candidate.title}」`}
                        onClick={() => reopen.mutate(candidate)}
                      >
                        <Pencil />
                        重新打开
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 items-center justify-center p-5 text-body-sm text-muted-foreground">
                没有待采纳候选
              </div>
            )}

          </section>
        </div>
      </div>
      )}

      {reviewMode === 'source' && queueOpen ? (
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
                    {item.pending_candidate_count} 条待采纳 · {item.review_status === 'partial_review' ? '部分确认' : '待确认'}
                    {formatTime(item.created_at) ? ` · ${formatTime(item.created_at)}` : ''}
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
