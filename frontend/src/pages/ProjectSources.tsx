import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { SourceList } from '@/components/features/SourceList'
import { Button } from '@/components/ui/button'
import {
  deleteSource,
  fetchProjects,
  fetchSources,
  updateSource,
  type ProjectStatus,
} from '@/lib/api'

const PROJECT_STATUSES: ProjectStatus[] = ['active', 'paused', 'completed', 'archived']

/** 项目内「采集与来源」视图。 */
export function ProjectSources({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient()
  const projects = useQuery({
    queryKey: ['projects', 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))).flat(),
    staleTime: 30_000,
  })
  const sources = useQuery({
    queryKey: ['sources', 'project', projectId],
    queryFn: () => fetchSources({ projectId }),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['sources'] })
  const assign = useMutation({
    mutationFn: ({ id, projectId: targetId }: { id: number; projectId: number | null }) =>
      updateSource(id, { project_id: targetId }),
    onSuccess: () => {
      invalidate()
      toast.success('来源归属已更新')
    },
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '更新失败，请重试'),
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteSource(id),
    onSuccess: () => {
      invalidate()
      toast.success('来源已删除')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败，请重试'),
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
          onDelete={(id) => remove.mutate(id)}
        />
      )}
    </div>
  )
}
