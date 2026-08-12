import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { toast } from 'sonner'
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
import { Textarea } from '@/components/ui/textarea'
import { NodeTree } from '@/components/features/NodeTree'
import {
  createNode,
  deleteNode,
  fetchProjectTree,
  fetchProjects,
  reorderNodes,
  updateNode,
  type TreeNodePayload,
} from '@/lib/api'

interface NodeFormState {
  mode: 'create' | 'edit'
  parent: TreeNodePayload | null
  node: TreeNodePayload | null
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
  // 组件通过 key 随 state 重挂载，初始值即预填值
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

/** 项目页：目录树查看与维护。 */
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

  function handleNodeSubmit(values: { name: string; description: string }) {
    if (!nodeForm) return
    if (nodeForm.mode === 'edit' && nodeForm.node) {
      update.mutate({ nodeId: nodeForm.node.id, ...values })
    } else {
      create.mutate({ parentId: nodeForm.parent?.id ?? null, ...values })
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <Link
            to="/projects"
            className="text-body-sm text-muted-foreground hover:text-foreground"
          >
            ← 返回项目列表
          </Link>
          <h1 className="text-heading font-bold">{project?.name ?? '项目'}</h1>
        </div>
        <Button onClick={() => setNodeForm({ mode: 'create', parent: null, node: null })}>
          添加根节点
        </Button>
      </div>

      {tree.isLoading ? (
        <p className="text-body-sm text-muted-foreground">加载中…</p>
      ) : tree.isError ? (
        <p className="text-body-sm text-error">目录加载失败：{(tree.error as Error).message}</p>
      ) : (
        <NodeTree
          nodes={tree.data ?? []}
          callbacks={{
            onAddChild: (parent) => setNodeForm({ mode: 'create', parent, node: null }),
            onRename: (node) => setNodeForm({ mode: 'edit', parent: null, node }),
            onDelete: (node) => setDeleteTarget(node),
            onReorder: (parentId, orderedIds) => reorder.mutate({ parentId, orderedIds }),
          }}
        />
      )}

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
    </section>
  )
}
