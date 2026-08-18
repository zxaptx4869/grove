import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Pencil, RotateCw, Sparkles } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  fetchProjectContext,
  refreshProjectContext,
  updateProjectContext,
  type ProjectContextStatus,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const STATUS_LABELS: Record<ProjectContextStatus, string> = {
  pending: '等待生成',
  ready: '已生成',
  failed: '生成失败',
}

const MAX_TOPIC_BADGES = 8

function statusClass(status: ProjectContextStatus) {
  if (status === 'ready') return 'bg-confirmed-soft text-confirmed'
  if (status === 'failed') return 'bg-error-soft text-destructive'
  return 'bg-muted text-muted-foreground'
}

function formatGeneratedAt(value: string | null) {
  if (!value) return '尚未生成'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

/** 项目上下文面板：展示 AI 候选概要，支持纠正与重新生成。 */
export function ProjectContextPanel({
  projectId,
  nodes = [],
}: {
  projectId: number
  nodes?: TreeNodePayload[]
}) {
  const [correctOpen, setCorrectOpen] = useState(false)
  const [summary, setSummary] = useState('')
  const [focus, setFocus] = useState('')
  const [actionError, setActionError] = useState('')

  const context = useQuery({
    queryKey: queryKeys.projectContext(projectId),
    queryFn: () => fetchProjectContext(projectId),
  })

  const refresh = useGroveMutation({
    mutationFn: () => refreshProjectContext(projectId),
    invalidates: [queryKeys.projectContext(projectId)],
    onSuccess: () => {
      setActionError('')
      toast.success('项目上下文已重新生成')
    },
    onError: (error) =>
      setActionError(error instanceof Error ? error.message : '重新生成失败，请重试'),
  })
  const correct = useGroveMutation({
    mutationFn: (payload: { project_summary: string | null; current_focus: string | null }) =>
      updateProjectContext(projectId, payload),
    invalidates: [queryKeys.projectContext(projectId)],
    onSuccess: () => {
      setCorrectOpen(false)
      setActionError('')
      toast.success('项目上下文纠正已保存')
    },
    onError: (error) =>
      setActionError(error instanceof Error ? error.message : '保存纠正失败，请重试'),
  })

  if (context.isLoading) {
    return (
      <div className="space-y-3 border-t pt-5" aria-label="项目上下文加载中">
        <div className="h-5 w-32 animate-pulse bg-muted/50" />
        <div className="h-16 animate-pulse bg-muted/40" />
        <div className="h-10 animate-pulse bg-muted/40" />
      </div>
    )
  }
  if (context.isError) {
    return (
      <div className="mt-7 border-t pt-5">
        <p className="text-body-sm">项目上下文加载失败，请重试。</p>
        <Button className="mt-3" variant="outline" size="sm" onClick={() => context.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const data = context.data
  if (!data) return null
  const topicNames = nodes.length > 0 ? nodes.map((node) => node.name) : data.directory_topics
  const recentThemes = data.recent_themes ?? []
  const entrySummary = data.entries_summary

  const openCorrect = () => {
    setSummary(data.corrections.project_summary ?? data.project_summary ?? '')
    setFocus(data.corrections.current_focus ?? data.current_focus ?? '')
    setActionError('')
    setCorrectOpen(true)
  }

  return (
    <section className="mt-7 border-t pt-5">
      <div className="flex h-9 items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h2 className="text-[16px] font-[650] leading-6">项目上下文</h2>
          <Badge className={`min-h-[22px] rounded px-[7px] py-0.5 text-[11px] font-semibold ${statusClass(data.status)}`}>
            {STATUS_LABELS[data.status]}
          </Badge>
          {data.provider === 'llm' && !data.is_fallback ? (
            <Badge className="min-h-[22px] rounded bg-confirmed-soft px-[7px] py-0.5 text-[11px] font-semibold text-confirmed">
              真实模型
            </Badge>
          ) : data.is_fallback || data.provider === 'offline' || data.provider === 'demo' ? (
            <Badge className="min-h-[22px] rounded bg-error-soft px-[7px] py-0.5 text-[11px] font-semibold text-destructive">
              离线生成
            </Badge>
          ) : (
            <Badge className="min-h-[22px] rounded bg-muted px-[7px] py-0.5 text-[11px] font-semibold text-muted-foreground">
              来源未标注
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={openCorrect}>
            <Pencil />
            纠正
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            <RotateCw className="size-3.5" />
            {refresh.isPending ? '重新生成中…' : '重新生成'}
          </Button>
        </div>
      </div>

      {data.error && data.status !== 'failed' ? (
        <div className="mt-3 rounded-md border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive">
          上次更新失败，当前展示上一份快照：{data.error}
        </div>
      ) : null}

      <div className="mt-3 space-y-3 text-body-sm leading-6 text-muted-foreground">
        <div>
          <p className="text-caption font-medium text-muted-foreground">项目概要</p>
          <p className="mt-0.5 text-foreground">{data.project_summary || '尚未生成项目概要'}</p>
        </div>
        <div>
          <p className="text-caption font-medium text-muted-foreground">当前关注</p>
          <p className="mt-0.5 text-foreground">{data.current_focus || '尚未生成当前关注方向'}</p>
        </div>
        <div>
          <p className="text-caption font-medium text-muted-foreground">目录主题</p>
          {topicNames.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {topicNames.slice(0, MAX_TOPIC_BADGES).map((topic) => (
                <Badge key={topic} variant="outline" className="bg-muted/40 text-muted-foreground">
                  {topic}
                </Badge>
              ))}
              {topicNames.length > MAX_TOPIC_BADGES ? (
                <Badge variant="outline" className="bg-muted/40 text-muted-foreground">
                  +{topicNames.length - MAX_TOPIC_BADGES}
                </Badge>
              ) : null}
            </div>
          ) : (
            <p className="mt-0.5">目录还是空的</p>
          )}
        </div>
        <div>
          <p className="text-caption font-medium text-muted-foreground">近期主题</p>
          {recentThemes.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {recentThemes.slice(0, MAX_TOPIC_BADGES).map((theme) => (
                <Badge key={theme} variant="outline" className="bg-brand-soft text-brand">
                  {theme}
                </Badge>
              ))}
              {recentThemes.length > MAX_TOPIC_BADGES ? (
                <Badge variant="outline" className="bg-muted/40 text-muted-foreground">
                  +{recentThemes.length - MAX_TOPIC_BADGES}
                </Badge>
              ) : null}
            </div>
          ) : (
            <p className="mt-0.5">暂无近期主题</p>
          )}
        </div>
        <div>
          <p className="text-caption font-medium text-muted-foreground">知识覆盖</p>
          <p className="mt-0.5 text-foreground">已确认 {entrySummary?.total ?? 0} 条正式知识</p>
          {entrySummary && entrySummary.by_top_node.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {entrySummary.by_top_node.slice(0, MAX_TOPIC_BADGES).map((node) => (
                <Badge key={node.node_id} variant="outline" className="bg-muted/40 text-muted-foreground">
                  {node.name} · {node.count}
                </Badge>
              ))}
              {entrySummary.by_top_node.length > MAX_TOPIC_BADGES ? (
                <Badge variant="outline" className="bg-muted/40 text-muted-foreground">
                  +{entrySummary.by_top_node.length - MAX_TOPIC_BADGES}
                </Badge>
              ) : null}
            </div>
          ) : null}
        </div>
        <p className="text-caption text-muted-foreground">
          <Sparkles className="mr-1 inline size-3.5" />
          AI 候选 · 更新于 {formatGeneratedAt(data.generated_at)} · 版本 v{data.version ?? 0} ·
          更新原因 {data.last_update_reason ?? '—'} · 模型 {data.model ?? '—'} · 生命周期{' '}
          {data.lifecycle_status}
        </p>
      </div>

      <Dialog
        open={correctOpen}
        onOpenChange={(open) => {
          setCorrectOpen(open)
          if (!open) setActionError('')
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>纠正项目上下文</DialogTitle>
            <DialogDescription>
              你的纠正会作为高优先级约束保留，重新生成时优先考虑。
            </DialogDescription>
          </DialogHeader>
          {actionError ? (
            <div className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">
              {actionError}
            </div>
          ) : null}
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="context-summary" className="text-body-sm font-medium">
                项目概要
              </label>
              <Textarea
                id="context-summary"
                value={summary}
                onChange={(event) => setSummary(event.target.value)}
                rows={3}
                placeholder="用你的方式概括这个项目"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="context-focus" className="text-body-sm font-medium">
                当前关注方向
              </label>
              <Textarea
                id="context-focus"
                value={focus}
                onChange={(event) => setFocus(event.target.value)}
                rows={3}
                placeholder="当前最需要关注什么"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCorrectOpen(false)}>
              取消
            </Button>
            <Button
              disabled={correct.isPending}
              onClick={() =>
                correct.mutate({
                  project_summary: summary.trim() || null,
                  current_focus: focus.trim() || null,
                })
              }
            >
              {correct.isPending ? '保存中…' : '保存纠正'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
