import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  FolderPlus,
  FolderTree,
  MoreHorizontal,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { NodeTree } from '@/components/features/NodeTree'
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  createNode,
  deleteNode,
  deleteProject,
  fetchProjects,
  fetchProjectTree,
  reorderNodes,
  updateNode,
  updateProject,
  updateProjectStatus,
  type ProjectStatus,
  type TreeNodePayload,
} from '@/lib/api'

const PROJECT_STATUSES: Array<{ key: ProjectStatus; label: string }> = [
  { key: 'active', label: '进行中' },
  { key: 'paused', label: '暂停' },
  { key: 'completed', label: '已完成' },
  { key: 'archived', label: '已归档' },
]

interface NodeFormState {
  mode: 'create' | 'edit'
  parent: TreeNodePayload | null
  node: TreeNodePayload | null
}

function findNodeWithPath(nodes: readonly TreeNodePayload[], targetId: number, path: TreeNodePayload[] = []): TreeNodePayload[] | null {
  for (const node of nodes) {
    const nextPath = [...path, node]
    if (node.id === targetId) return nextPath
    const found = findNodeWithPath(node.children, targetId, nextPath)
    if (found) return found
  }
  return null
}

function flattenNodes(nodes: readonly TreeNodePayload[], depth = 0): Array<{ node: TreeNodePayload; depth: number }> {
  return nodes.flatMap((node) => [{ node, depth }, ...flattenNodes(node.children, depth + 1)])
}

function NodeFormDialog({
  state,
  onClose,
  onSubmit,
  isPending,
}: {
  state: NodeFormState | null
  onClose: () => void
  onSubmit: (values: { name: string; description: string }) => void
  isPending: boolean
}) {
  const [name, setName] = useState(state?.mode === 'edit' ? state.node?.name ?? '' : '')
  const [description, setDescription] = useState(state?.mode === 'edit' ? state.node?.description ?? '' : '')

  return (
    <Dialog open={state !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {state ? (
          <>
            <DialogHeader>
              <DialogTitle>{state.mode === 'edit' ? '编辑目录节点' : '创建目录节点'}</DialogTitle>
              <DialogDescription>{state.mode === 'edit' ? '修改节点名称与说明。' : state.parent ? `在「${state.parent.name}」下创建子节点。` : '创建一个根级目录节点。'}</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-1.5"><label htmlFor="node-name" className="text-body-sm font-medium">名称</label><Input id="node-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="目录名称" autoFocus /></div>
              <div className="space-y-1.5"><label htmlFor="node-description" className="text-body-sm font-medium">说明（可选）</label><Textarea id="node-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这个节点用于整理什么" rows={3} /></div>
            </div>
            <DialogFooter><Button variant="outline" onClick={onClose}>取消</Button><Button disabled={!name.trim() || isPending} onClick={() => onSubmit({ name: name.trim(), description: description.trim() })}>{isPending ? '保存中…' : '保存'}</Button></DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

export function ProjectPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const projects = useQuery({
    queryKey: ['projects', 'all-statuses'],
    queryFn: async () => (await Promise.all(PROJECT_STATUSES.map(({ key }) => fetchProjects(key)))).flat(),
    enabled: Number.isFinite(id),
    staleTime: 30_000,
  })
  const tree = useQuery({
    queryKey: ['project-tree', id],
    queryFn: () => fetchProjectTree(id),
    enabled: Number.isFinite(id),
  })
  const project = projects.data?.find((item) => item.id === id)
  const nodes = tree.data ?? []

  const [nodeForm, setNodeForm] = useState<NodeFormState | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [deleteNodeTarget, setDeleteNodeTarget] = useState<TreeNodePayload | null>(null)
  const [moveTarget, setMoveTarget] = useState<TreeNodePayload | null>(null)
  const [moveParentId, setMoveParentId] = useState<number | null>(null)
  const [editProjectOpen, setEditProjectOpen] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [actionError, setActionError] = useState('')

  const invalidateTree = () => queryClient.invalidateQueries({ queryKey: ['project-tree', id] })
  const invalidateProjects = () => queryClient.invalidateQueries({ queryKey: ['projects'] })

  const create = useMutation({
    mutationFn: ({ parentId, name, description }: { parentId: number | null; name: string; description: string }) => createNode(id, { parent_id: parentId, name, description: description || null }),
    onSuccess: () => { invalidateTree(); invalidateProjects(); setNodeForm(null); setActionError(''); toast.success('目录节点已创建') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '创建失败，请重试'),
  })
  const update = useMutation({
    mutationFn: ({ nodeId, name, description }: { nodeId: number; name: string; description: string }) => updateNode(id, nodeId, { name, description: description || null }),
    onSuccess: () => { invalidateTree(); setNodeForm(null); setActionError(''); toast.success('目录节点已更新') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '更新失败，请重试'),
  })
  const removeNode = useMutation({
    mutationFn: (nodeId: number) => deleteNode(id, nodeId),
    onSuccess: () => { invalidateTree(); invalidateProjects(); setDeleteNodeTarget(null); setSelectedId(null); setActionError(''); toast.success('目录节点已删除') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '删除失败，请重试'),
  })
  const reorder = useMutation({
    mutationFn: ({ parentId, orderedIds }: { parentId: number | null; orderedIds: number[] }) => reorderNodes(id, parentId, orderedIds),
    onSuccess: () => { invalidateTree(); setActionError('') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '排序失败，请重试'),
  })
  const move = useMutation({
    mutationFn: () => updateNode(id, moveTarget!.id, { parent_id: moveParentId }),
    onSuccess: () => { invalidateTree(); setMoveTarget(null); setActionError(''); toast.success('目录节点已移动') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '移动失败，请重试'),
  })
  const editProject = useMutation({
    mutationFn: () => updateProject(id, { name: projectName.trim(), description: projectDescription.trim() || null }),
    onSuccess: () => { invalidateProjects(); setEditProjectOpen(false); setActionError(''); toast.success('项目信息已更新') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '保存失败，请重试'),
  })
  const changeStatus = useMutation({
    mutationFn: (status: ProjectStatus) => updateProjectStatus(id, status),
    onSuccess: () => { invalidateProjects(); setActionError(''); toast.success('项目状态已更新') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '状态更新失败，请重试'),
  })
  const removeProject = useMutation({
    mutationFn: () => deleteProject(id),
    onSuccess: () => { invalidateProjects(); navigate('/projects', { replace: true }); toast.success('项目已删除') },
    onError: (error) => setActionError(error instanceof Error ? error.message : '删除失败，请重试'),
  })

  const selectedPath = selectedId ? findNodeWithPath(nodes, selectedId) : null
  const selectedNode = selectedPath?.at(-1) ?? null

  function openAddNode(parent: TreeNodePayload | null) {
    setActionError('')
    setNodeForm({ mode: 'create', parent, node: null })
  }

  function openProjectEdit() {
    if (!project) return
    setProjectName(project.name)
    setProjectDescription(project.description ?? '')
    setActionError('')
    setEditProjectOpen(true)
  }

  if (!Number.isFinite(id)) return <div role="alert" className="text-body-sm text-destructive">项目地址无效。</div>
  if (projects.isLoading || tree.isLoading) return <div className="space-y-5" aria-label="项目加载中"><div className="h-16 animate-pulse bg-muted/60" /><div className="h-[420px] animate-pulse bg-muted/40" /></div>
  if (projects.isError || tree.isError) return <div className="border-l-2 border-destructive px-4 py-3"><p className="text-body-sm">项目工作台加载失败，请重试。</p><Button className="mt-3" variant="outline" size="sm" onClick={() => { projects.refetch(); tree.refetch() }}>重试</Button></div>
  if (!project) return <div className="border-l-2 border-destructive px-4 py-3 text-body-sm">项目不存在，或你无权访问该项目。</div>

  return (
    <section id="project-overview" className="mx-auto w-full max-w-[1120px]">
      <header className="mb-6 flex items-start justify-between gap-6 border-b pb-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-display font-semibold">{project.name}</h1>
            <Badge variant="outline" className="shrink-0">{PROJECT_STATUSES.find(({ key }) => key === project.status)?.label}</Badge>
          </div>
          <p className="mt-1 max-w-2xl text-body-sm text-muted-foreground">{project.description || '尚未填写项目目标与背景'}</p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button size="icon-sm" variant="ghost" aria-label="项目更多操作"><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={openProjectEdit}><Pencil />编辑项目信息</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={() => { setActionError(''); setDeleteProjectOpen(true) }}><Trash2 />删除项目</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      {actionError && !nodeForm && !deleteNodeTarget && !moveTarget && !editProjectOpen && !deleteProjectOpen ? <div role="alert" className="mb-4 border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}

      <div className="grid min-h-[520px] grid-cols-[minmax(0,1fr)_268px] gap-8">
        <section id="project-directory" className="min-w-0">
          <div className="mb-3 flex h-9 items-center justify-between">
            <div><h2 className="text-title font-semibold">项目目录</h2><p className="text-caption text-muted-foreground">{project.node_count} 个节点</p></div>
            {nodes.length > 0 ? <Button size="sm" onClick={() => openAddNode(null)}><Plus />根节点</Button> : null}
          </div>

          {nodes.length === 0 ? (
            <div className="flex min-h-[400px] items-center justify-center border-y">
              <div className="max-w-sm text-center">
                <span className="mx-auto flex size-11 items-center justify-center rounded-md bg-muted"><FolderTree className="size-5 text-muted-foreground" /></span>
                <h3 className="mt-4 text-title font-semibold">从空目录开始</h3>
                <p className="mt-1 text-body-sm leading-6 text-muted-foreground">按你的理解方式建立目录，后续可随时编辑、移动和排序。</p>
                <div className="mt-5 flex justify-center gap-2"><Button onClick={() => openAddNode(null)}><FolderPlus />手动创建</Button><Button variant="outline" onClick={() => setAiOpen(true)}><Sparkles />与 AI 共创目录</Button></div>
              </div>
            </div>
          ) : (
            <div className="grid min-h-[430px] grid-cols-[300px_minmax(0,1fr)] border-y">
              <div className="border-r py-3 pr-3">
                <NodeTree
                  nodes={nodes}
                  selectedId={selectedId}
                  onSelect={(node) => setSelectedId(node.id)}
                  callbacks={{
                    onAddChild: openAddNode,
                    onRename: (node) => { setActionError(''); setNodeForm({ mode: 'edit', parent: null, node }) },
                    onMove: (node) => { setActionError(''); setMoveTarget(node); setMoveParentId(null) },
                    onDelete: (node) => { setActionError(''); setDeleteNodeTarget(node) },
                    onReorder: (parentId, orderedIds) => reorder.mutate({ parentId, orderedIds }),
                  }}
                />
              </div>
              <div className="p-6">
                {selectedNode ? (
                  <div>
                    <p className="text-caption text-muted-foreground">{selectedPath?.map((node) => node.name).join(' / ')}</p>
                    <h3 className="mt-2 text-heading font-semibold">{selectedNode.name}</h3>
                    <p className="mt-2 text-body-sm leading-6 text-muted-foreground">{selectedNode.description || '尚未填写节点说明。'}</p>
                    <Button className="mt-5" variant="outline" size="sm" onClick={() => setNodeForm({ mode: 'edit', parent: null, node: selectedNode })}><Pencil />编辑节点</Button>
                  </div>
                ) : (
                  <div className="flex min-h-[360px] items-center justify-center text-center"><div><FolderTree className="mx-auto size-5 text-muted-foreground" /><p className="mt-2 text-body-sm text-muted-foreground">选择一个目录节点查看说明</p></div></div>
                )}
              </div>
            </div>
          )}
        </section>

        <aside className="border-l pl-6">
          <section>
            <div className="flex items-center justify-between"><h2 className="text-body-sm font-semibold">项目状态</h2><Button size="icon-xs" variant="ghost" onClick={openProjectEdit} aria-label="编辑项目信息"><Pencil /></Button></div>
            <div className="mt-3 grid grid-cols-2 gap-1" role="group" aria-label="项目状态">
              {PROJECT_STATUSES.map(({ key, label }) => <button key={key} type="button" disabled={changeStatus.isPending} onClick={() => changeStatus.mutate(key)} className={`h-8 rounded-md border text-caption transition-colors disabled:opacity-50 ${project.status === key ? 'border-brand/30 bg-brand-soft font-medium text-brand' : 'bg-white text-muted-foreground hover:bg-muted'}`}>{label}</button>)}
            </div>
          </section>
          <section className="mt-6 border-t pt-5">
            <h2 className="text-body-sm font-semibold">目标与背景</h2>
            <p className="mt-2 text-body-sm leading-6 text-muted-foreground">{project.description || '尚未填写。'}</p>
            <Button className="mt-3" size="sm" variant="ghost" onClick={openProjectEdit}><Pencil />编辑</Button>
          </section>
          <section className="mt-6 border-t pt-5">
            <h2 className="text-body-sm font-semibold">目录共创</h2>
            <p className="mt-2 text-caption leading-5 text-muted-foreground">从项目目标出发，与 AI 一起讨论目录结构。</p>
            <Button className="mt-3" size="sm" variant="outline" onClick={() => setAiOpen(true)}><Sparkles />与 AI 共创目录</Button>
          </section>
        </aside>
      </div>

      <NodeFormDialog
        key={nodeForm ? `${nodeForm.mode}-${nodeForm.node?.id ?? nodeForm.parent?.id ?? 'root'}` : 'closed'}
        state={nodeForm}
        onClose={() => { setNodeForm(null); setActionError('') }}
        onSubmit={(values) => {
          if (!nodeForm) return
          if (nodeForm.mode === 'edit' && nodeForm.node) update.mutate({ nodeId: nodeForm.node.id, ...values })
          else create.mutate({ parentId: nodeForm.parent?.id ?? null, ...values })
        }}
        isPending={create.isPending || update.isPending}
      />

      <Dialog open={deleteNodeTarget !== null} onOpenChange={(open) => { if (!open) { setDeleteNodeTarget(null); setActionError('') } }}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>删除目录节点</DialogTitle><DialogDescription>将删除「{deleteNodeTarget?.name}」及其全部子节点，此操作不可撤销。</DialogDescription></DialogHeader>{actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}<DialogFooter><Button variant="outline" onClick={() => setDeleteNodeTarget(null)}>取消</Button><Button variant="destructive" disabled={removeNode.isPending} onClick={() => deleteNodeTarget && removeNode.mutate(deleteNodeTarget.id)}><Trash2 />{removeNode.isPending ? '删除中…' : '确认删除'}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={moveTarget !== null} onOpenChange={(open) => { if (!open) { setMoveTarget(null); setActionError('') } }}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>移动目录节点</DialogTitle><DialogDescription>选择「{moveTarget?.name}」的新位置。</DialogDescription></DialogHeader>{actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}<select aria-label="新父节点" className="h-10 rounded-md border bg-background px-3 text-body-sm" value={moveParentId ?? ''} onChange={(event) => setMoveParentId(event.target.value ? Number(event.target.value) : null)}><option value="">根目录</option>{flattenNodes(nodes).filter(({ node }) => node.id !== moveTarget?.id && !findNodeWithPath(moveTarget?.children ?? [], node.id)).map(({ node, depth }) => <option key={node.id} value={node.id}>{'　'.repeat(depth)}{node.name}</option>)}</select><DialogFooter><Button variant="outline" onClick={() => setMoveTarget(null)}>取消</Button><Button disabled={move.isPending} onClick={() => move.mutate()}>{move.isPending ? '移动中…' : '确认移动'}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={editProjectOpen} onOpenChange={(open) => { setEditProjectOpen(open); if (!open) setActionError('') }}><DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>编辑项目信息</DialogTitle><DialogDescription>目标与背景是一个可选字段。</DialogDescription></DialogHeader>{actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}<div className="space-y-4"><div className="space-y-1.5"><label htmlFor="edit-project-name" className="text-body-sm font-medium">项目名称</label><Input id="edit-project-name" value={projectName} onChange={(event) => setProjectName(event.target.value)} /></div><div className="space-y-1.5"><label htmlFor="edit-project-description" className="text-body-sm font-medium">目标与背景（可选）</label><Textarea id="edit-project-description" value={projectDescription} onChange={(event) => setProjectDescription(event.target.value)} rows={5} /></div></div><DialogFooter><Button variant="outline" onClick={() => setEditProjectOpen(false)}>取消</Button><Button disabled={!projectName.trim() || editProject.isPending} onClick={() => editProject.mutate()}>{editProject.isPending ? '保存中…' : '保存'}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={deleteProjectOpen} onOpenChange={(open) => { setDeleteProjectOpen(open); if (!open) setActionError('') }}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>删除项目</DialogTitle><DialogDescription>将删除「{project.name}」及其全部目录节点，此操作不可撤销。</DialogDescription></DialogHeader>{actionError ? <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">{actionError}</div> : null}<DialogFooter><Button variant="outline" onClick={() => setDeleteProjectOpen(false)}>取消</Button><Button variant="destructive" disabled={removeProject.isPending} onClick={() => removeProject.mutate()}><Trash2 />{removeProject.isPending ? '删除中…' : '确认删除'}</Button></DialogFooter></DialogContent></Dialog>

      <Dialog open={aiOpen} onOpenChange={setAiOpen}><DialogContent className="sm:max-w-md"><DialogHeader><DialogTitle>与 AI 共创目录</DialogTitle><DialogDescription>入口已就位。Directory Agent 不在本轮实现范围内，目前不会生成或修改任何目录节点。</DialogDescription></DialogHeader><DialogFooter><Button onClick={() => setAiOpen(false)}>知道了</Button></DialogFooter></DialogContent></Dialog>
    </section>
  )
}
