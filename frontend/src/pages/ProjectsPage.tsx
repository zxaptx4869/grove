import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Archive, CheckCircle2, FolderKanban, Pause, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState } from '@/components/features/EmptyState'
import { createProject, deleteProject, fetchProjects, updateProjectStatus, type ProjectPayload, type ProjectStatus } from '@/lib/api'

const statuses: Array<{ key: ProjectStatus | 'all'; label: string; icon: typeof FolderKanban }> = [
  { key: 'all', label: '全部项目', icon: FolderKanban },
  { key: 'active', label: '进行中', icon: CheckCircle2 },
  { key: 'paused', label: '暂停', icon: Pause },
  { key: 'completed', label: '已完成', icon: CheckCircle2 },
  { key: 'archived', label: '已归档', icon: Archive },
]

const statusLabels: Record<ProjectStatus, string> = { active: '进行中', paused: '暂停', completed: '已完成', archived: '已归档' }

function statusVariant(status: ProjectStatus) {
  return status === 'active' ? 'default' : status === 'archived' ? 'secondary' : 'outline'
}

export function ProjectsPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<ProjectStatus | 'all'>('all')
  const projects = useQuery({ queryKey: ['projects', filter], queryFn: () => fetchProjects(filter) })
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ProjectPayload | null>(null)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['projects'] })
  const create = useMutation({
    mutationFn: () => createProject({ name: name.trim(), description: description.trim() || null }),
    onSuccess: () => { refresh(); setCreateOpen(false); setName(''); setDescription(''); toast.success('项目已创建') },
    onError: (error) => toast.error(error instanceof Error ? error.message : '创建失败'),
  })
  const changeStatus = useMutation({
    mutationFn: ({ id, status }: { id: number; status: ProjectStatus }) => updateProjectStatus(id, status),
    onSuccess: () => { refresh(); toast.success('项目状态已更新') },
    onError: (error) => toast.error(error instanceof Error ? error.message : '状态更新失败'),
  })
  const remove = useMutation({
    mutationFn: () => deleteProject(deleteTarget!.id),
    onSuccess: () => { refresh(); setDeleteTarget(null); toast.success('项目已删除') },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败'),
  })

  return <div className="mx-auto w-full max-w-6xl space-y-7">
    <header className="flex items-end justify-between gap-4 border-b pb-5">
      <div><p className="text-caption uppercase tracking-[0.16em] text-muted-foreground">Workspace</p><h1 className="mt-1 text-display font-semibold">项目管理</h1><p className="mt-1 text-body-sm text-muted-foreground">按状态查看和继续你的知识整理项目。</p></div>
      <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 size-4" />新建项目</Button>
    </header>
    <div className="flex flex-wrap items-center gap-1 border-b pb-3" role="tablist" aria-label="项目状态筛选">
      {statuses.map(({ key, label, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={filter === key} onClick={() => setFilter(key)} className={`inline-flex items-center gap-2 rounded-md px-3 py-2 text-body-sm transition-colors ${filter === key ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}><Icon className="size-4" />{label}</button>)}
    </div>
    {projects.isLoading ? <div className="space-y-2" aria-label="项目加载中">{[1, 2, 3].map((item) => <div key={item} className="h-16 animate-pulse rounded-md bg-muted" />)}</div> : projects.isError ? <div className="border-l-2 border-destructive px-4 py-3"><p className="text-body-sm">项目列表加载失败，请重试。</p><Button className="mt-3" variant="outline" size="sm" onClick={() => projects.refetch()}>重试</Button></div> : projects.data?.length === 0 ? <EmptyState title={filter === 'all' ? '还没有项目' : `没有${statuses.find((item) => item.key === filter)?.label ?? ''}项目`} description="从一个具体目标开始，目录会保持空白，按你的方式逐步建立。" action={<Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 size-4" />创建项目</Button>} /> : <ul className="divide-y border-y">{projects.data?.map((project) => <li key={project.id} className="group flex items-center gap-4 py-4"><div className="flex size-10 shrink-0 items-center justify-center rounded-md bg-muted"><FolderKanban className="size-5 text-muted-foreground" /></div><div className="min-w-0 flex-1"><Link className="font-medium hover:underline" to={`/projects/${project.id}`}>{project.name}</Link><p className="mt-1 truncate text-body-sm text-muted-foreground">{project.description || '尚未填写项目目标与背景'} · {project.node_count} 个目录节点</p></div><Badge variant={statusVariant(project.status)}>{statusLabels[project.status]}</Badge><div className="flex items-center gap-1 opacity-70 group-hover:opacity-100"><Button asChild size="sm" variant="outline"><Link to={`/projects/${project.id}`}>进入项目</Link></Button><select aria-label={`${project.name} 状态`} className="h-9 rounded-md border bg-background px-2 text-body-sm" value={project.status} disabled={changeStatus.isPending} onChange={(event) => changeStatus.mutate({ id: project.id, status: event.target.value as ProjectStatus })}>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><Button aria-label={`删除 ${project.name}`} title="删除项目" size="icon" variant="ghost" className="text-destructive" onClick={() => setDeleteTarget(project)}><Trash2 className="size-4" /></Button></div></li>)}</ul>}

    <Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>新建项目</DialogTitle><DialogDescription>项目会从空目录开始，你可以手动建立结构或稍后进入 AI 共创入口。</DialogDescription></DialogHeader><div className="space-y-4"><div className="space-y-1.5"><label htmlFor="project-name" className="text-body-sm font-medium">项目名称</label><Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：房子装修" /></div><div className="space-y-1.5"><label htmlFor="project-description" className="text-body-sm font-medium">目标与背景（可选）</label><Textarea id="project-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="你想完成什么？已有怎样的背景？" rows={4} /></div></div><DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>{create.isPending ? '创建中…' : '创建项目'}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>删除项目</DialogTitle><DialogDescription>将删除「{deleteTarget?.name}」及其全部目录节点，此操作不可撤销。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setDeleteTarget(null)}>取消</Button><Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 className="mr-2 size-4" />{remove.isPending ? '删除中…' : '确认删除'}</Button></DialogFooter></DialogContent></Dialog>
  </div>
}
