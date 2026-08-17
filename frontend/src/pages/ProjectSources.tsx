import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'

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

/** 项目内「采集与来源」视图。 */
export function ProjectSources({ projectId }: { projectId: number }) {
  const projects = useQuery({
    queryKey: [...queryKeys.projects, 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))).flat(),
    staleTime: 30_000,
  })
  const sources = useQuery({
    queryKey: [...queryKeys.sources, 'project', projectId],
    queryFn: () => fetchSources({ projectId }),
    staleTime: 0,
    refetchInterval: (query) =>
      query.state.data?.some(
        (source) => source.status === 'waiting' || source.status === 'processing',
      )
        ? 1500
        : false,
  })

  const assign = useGroveMutation({
    mutationFn: ({ id, projectId: targetId }: { id: number; projectId: number | null }) =>
      updateSource(id, { project_id: targetId }),
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
    <div>
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
          sources={sources.data ?? []}
          projects={projectOptions}
          onAssign={(id, targetId) => assign.mutate({ id, projectId: targetId })}
          onTrigger={(id) => trigger.mutate(id)}
          onDelete={(id) => remove.mutate(id)}
        />
      )}
    </div>
  )
}
