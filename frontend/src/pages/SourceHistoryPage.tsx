import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Search, X } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { SourceList } from '@/components/features/SourceList'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  deleteSource,
  fetchProjects,
  fetchSourcePage,
  triggerProcessing,
  updateSource,
  type ProjectStatus,
  type SourceStatus,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const PROJECT_STATUSES: ProjectStatus[] = ['active', 'paused', 'completed', 'archived']
const SOURCE_STATUSES: Array<{ value: SourceStatus; label: string }> = [
  { value: 'waiting', label: '待处理' },
  { value: 'processing', label: '处理中' },
  { value: 'done', label: '已完成' },
  { value: 'failed', label: '失败' },
]
const PAGE_SIZE = 20

/** 全屏来源历史页：筛选、搜索与分页管理全部采集来源。 */
export function SourceHistoryPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [projectId, setProjectId] = useState<number | 'all'>(() => {
    const raw = searchParams.get('project')
    const parsed = raw ? Number(raw) : NaN
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 'all'
  })
  const [status, setStatus] = useState<SourceStatus | 'all'>('all')
  const [unassigned, setUnassigned] = useState(false)
  const [queryInput, setQueryInput] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [page, setPage] = useState(1)

  // 输入防抖自动查询：清空输入后自动回到全部数据
  useEffect(() => {
    const timer = setTimeout(() => {
      setSubmittedQuery(queryInput.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(timer)
  }, [queryInput])

  const projects = useQuery({
    queryKey: [...queryKeys.projects, 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))).flat(),
    staleTime: 30_000,
  })

  const sources = useQuery({
    queryKey: [
      'sources-page',
      projectId,
      status,
      unassigned,
      submittedQuery,
      page,
    ],
    queryFn: () =>
      fetchSourcePage({
        projectId: projectId !== 'all' ? projectId : undefined,
        unassigned: unassigned || undefined,
        status: status !== 'all' ? status : undefined,
        q: submittedQuery || undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      }),
  })

  const invalidatePages = () =>
    queryClient.invalidateQueries({ queryKey: ['sources-page'] })
  const assign = useGroveMutation({
    mutationFn: ({ id, targetId }: { id: number; targetId: number | null }) =>
      updateSource(id, { project_id: targetId }),
    invalidates: [queryKeys.sources],
    onSuccess: () => {
      invalidatePages()
      toast.success('来源归属已更新')
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '更新失败，请重试'),
  })
  const remove = useGroveMutation({
    mutationFn: (id: number) => deleteSource(id),
    invalidates: [queryKeys.sources],
    onSuccess: () => {
      invalidatePages()
      toast.success('来源已删除')
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '删除失败，请重试'),
  })
  const trigger = useGroveMutation({
    mutationFn: (id: number) => triggerProcessing(id),
    invalidates: [queryKeys.sources],
    onSuccess: () => {
      invalidatePages()
      toast.success('已开始处理')
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '触发处理失败'),
  })

  const total = sources.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const projectOptions = (projects.data ?? []).map((project) => ({
    id: project.id,
    name: project.name,
  }))

  function search() {
    setSubmittedQuery(queryInput.trim())
    setPage(1)
  }

  return (
    <section className="w-full px-6 pb-[30px] pt-[22px]">
      <header className="mb-5">
        <h1 className="text-[22px] font-[650] leading-[30px]">全部来源</h1>
        <p className="mt-0.5 text-body text-muted-foreground">
          查询与管理所有采集来源，可按项目、状态和关键词筛选。
        </p>
      </header>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select
          aria-label="项目筛选"
          className="h-9 w-40 rounded-md border px-2 text-body-sm"
          value={String(projectId)}
          onChange={(event) => {
            const value = event.target.value
            setProjectId(value === 'all' ? 'all' : Number(value))
            setPage(1)
          }}
        >
          <option value="all">全部项目</option>
          {projectOptions.map((project) => (
            <option key={project.id} value={String(project.id)}>
              {project.name}
            </option>
          ))}
        </select>
        <select
          aria-label="状态筛选"
          className="h-9 w-32 rounded-md border px-2 text-body-sm"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as SourceStatus | 'all')
            setPage(1)
          }}
        >
          <option value="all">全部状态</option>
          {SOURCE_STATUSES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <label className="flex h-9 cursor-pointer items-center gap-1.5 text-body-sm">
          <input
            type="checkbox"
            checked={unassigned}
            onChange={(event) => {
              setUnassigned(event.target.checked)
              setPage(1)
            }}
          />
          仅未归属
        </label>
        <div className="ml-auto flex w-72 items-center gap-2">
          <Input
            value={queryInput}
            onChange={(event) => setQueryInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') search()
            }}
            placeholder="搜索标题或备注…"
            aria-label="搜索来源"
          />
          {queryInput ? (
            <button
              type="button"
              aria-label="清空搜索"
              onClick={() => setQueryInput('')}
              className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          ) : null}
          <Button size="sm" variant="outline" onClick={search}>
            <Search />
            搜索
          </Button>
        </div>
      </div>

      {sources.isLoading ? (
        <div className="space-y-2 border-t" aria-label="来源加载中">
          {[1, 2, 3].map((item) => (
            <div key={item} className="h-[64px] animate-pulse bg-muted/50" />
          ))}
        </div>
      ) : sources.isError ? (
        <div className="border-t pt-4">
          <p className="text-body-sm">来源列表加载失败，请重试。</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => sources.refetch()}>
            重试
          </Button>
        </div>
      ) : (
        <SourceList
          sources={sources.data?.items ?? []}
          projects={projectOptions}
          onAssign={(id, targetId) => assign.mutate({ id, targetId })}
          onTrigger={(id) => trigger.mutate(id)}
          onDelete={(id) => remove.mutate(id)}
        />
      )}

      <div className="mt-4 flex items-center justify-end gap-2 text-body-sm text-muted-foreground">
        <span>
          第 {page} / {totalPages} 页 · 共 {total} 条
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={page <= 1 || sources.isLoading}
          onClick={() => setPage((value) => Math.max(1, value - 1))}
        >
          上一页
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={page >= totalPages || sources.isLoading}
          onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
        >
          下一页
        </Button>
      </div>
    </section>
  )
}
