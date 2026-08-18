import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CheckCheck, FolderInput, ShieldAlert } from 'lucide-react'
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
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { DirectoryTreeSelect } from '@/components/features/DirectoryTreeSelect'
import {
  batchDecideProjectCandidates,
  batchUpdateCandidatesDirectory,
  fetchProjectTree,
  fetchReviewCandidates,
  type ReviewCandidatePayload,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const TYPE_LABELS: Record<ReviewCandidatePayload['main_type'], string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

function buildNodeLabels(
  nodes: readonly TreeNodePayload[],
  prefix = '',
): Map<number, string> {
  const labels = new Map<number, string>()
  for (const node of nodes) {
    const label = prefix ? `${prefix} / ${node.name}` : node.name
    labels.set(node.id, label)
    for (const [id, childLabel] of buildNodeLabels(node.children, label)) {
      labels.set(id, childLabel)
    }
  }
  return labels
}

function routingReason(candidate: ReviewCandidatePayload): string {
  if (candidate.risk_flags.length > 0) return candidate.risk_flags[0]
  if (candidate.candidate_kind === 'other') return '其他发现'
  if (candidate.routing_status === 'needs_review') return '需要确认'
  if (candidate.routing_status === 'no_suitable') return '暂无合适位置'
  return '需精审'
}

export function BatchReviewView({
  projectId,
  onReviewCandidate,
}: {
  projectId: number
  onReviewCandidate: (candidateId: number, sourceId: number) => void
}) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [directoryNodeId, setDirectoryNodeId] = useState<number | null>(null)
  const [directoryOpen, setDirectoryOpen] = useState(false)

  const candidates = useQuery({
    queryKey: queryKeys.reviewCandidates(projectId),
    queryFn: () => fetchReviewCandidates(projectId),
    enabled: Number.isFinite(projectId),
  })
  const tree = useQuery({
    queryKey: queryKeys.projectTree(projectId),
    queryFn: () => fetchProjectTree(projectId),
    enabled: Number.isFinite(projectId),
  })
  const nodeLabels = useMemo(() => buildNodeLabels(tree.data ?? []), [tree.data])

  const quickCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.review_band === 'quick'),
    [candidates.data],
  )
  const detailedCandidates = useMemo(
    () => (candidates.data ?? []).filter((candidate) => candidate.review_band === 'detailed'),
    [candidates.data],
  )
  const groups = useMemo(() => {
    const byNode = new Map<number, ReviewCandidatePayload[]>()
    for (const candidate of quickCandidates) {
      const effectiveNodeId = candidate.user_node_id ?? candidate.recommended_node_id
      if (effectiveNodeId == null) continue
      const list = byNode.get(effectiveNodeId) ?? []
      list.push(candidate)
      byNode.set(effectiveNodeId, list)
    }
    return Array.from(byNode.entries())
      .map(([nodeId, list]) => ({
        nodeId,
        label: nodeLabels.get(nodeId) ?? `节点 ${nodeId}`,
        candidates: list,
      }))
      .sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
  }, [quickCandidates, nodeLabels])

  function toggleSelected(candidateId: number) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(candidateId)) next.delete(candidateId)
      else next.add(candidateId)
      return next
    })
  }

  function toggleExpanded(candidateId: number) {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(candidateId)) next.delete(candidateId)
      else next.add(candidateId)
      return next
    })
  }

  const invalidates = [
    queryKeys.reviewCandidates(projectId),
    queryKeys.reviewSources(projectId),
    queryKeys.projectTree(projectId),
  ]
  const confirmBatch = useGroveMutation({
    mutationFn: () =>
      batchDecideProjectCandidates(projectId, {
        candidate_ids: Array.from(selectedIds),
        action: 'confirm',
      }),
    invalidates,
    onSuccess: (results) => {
      const failed = results.filter((item) => item.status === 'failed').length
      const succeeded = results.filter((item) => item.status === 'confirmed').length
      setSelectedIds(new Set())
      if (failed > 0) {
        toast.error(`已归档 ${succeeded} 条，${failed} 条失败，失败项仍可重试`)
      } else {
        toast.success(`已归档 ${succeeded} 条候选`)
      }
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '批量确认失败'),
  })
  const rejectBatch = useGroveMutation({
    mutationFn: () =>
      batchDecideProjectCandidates(projectId, {
        candidate_ids: Array.from(selectedIds),
        action: 'reject',
      }),
    invalidates: [queryKeys.reviewCandidates(projectId), queryKeys.reviewSources(projectId)],
    onSuccess: (results) => {
      setSelectedIds(new Set())
      toast.success(`已拒绝 ${results.length} 条候选`)
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '批量拒绝失败'),
  })
  const updateDirectory = useGroveMutation({
    mutationFn: () =>
      batchUpdateCandidatesDirectory(projectId, {
        candidate_ids: Array.from(selectedIds),
        node_id: directoryNodeId as number,
      }),
    invalidates: [queryKeys.reviewCandidates(projectId), queryKeys.reviewSources(projectId)],
    onSuccess: (result) => {
      setSelectedIds(new Set())
      setDirectoryNodeId(null)
      setDirectoryOpen(false)
      toast.success(`已为 ${result.updated} 条候选设置目录`)
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '修改目录失败'),
  })

  const selectedCount = selectedIds.size

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="sticky top-0 z-10 flex min-h-[56px] items-center gap-2 border-b bg-card px-6">
        <strong className="text-body-sm">已选 {selectedCount} 条低风险候选</strong>
        <Button
          size="sm"
          disabled={selectedCount === 0 || confirmBatch.isPending}
          onClick={() => confirmBatch.mutate()}
        >
          <CheckCheck />
          批量采纳
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="border-destructive/40 bg-error-soft text-destructive hover:bg-error-soft/70 hover:text-destructive"
          disabled={selectedCount === 0 || rejectBatch.isPending}
          onClick={() => rejectBatch.mutate()}
        >
          批量拒绝
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setDirectoryOpen(true)}
          disabled={selectedCount === 0}
        >
          <FolderInput />
          修改目录
        </Button>
        <span className="ml-auto text-caption text-muted-foreground">
          高风险、需要确认、暂无合适位置和其他发现已自动分流精审。
        </span>
      </div>

      <div className="space-y-4 px-6 py-4">
        {candidates.isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((item) => (
              <div key={item} className="h-[64px] animate-pulse rounded-md bg-muted/50" />
            ))}
          </div>
        ) : candidates.isError ? (
          <div className="rounded-md bg-error-soft px-3 py-3 text-body-sm text-destructive">
            批量候选加载失败，请重试。
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
          <p className="py-10 text-center text-body-sm text-muted-foreground">
            没有待采纳候选
          </p>
        ) : (
          <>
            {groups.map((group) => (
              <section key={group.nodeId} className="rounded-md border">
                <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
                  <FolderInput className="size-4 text-muted-foreground" />
                  <h3 className="min-w-0 truncate text-body font-[650]">{group.label}</h3>
                  <Badge className="shrink-0 bg-ai-candidate-soft text-ai-candidate">
                    推荐明确 · {group.candidates.length}
                  </Badge>
                </div>
                <div className="divide-y">
                  {group.candidates.map((candidate) => (
                    <BatchCandidateRow
                      key={candidate.id}
                      candidate={candidate}
                      selected={selectedIds.has(candidate.id)}
                      expanded={expandedIds.has(candidate.id)}
                      onToggleSelected={() => toggleSelected(candidate.id)}
                      onToggleExpanded={() => toggleExpanded(candidate.id)}
                    />
                  ))}
                </div>
              </section>
            ))}

            {detailedCandidates.length > 0 ? (
              <section className="rounded-md border">
                <div className="flex items-center gap-2 border-b bg-muted/30 px-3 py-2">
                  <ShieldAlert className="size-4 text-destructive" />
                  <h3 className="text-body font-[650]">已分流精审</h3>
                  <Badge className="shrink-0 bg-error-soft text-destructive">
                    {detailedCandidates.length} 条不参与快审
                  </Badge>
                </div>
                <div className="divide-y">
                  {detailedCandidates.map((candidate) => (
                    <div key={candidate.id} className="flex items-center gap-3 px-3 py-2.5">
                      <input type="checkbox" disabled aria-label="精审候选不可批量勾选" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-body-sm font-medium">{candidate.title}</p>
                        <p className="text-caption text-muted-foreground">
                          {routingReason(candidate)} · 来自：{candidate.source_title}
                        </p>
                      </div>
                      <Badge className="bg-error-soft text-destructive">需精审</Badge>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onReviewCandidate(candidate.id, candidate.source_id)}
                      >
                        精审
                      </Button>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>

      <Dialog open={directoryOpen} onOpenChange={setDirectoryOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>修改目录</DialogTitle>
            <DialogDescription>
              为选中的 {selectedCount} 条候选选择统一归档目录。
            </DialogDescription>
          </DialogHeader>
          <DirectoryTreeSelect
            nodes={tree.data ?? []}
            value={directoryNodeId}
            loading={tree.isLoading}
            placeholder="按各自推荐目录"
            ariaLabel="统一归档目录"
            onSelect={(id) => setDirectoryNodeId(id)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDirectoryOpen(false)}>
              取消
            </Button>
            <Button
              disabled={directoryNodeId == null || updateDirectory.isPending}
              onClick={() => updateDirectory.mutate()}
            >
              {updateDirectory.isPending ? '保存中…' : '确认'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function BatchCandidateRow({
  candidate,
  selected,
  expanded,
  onToggleSelected,
  onToggleExpanded,
}: {
  candidate: ReviewCandidatePayload
  selected: boolean
  expanded: boolean
  onToggleSelected: () => void
  onToggleExpanded: () => void
}) {
  return (
    <div className="px-3 py-2.5">
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelected}
          aria-label={`选择「${candidate.title}」`}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-body-sm font-medium">{candidate.title}</p>
          <p className="truncate text-caption text-muted-foreground">
            来自：{candidate.source_title} · {TYPE_LABELS[candidate.main_type]}
          </p>
        </div>
        <Badge className="bg-ai-candidate-soft text-ai-candidate">新知识</Badge>
        <Button size="sm" variant="ghost" onClick={onToggleExpanded}>
          {expanded ? '收起来源' : '展开来源'}
        </Button>
      </div>
      {expanded ? (
        <div className="mt-2 space-y-1 border-l-2 border-muted pl-3">
          {candidate.source_note ? (
            <p className="text-caption text-muted-foreground">采集说明：{candidate.source_note}</p>
          ) : null}
          {candidate.evidence.length > 0 ? (
            <blockquote className="border-l-2 px-2 text-caption text-muted-foreground">
              {candidate.evidence.map((item) => item.quote).join(' ')}
            </blockquote>
          ) : (
            <p className="text-caption text-muted-foreground">没有证据引用</p>
          )}
        </div>
      ) : null}
    </div>
  )
}
