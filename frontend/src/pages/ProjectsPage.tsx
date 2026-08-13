import { useState } from 'react'
import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, FolderKanban, MoreHorizontal, Plus, Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { EmptyState } from '@/components/features/EmptyState'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  createProject,
  deleteProject,
  fetchProjects,
  updateProjectStatus,
  type ProjectPayload,
  type ProjectStatus,
} from '@/lib/api'

const STATUSES: Array<{ key: ProjectStatus; label: string }> = [
  { key: 'active', label: '进行中' },
  { key: 'paused', label: '暂停' },
  { key: 'completed', label: '已完成' },
  { key: 'archived', label: '已归档' },
]

const STATUS_LABELS = Object.fromEntries(STATUSES.map(({ key, label }) => [key, label])) as Record<ProjectStatus, string>

function statusClass(status: ProjectStatus) {
  if (status === 'active') return 'border-brand/20 bg-brand-soft text-brand'
  if (status === 'completed') return 'border-confirmed/20 bg-confirmed-soft text-confirmed'
  return 'border-border bg-muted/70 text-muted-foreground'
}

export function ProjectsPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<ProjectStatus>('active')
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ProjectPayload | null>(null)
  const [actionError, setActionError] = useState('')

  const projectQueries = useQueries({
    queries: STATUSES.map(({ key }) => ({
      queryKey: ['projects', key],
      queryFn: () => fetchProjects(key),
      staleTime: 30_000,
    })),
  })
  const activeIndex = STATUSES.findIndex(({ key }) => key === filter)
  const currentQuery = projectQueries[activeIndex]
  const projects = currentQuery.data ?? []
  const isInitialLoading = projectQueries.some((query) => query.isLoading)
  const hasLoadError = projectQueries.some((query) => query.isError)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['projects'] })
  const create = useMutation({
    mutationFn: () => createProject({ name: name.trim(), description: description.trim() || null }),
    onSuccess: () => {
      refresh()
      setCreateOpen(false)
      setName('')
      setDescription('')
      setActionError('')
      setFilter('active')
      toast.success('项目已创建')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '创建失败，请重试'),
  })
  const changeStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: ProjectStatus }) => updateProjectStatus(id, status),
    onSuccess: () => {
      refresh()
      setActionError('')
      toast.success('项目状态已更新')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '状态更新失败，请重试'),
  })
  const remove = useMutation({
    mutationFn: () => deleteProject(deleteTarget!.id),
    onSuccess: () => {
      refresh()
      setDeleteTarget(null)
      setActionError('')
      toast.success('项目已删除')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '删除失败，请重试'),
  })

  function openCreate() {
    setActionError('')
    setCreateOpen(true)
  }

  return (
    <section className="mx-auto w-full max-w-[1040px]">
      <header className="mb-5 flex items-start justify-between gap-6">
        <div>
          <h1 className="text-display font-semibold">项目</h1>
          <p className="mt-1 text-body-sm text-muted-foreground">按生命周期管理知识整理项目。</p>
        </div>
        <Button onClick={openCreate}><Plus />新建项目</Button>
      </header>

      <div className="mb-2 flex items-center gap-1 border-b pb-2" role="tablist" aria-label="项目状态筛选">
        {STATUSES.map(({ key, label }, index) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={filter === key}
            onClick={() => setFilter(key)}
            className={`flex h-8 items-center gap-1.5 rounded-md px-3 text-body-sm transition-colors ${filter === key ? 'bg-foreground font-medium text-white' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
          >
            {label}
            <span className={`text-caption ${filter === key ? 'text-white/70' : 'text-muted-foreground/70'}`}>{projectQueries[index].data?.length ?? '–'}</span>
          </button>
        ))}
      </div>

      {actionError && !createOpen && !deleteTarget ? (
        <div role="alert" className="mb-2 border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div>
      ) : null}

      {isInitialLoading ? (
        <div className="divide-y" aria-label="项目加载中">
          {[1, 2, 3].map((item) => <div key={item} className="h-[66px] animate-pulse bg-muted/50" />)}
        </div>
      ) : hasLoadError ? (
        <div className="border-l-2 border-destructive px-4 py-4">
          <p className="text-body-sm">项目列表加载失败，请重试。</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => projectQueries.forEach((query) => query.refetch())}>重试</Button>
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          title={`没有${STATUS_LABELS[filter]}项目`}
          description={filter === 'active' ? '新项目会从空目录开始，你可以逐步建立自己的结构。' : '项目状态变化后会显示在这里。'}
          action={filter === 'active' ? <Button onClick={openCreate}><Plus />创建项目</Button> : undefined}
        />
      ) : (
        <ul className="divide-y" aria-label={`${STATUS_LABELS[filter]}项目`}>
          {projects.map((project) => (
            <li key={project.id} className="group flex min-h-[66px] items-center gap-3 px-1 py-2">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted"><FolderKanban className="size-4 text-muted-foreground" /></span>
              <div className="min-w-0 flex-1">
                <Link className="text-body-sm font-medium hover:text-brand" to={`/projects/${project.id}`}>{project.name}</Link>
                <p className="mt-0.5 truncate text-caption text-muted-foreground">{project.description || '尚未填写目标与背景'} · {project.node_count} 个目录节点</p>
              </div>
              <Badge variant="outline" className={statusClass(project.status)}>{STATUS_LABELS[project.status]}</Badge>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button asChild size="icon-sm" variant="ghost" aria-label={`进入 ${project.name}`}><Link to={`/projects/${project.id}`}><ArrowRight /></Link></Button>
                </TooltipTrigger>
                <TooltipContent>进入项目</TooltipContent>
              </Tooltip>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon-sm" variant="ghost" aria-label={`${project.name} 更多操作`}><MoreHorizontal /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuLabel>项目状态</DropdownMenuLabel>
                  <DropdownMenuRadioGroup
                    value={project.status}
                    onValueChange={(status) => changeStatus.mutate({ id: project.id, status: status as ProjectStatus })}
                  >
                    {STATUSES.map(({ key, label }) => <DropdownMenuRadioItem key={key} value={key} disabled={changeStatus.isPending}>{label}</DropdownMenuRadioItem>)}
                  </DropdownMenuRadioGroup>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem variant="destructive" onSelect={() => { setActionError(''); setDeleteTarget(project) }}><Trash2 />删除项目</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={createOpen} onOpenChange={(open) => { setCreateOpen(open); if (!open) setActionError('') }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>项目会从空目录开始，目标与背景可以稍后补充。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}
            <div className="space-y-1.5"><label htmlFor="project-name" className="text-body-sm font-medium">项目名称</label><Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：房子装修" autoFocus /></div>
            <div className="space-y-1.5"><label htmlFor="project-description" className="text-body-sm font-medium">目标与背景（可选）</label><Textarea id="project-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="你想完成什么？已有怎样的背景？" rows={4} /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? '创建中…' : '创建项目'}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => { if (!open) { setDeleteTarget(null); setActionError('') } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>删除项目</DialogTitle><DialogDescription>将删除「{deleteTarget?.name}」及其全部目录节点，此操作不可撤销。</DialogDescription></DialogHeader>
          {actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}
          <DialogFooter><Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button><Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 />{remove.isPending ? '删除中…' : '确认删除'}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
