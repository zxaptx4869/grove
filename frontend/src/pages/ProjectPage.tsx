import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Separator } from '@/components/ui/separator'
import { EmptyState } from '@/components/features/EmptyState'
import { NodeTree } from '@/components/features/NodeTree'
import {
  createNode,
  deleteNode,
  deleteProject,
  fetchProjectTree,
  fetchProjects,
  renameProject,
  reorderNodes,
  updateNode,
  type ProjectPayload,
  type TreeNodePayload,
} from '@/lib/api'

interface NodeFormState {
  mode: 'create' | 'edit'
  parent: TreeNodePayload | null
  node: TreeNodePayload | null
}

function findNodeWithPath(
  nodes: readonly TreeNodePayload[],
  targetId: number,
  path: TreeNodePayload[] = [],
): TreeNodePayload[] | null {
  for (const node of nodes) {
    const nextPath = [...path, node]
    if (node.id === targetId) return nextPath
    const found = findNodeWithPath(node.children, targetId, nextPath)
    if (found) return found
  }
  return null
}

function countNodes(nodes: readonly TreeNodePayload[]): number {
  return nodes.reduce((sum, node) => sum + 1 + countNodes(node.children), 0)
}

/** 项目重命名对话框。 */
function RenameProjectDialog({
  project,
  onClose,
}: {
  project: ProjectPayload | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(project?.name ?? '')
  const rename = useMutation({
    mutationFn: (nextName: string) => renameProject(project!.id, nextName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      onClose()
      toast.success('项目已重命名')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '重命名失败'),
  })

  return (
    <Dialog open={project !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>重命名项目</DialogTitle>
        </DialogHeader>
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="项目名称"
        />
        <DialogFooter>
          <Button
            disabled={name.trim().length === 0 || rename.isPending}
            onClick={() => rename.mutate(name.trim())}
          >
            {rename.isPending ? '保存中…' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 删除项目确认对话框。 */
function DeleteProjectDialog({
  project,
  onClose,
}: {
  project: ProjectPayload | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => deleteProject(project!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      onClose()
      toast.success('项目已删除')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败'),
  })

  return (
    <Dialog open={project !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>删除项目</DialogTitle>
          <DialogDescription>
            将删除「{project?.name}」及其全部目录节点，此操作不可撤销。
          </DialogDescription>
        </DialogHeader>
        <Separator />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {remove.isPending ? '删除中…' : '确认删除'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 节点创建/编辑对话框（数据驱动，纯表单输入）。 */
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
  const isOpen = state !== null
  const isEdit = state?.mode === 'edit'
  const [name, setName] = useState(
    state?.mode === 'edit' ? state.node?.name ?? '' : '',
  )
  const [description, setDescription] = useState(
    state?.mode === 'edit' ? state.node?.description ?? '' : '',
  )

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {state ? (
          <>
            <DialogHeader>
              <DialogTitle>{isEdit ? '编辑节点' : '添加节点'}</DialogTitle>
              <DialogDescription>
                {isEdit
                  ? '修改节点名称与描述。'
                  : state.parent
                    ? `添加到「${state.parent.name}」下。`
                    : '添加一个根级节点。'}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="node-name" className="text-body-sm font-medium">
                  名称
                </label>
                <Input
                  id="node-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="节点名称"
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="node-description" className="text-body-sm font-medium">
                  描述（可选）
                </label>
                <Textarea
                  id="node-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="补充说明"
                  rows={3}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                disabled={name.trim().length === 0 || isPending}
                onClick={() => onSubmit({ name: name.trim(), description: description.trim() })}
              >
                {isPending ? '保存中…' : '保存'}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

/** 项目页：左侧目录树 + 右侧内容区（布局参考 KnowStruct）。 */
export function ProjectPage() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const queryClient = useQueryClient()

  const tree = useQuery({
    queryKey: ['project-tree', id],
    queryFn: () => fetchProjectTree(id),
    enabled: Number.isFinite(id),
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: fetchProjects })
  const project = projects.data?.find((item) => item.id === id)

  const [nodeForm, setNodeForm] = useState<NodeFormState | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<TreeNodePayload | null>(null)
  const [renameTarget, setRenameTarget] = useState<ProjectPayload | null>(null)
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<ProjectPayload | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [treeOpen, setTreeOpen] = useState(false)

  const invalidateTree = () =>
    queryClient.invalidateQueries({ queryKey: ['project-tree', id] })

  const create = useMutation({
    mutationFn: ({
      parentId,
      name,
      description,
    }: {
      parentId: number | null
      name: string
      description: string
    }) => createNode(id, { name, description: description || null, parent_id: parentId }),
    onSuccess: () => {
      invalidateTree()
      setNodeForm(null)
      toast.success('节点已添加')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '添加失败'),
  })

  const update = useMutation({
    mutationFn: ({
      nodeId,
      name,
      description,
    }: {
      nodeId: number
      name: string
      description: string
    }) => updateNode(id, nodeId, { name, description: description || null }),
    onSuccess: () => {
      invalidateTree()
      setNodeForm(null)
      toast.success('节点已更新')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '更新失败'),
  })

  const remove = useMutation({
    mutationFn: (nodeId: number) => deleteNode(id, nodeId),
    onSuccess: () => {
      invalidateTree()
      setDeleteTarget(null)
      toast.success('节点已删除')
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : '删除失败'),
  })

  const reorder = useMutation({
    mutationFn: ({ parentId, orderedIds }: { parentId: number | null; orderedIds: number[] }) =>
      reorderNodes(id, parentId, orderedIds),
    onSuccess: () => invalidateTree(),
    onError: (error) => toast.error(error instanceof Error ? error.message : '排序失败'),
  })

  const nodes = tree.data ?? []
  const nodeCount = project?.node_count ?? countNodes(nodes)
  const selectedPath = selectedId ? findNodeWithPath(nodes, selectedId) : null
  const selectedNode = selectedPath?.[selectedPath.length - 1] ?? null

  function handleNodeSubmit(values: { name: string; description: string }) {
    if (!nodeForm) return
    if (nodeForm.mode === 'edit' && nodeForm.node) {
      update.mutate({ nodeId: nodeForm.node.id, ...values })
    } else {
      create.mutate({ parentId: nodeForm.parent?.id ?? null, ...values })
    }
  }

  function openAddChild(parent: TreeNodePayload | null) {
    setNodeForm({ mode: 'create', parent, node: null })
    setTreeOpen(false)
  }

  return (
    <section className="space-y-0">
      {/* 项目顶栏 */}
      <header className="-mx-4 mb-4 flex flex-wrap items-center gap-3 border-b px-4 pb-3 md:-mx-6 md:px-6">
        <Link
          to="/projects"
          className="text-body-sm text-muted-foreground hover:text-foreground"
        >
          ← 项目列表
        </Link>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-title font-bold">{project?.name ?? '项目'}</h1>
            <Badge variant="outline">{project?.template === 'decoration' ? '装修模板' : '空目录'}</Badge>
          </div>
          <p className="text-caption text-muted-foreground">{nodeCount} 个目录节点</p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => openAddChild(null)}>
            添加根节点
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => project && setRenameTarget(project)}
          >
            重命名
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-error hover:text-error"
            onClick={() => project && setDeleteProjectTarget(project)}
          >
            删除
          </Button>
        </div>
      </header>

      {/* 移动端：目录开关 */}
      <div className="mb-3 md:hidden">
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => setTreeOpen((value) => !value)}
        >
          {treeOpen ? '收起目录' : '展开目录'}
        </Button>
      </div>

      <div className="flex flex-col gap-6 md:flex-row">
        {/* 左侧：知识目录 */}
        <aside className="md:w-72 md:shrink-0 md:border-r md:pr-4">
          <div
            className={`space-y-2 ${treeOpen ? 'block' : 'hidden'} md:block`}
          >
            <div className="hidden items-center justify-between md:flex">
              <h2 className="text-title font-semibold">知识目录</h2>
              <Button size="sm" variant="ghost" onClick={() => openAddChild(null)}>
                + 根节点
              </Button>
            </div>
            {tree.isLoading ? (
              <p className="text-body-sm text-muted-foreground">加载中…</p>
            ) : tree.isError ? (
              <p className="text-body-sm text-error">目录加载失败</p>
            ) : (
              <NodeTree
                nodes={nodes}
                selectedId={selectedId}
                onSelect={(node) => setSelectedId(node.id)}
                callbacks={{
                  onAddChild: (parent) => openAddChild(parent),
                  onRename: (node) => setNodeForm({ mode: 'edit', parent: null, node }),
                  onDelete: (node) => setDeleteTarget(node),
                  onReorder: (parentId, orderedIds) => reorder.mutate({ parentId, orderedIds }),
                }}
              />
            )}
          </div>
        </aside>

        {/* 右侧：内容区 */}
        <main className="min-w-0 flex-1">
          {selectedNode ? (
            <div className="space-y-4">
              <p className="text-caption text-muted-foreground">
                {project?.name} / {selectedPath?.map((node) => node.name).join(' / ')}
              </p>
              <h2 className="text-heading font-bold">{selectedNode.name}</h2>
              {selectedNode.description ? (
                <p className="text-body text-muted-foreground">{selectedNode.description}</p>
              ) : null}
              <Separator />
              <EmptyState
                title="该节点还没有内容"
                description="后续切片将在此展示节点下的正式记录、采集素材与 AI 候选确认。"
              />
            </div>
          ) : (
            <div className="space-y-6">
              <div className="space-y-1">
                <h2 className="text-heading font-bold">项目总览</h2>
                <p className="text-body-sm text-muted-foreground">
                  目录是知识库的心智模型。左侧选择节点查看详情，或先调整目录结构。
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <EmptyState
                  title="采集箱"
                  description="拖拽、粘贴、上传素材（下一切片）。"
                  action={
                    <Button asChild variant="outline" size="sm">
                      <Link to="/inbox">去采集</Link>
                    </Button>
                  }
                />
                <EmptyState
                  title="候选确认"
                  description="AI 抽取的候选将在此批量采纳或拒绝。"
                />
              </div>
            </div>
          )}
        </main>
      </div>

      <NodeFormDialog
        key={
          nodeForm
            ? nodeForm.mode === 'edit'
              ? `edit-${nodeForm.node?.id ?? 'unknown'}`
              : `create-${nodeForm.parent?.id ?? 'root'}`
            : 'closed'
        }
        state={nodeForm}
        onClose={() => setNodeForm(null)}
        onSubmit={handleNodeSubmit}
        isPending={create.isPending || update.isPending}
      />

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除节点</DialogTitle>
            <DialogDescription>
              将删除「{deleteTarget?.name}」及其全部子节点，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
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

      <RenameProjectDialog
        key={renameTarget?.id ?? 'none'}
        project={renameTarget}
        onClose={() => setRenameTarget(null)}
      />
      <DeleteProjectDialog
        key={deleteProjectTarget?.id ?? 'none'}
        project={deleteProjectTarget}
        onClose={() => setDeleteProjectTarget(null)}
      />
    </section>
  )
}
