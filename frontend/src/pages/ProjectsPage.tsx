import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
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
import { Separator } from '@/components/ui/separator'
import { EmptyState } from '@/components/features/EmptyState'
import {
  createProject,
  deleteProject,
  fetchProjects,
  renameProject,
  type ProjectPayload,
} from '@/lib/api'

const PROJECTS_QUERY_KEY = ['projects'] as const

/** 项目管理页：列表、新建（模板选择）、重命名、删除。 */
export function ProjectsPage() {
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: PROJECTS_QUERY_KEY, queryFn: fetchProjects })

  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newTemplate, setNewTemplate] = useState<'empty' | 'decoration'>('empty')
  const [renameTarget, setRenameTarget] = useState<ProjectPayload | null>(null)
  const [renameName, setRenameName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<ProjectPayload | null>(null)

  const create = useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
      setCreateOpen(false)
      setNewName('')
      setNewTemplate('empty')
      toast.success('项目已创建')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '创建失败'),
  })

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => renameProject(id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
      setRenameTarget(null)
      toast.success('已重命名')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '重命名失败'),
  })

  const remove = useMutation({
    mutationFn: (id: number) => deleteProject(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
      setDeleteTarget(null)
      toast.success('项目已删除')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败'),
  })

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-heading font-bold">项目管理</h1>
          <p className="text-body-sm text-muted-foreground">目录是知识库的心智模型，从这里开始组织。</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}>新建项目</Button>
      </div>

      {projects.isLoading ? (
        <p className="text-body-sm text-muted-foreground">加载中…</p>
      ) : projects.data && projects.data.length === 0 ? (
        <EmptyState
          title="还没有项目"
          description="创建一个项目，可选择装修模板或从空目录开始。"
          action={<Button onClick={() => setCreateOpen(true)}>创建第一个项目</Button>}
        />
      ) : (
        <ul className="divide-y rounded-lg border">
          {(projects.data ?? []).map((project) => (
            <li key={project.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <Link
                  to={`/projects/${project.id}`}
                  className="font-medium hover:underline"
                >
                  {project.name}
                </Link>
                <div className="mt-1 flex items-center gap-2">
                  <Badge variant="outline">{project.template === 'decoration' ? '装修模板' : '空目录'}</Badge>
                  <span className="text-caption text-muted-foreground">
                    {project.node_count} 个节点
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button asChild size="sm" variant="outline">
                  <Link to={`/projects/${project.id}`}>打开</Link>
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setRenameTarget(project)
                    setRenameName(project.name)
                  }}
                >
                  重命名
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-error hover:text-error"
                  onClick={() => setDeleteTarget(project)}
                >
                  删除
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* 新建项目 */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>新建项目</DialogTitle>
            <DialogDescription>选择目录模板，装修模板会预置 149 个知识节点。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="project-name" className="text-body-sm font-medium">
                项目名称
              </label>
              <Input
                id="project-name"
                placeholder="例如：房子装修"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="project-template" className="text-body-sm font-medium">
                目录模板
              </label>
              <select
                id="project-template"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                value={newTemplate}
                onChange={(event) =>
                  setNewTemplate(event.target.value as 'empty' | 'decoration')
                }
              >
                <option value="empty">空目录</option>
                <option value="decoration">装修模板（149 节点）</option>
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button
              disabled={newName.trim().length === 0 || create.isPending}
              onClick={() =>
                create.mutate({ name: newName.trim(), template: newTemplate })
              }
            >
              {create.isPending ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 重命名 */}
      <Dialog open={renameTarget !== null} onOpenChange={(open) => !open && setRenameTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>重命名项目</DialogTitle>
          </DialogHeader>
          <Input
            value={renameName}
            onChange={(event) => setRenameName(event.target.value)}
            placeholder="项目名称"
          />
          <DialogFooter>
            <Button
              disabled={renameName.trim().length === 0 || rename.isPending}
              onClick={() =>
                renameTarget && rename.mutate({ id: renameTarget.id, name: renameName.trim() })
              }
            >
              {rename.isPending ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除项目</DialogTitle>
            <DialogDescription>
              将删除「{deleteTarget?.name}」及其全部目录节点，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <Separator />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleteTarget && remove.mutate(deleteTarget.id)}
            >
              {remove.isPending ? '删除中…' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
