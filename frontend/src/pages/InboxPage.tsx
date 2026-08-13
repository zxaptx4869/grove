import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { SourceCapture } from '@/components/features/SourceCapture'
import { SourceList } from '@/components/features/SourceList'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { Button } from '@/components/ui/button'
import {
  deleteSource,
  fetchProjects,
  fetchSources,
  triggerProcessing,
  updateSource,
  type ProjectStatus,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const PROJECT_STATUSES: ProjectStatus[] = ['active', 'paused', 'completed', 'archived']

/** 全局收集箱：采集入口与未归属/全部来源列表。 */
export function InboxPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<'all' | 'unassigned'>('unassigned')

  const projects = useQuery({
    queryKey: [...queryKeys.projects, 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))).flat(),
    staleTime: 30_000,
  })
  const sources = useQuery({
    queryKey: [...queryKeys.sources, filter],
    queryFn: () => fetchSources({ unassigned: filter === 'unassigned' }),
  })

  const invalidateSources = () => queryClient.invalidateQueries({ queryKey: queryKeys.sources })
  const assign = useGroveMutation({
    mutationFn: ({ id, projectId }: { id: number; projectId: number | null }) =>
      updateSource(id, { project_id: projectId }),
    invalidates: [queryKeys.sources],
    onSuccess: () => {
      toast.success('来源归属已更新')
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '更新失败，请重试'),
  })
  const remove = useGroveMutation({
    mutationFn: (id: number) => deleteSource(id),
    invalidates: [queryKeys.sources],
    onSuccess: () => {
      toast.success('来源已删除')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败，请重试'),
  })
  const trigger = useGroveMutation({
    mutationFn: (id: number) => triggerProcessing(id),
    invalidates: [queryKeys.sources],
    onSuccess: () => toast.success('已开始处理'),
    onError: (error) => toast.error(error instanceof Error ? error.message : '触发处理失败'),
  })

  const projectOptions = (projects.data ?? []).map((project) => ({
    id: project.id,
    name: project.name,
  }))

  return (
    <section className="w-full px-6 pb-[30px] pt-[22px]">
      <header className="mb-5">
        <h1 className="text-[22px] font-[650] leading-[30px]">收集箱</h1>
        <p className="mt-0.5 text-body text-muted-foreground">
          先放进来，稍后再归属项目。当前不支持 AI 推荐项目。
        </p>
      </header>

      <div className="grid grid-cols-[minmax(360px,0.9fr)_minmax(0,1.1fr)] items-start gap-6">
        <SourceCapture projects={projectOptions} onCreated={invalidateSources} />

        <div className="min-w-0">
          <div className="mb-2 flex h-[34px] items-center gap-1.5" role="tablist" aria-label="来源筛选">
            {([
              ['all', '全部'],
              ['unassigned', '未归属'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={filter === key}
                onClick={() => setFilter(key)}
                className={`flex h-[34px] items-center rounded-md px-2.5 text-body transition-colors ${filter === key ? 'bg-card text-foreground shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
              >
                {label}
              </button>
            ))}
          </div>

          {sources.isLoading ? (
            <div className="divide-y border-t" aria-label="来源加载中">
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
          sources={sources.data ?? []}
          projects={projectOptions}
          onAssign={(id, projectId) => assign.mutate({ id, projectId })}
          onTrigger={(id) => trigger.mutate(id)}
          onDelete={(id) => remove.mutate(id)}
        />
          )}
        </div>
      </div>
    </section>
  )
}
