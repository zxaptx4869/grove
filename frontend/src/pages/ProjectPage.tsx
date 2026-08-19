import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpen,
  FolderPlus,
  FolderTree,
  LayoutGrid,
  List,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { NodeTree } from '@/components/features/NodeTree'
import { DirectoryTreeSelect } from '@/components/features/DirectoryTreeSelect'
import { EntryCard, EntryList } from '@/components/features/EntryViews'
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
import { CaptureDialog } from '@/components/features/CaptureDialog'
import { DirectoryDraftDialog } from '@/components/features/DirectoryDraftDialog'
import { ProjectContextPanel } from '@/components/features/ProjectContextPanel'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { ProjectSources } from '@/pages/ProjectSources'
import {
  createNode,
  deleteNode,
  deleteProject,
  discardDirectoryDraft,
  fetchDirectoryDraft,
  fetchProjects,
  fetchProjectTree,
  fetchNodeEntries,
  reorderNodes,
  searchEntries,
  updateNode,
  updateProject,
  updateProjectStatus,
  type ProjectStatus,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

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

function descendantEntryCount(node: TreeNodePayload): number {
  return node.children.reduce(
    (sum, child) => sum + child.entry_count + descendantEntryCount(child),
    0,
  )
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
  const [name, setName] = useState(state?.mode === 'edit' ? (state.node?.name ?? '') : '')
  const [description, setDescription] = useState(
    state?.mode === 'edit' ? (state.node?.description ?? '') : '',
  )

  return (
    <Dialog open={state !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        {state ? (
          <>
            <DialogHeader>
              <DialogTitle>{state.mode === 'edit' ? '编辑目录节点' : '创建目录节点'}</DialogTitle>
              <DialogDescription>
                {state.mode === 'edit'
                  ? '修改节点名称与说明。'
                  : state.parent
                    ? `在「${state.parent.name}」下创建子节点。`
                    : '创建一个根级目录节点。'}
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
                  placeholder="目录名称"
                  autoFocus
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="node-description" className="text-body-sm font-medium">
                  说明（可选）
                </label>
                <Textarea
                  id="node-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="这个节点用于整理什么"
                  rows={3}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={onClose}>
                取消
              </Button>
              <Button
                disabled={!name.trim() || isPending}
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

export function ProjectPage() {
  const { projectId } = useParams()
  const [searchParams] = useSearchParams()
  const id = Number(projectId)
  const isDirectoryView = searchParams.get('view') === 'directory'
  const isSourcesView = searchParams.get('view') === 'sources'
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const projects = useQuery({
    queryKey: [...queryKeys.projects, 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map(({ key }) => fetchProjects(key)))).flat(),
    enabled: Number.isFinite(id),
    staleTime: 30_000,
  })
  const tree = useQuery({
    queryKey: queryKeys.projectTree(id),
    queryFn: () => fetchProjectTree(id),
    enabled: Number.isFinite(id),
  })
  const draftQuery = useQuery({
    queryKey: queryKeys.directoryDraft(id),
    queryFn: () => fetchDirectoryDraft(id),
    enabled: Number.isFinite(id),
    retry: false,
  })
  const project = projects.data?.find((item) => item.id === id)
  const nodes = useMemo(() => tree.data ?? [], [tree.data])
  // 只在查询成功态读取草稿：应用/放弃后重查 404 或缓存残留都不应再显示提示条
  const activeDraft = draftQuery.isSuccess ? (draftQuery.data ?? null) : null
  const draftTargetNode = useMemo(() => {
    if (!activeDraft || activeDraft.kind !== 'expand' || activeDraft.target_node_id == null) {
      return null
    }
    const walk = (items: TreeNodePayload[]): TreeNodePayload | null => {
      for (const node of items) {
        if (node.id === activeDraft.target_node_id) return node
        const found = walk(node.children)
        if (found) return found
      }
      return null
    }
    return walk(nodes)
  }, [activeDraft, nodes])

  const [nodeForm, setNodeForm] = useState<NodeFormState | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [deleteNodeTarget, setDeleteNodeTarget] = useState<TreeNodePayload | null>(null)
  const [moveTarget, setMoveTarget] = useState<TreeNodePayload | null>(null)
  const [moveParentId, setMoveParentId] = useState<number | null>(null)
  const moveExcludedIds = useMemo(() => {
    const excluded = new Set<number>()
    if (!moveTarget) return excluded
    const walk = (node: TreeNodePayload) => {
      excluded.add(node.id)
      node.children.forEach(walk)
    }
    walk(moveTarget)
    return excluded
  }, [moveTarget])
  const moveNodeFilter = useCallback(
    (node: TreeNodePayload) => !moveExcludedIds.has(node.id),
    [moveExcludedIds],
  )
  const [editProjectOpen, setEditProjectOpen] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [deleteProjectOpen, setDeleteProjectOpen] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [expandTarget, setExpandTarget] = useState<TreeNodePayload | null>(null)
  const [overwriteNode, setOverwriteNode] = useState<TreeNodePayload | null>(null)
  const [checkingDraft, setCheckingDraft] = useState(false)
  const [captureOpen, setCaptureOpen] = useState(false)
  const [actionError, setActionError] = useState('')
  const [viewMode, setViewMode] = useState<'card' | 'list'>(() =>
    Number.isFinite(id) && window.localStorage.getItem(`grove.view-mode.${id}`) === 'list'
      ? 'list'
      : 'card',
  )
  const [scope, setScope] = useState<'direct' | 'descendants'>('direct')
  const [searchInput, setSearchInput] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')

  function submitSearch() {
    setSubmittedSearch(searchInput.trim())
  }

  const create = useGroveMutation({
    mutationFn: ({
      parentId,
      name,
      description,
    }: {
      parentId: number | null
      name: string
      description: string
    }) => createNode(id, { parent_id: parentId, name, description: description || null }),
    invalidates: [queryKeys.projectTree(id), queryKeys.projects],
    onSuccess: () => {
      setNodeForm(null)
      setActionError('')
      toast.success('目录节点已创建')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '创建失败，请重试'),
  })
  const update = useGroveMutation({
    mutationFn: ({
      nodeId,
      name,
      description,
    }: {
      nodeId: number
      name: string
      description: string
    }) => updateNode(id, nodeId, { name, description: description || null }),
    invalidates: [queryKeys.projectTree(id)],
    onSuccess: () => {
      setNodeForm(null)
      setActionError('')
      toast.success('目录节点已更新')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '更新失败，请重试'),
  })
  const removeNode = useGroveMutation({
    mutationFn: (nodeId: number) => deleteNode(id, nodeId),
    invalidates: [queryKeys.projectTree(id), queryKeys.projects],
    onSuccess: () => {
      setDeleteNodeTarget(null)
      setSelectedId(null)
      setActionError('')
      toast.success('目录节点已删除')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '删除失败，请重试'),
  })
  const discardDraft = useGroveMutation({
    mutationFn: () => discardDirectoryDraft(id),
    invalidates: [queryKeys.directoryDraft(id)],
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: queryKeys.directoryDraft(id) })
      toast.success('AI 草稿已放弃')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '放弃草稿失败'),
  })
  const reorder = useGroveMutation({
    mutationFn: ({ parentId, orderedIds }: { parentId: number | null; orderedIds: number[] }) =>
      reorderNodes(id, parentId, orderedIds),
    invalidates: [queryKeys.projectTree(id)],
    onSuccess: () => {
      setActionError('')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '排序失败，请重试'),
  })
  const move = useGroveMutation({
    mutationFn: () => updateNode(id, moveTarget!.id, { parent_id: moveParentId }),
    invalidates: [queryKeys.projectTree(id)],
    onSuccess: () => {
      setMoveTarget(null)
      setActionError('')
      toast.success('目录节点已移动')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '移动失败，请重试'),
  })
  const editProject = useGroveMutation({
    mutationFn: () =>
      updateProject(id, {
        name: projectName.trim(),
        description: projectDescription.trim() || null,
      }),
    invalidates: [queryKeys.projects],
    onSuccess: () => {
      setEditProjectOpen(false)
      setActionError('')
      toast.success('项目信息已更新')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '保存失败，请重试'),
  })
  const changeStatus = useGroveMutation({
    mutationFn: (status: ProjectStatus) => updateProjectStatus(id, status),
    invalidates: [queryKeys.projects],
    onSuccess: () => {
      setActionError('')
      toast.success('项目状态已更新')
    },
    onError: (error) =>
      setActionError(error instanceof Error ? error.message : '状态更新失败，请重试'),
  })
  const removeProject = useGroveMutation({
    mutationFn: () => deleteProject(id),
    invalidates: [queryKeys.projects, queryKeys.sources],
    onSuccess: () => {
      navigate('/projects', { replace: true })
      toast.success('项目已删除')
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : '删除失败，请重试'),
  })

  const selectedPath = selectedId ? findNodeWithPath(nodes, selectedId) : null
  const effectiveSelectedPath = selectedPath ?? (nodes[0] ? [nodes[0]] : null)
  const effectiveSelectedId = effectiveSelectedPath?.at(-1)?.id ?? null
  const selectedNode = effectiveSelectedPath?.at(-1) ?? null
  const searchActive = submittedSearch.length > 0
  const directCount = selectedNode?.entry_count ?? 0
  const descendantCount = selectedNode ? descendantEntryCount(selectedNode) : 0
  const entries = useQuery({
    queryKey: queryKeys.nodeEntries(id, effectiveSelectedId ?? 0, scope),
    queryFn: () => fetchNodeEntries(id, effectiveSelectedId as number, scope),
    enabled: isDirectoryView && !searchActive && effectiveSelectedId !== null,
  })
  const searchResults = useQuery({
    queryKey: queryKeys.search(submittedSearch, id),
    queryFn: () => searchEntries(submittedSearch, id),
    enabled: isDirectoryView && searchActive && Number.isFinite(id),
  })

  function openAddNode(parent: TreeNodePayload | null) {
    setActionError('')
    setNodeForm({ mode: 'create', parent, node: null })
  }

  async function handleExpand(node: TreeNodePayload) {
    setActionError('')
    setCheckingDraft(true)
    try {
      const existing = await fetchDirectoryDraft(id)
      if (existing.kind === 'expand' && existing.target_node_id === node.id) {
        // 同一节点的已有拓展草稿直接继续，不重新生成
        setExpandTarget(node)
      } else {
        setOverwriteNode(node)
      }
    } catch {
      setExpandTarget(node)
    } finally {
      setCheckingDraft(false)
    }
  }

  function continueActiveDraft() {
    setActionError('')
    if (activeDraft?.kind === 'expand' && draftTargetNode) {
      setExpandTarget(draftTargetNode)
      return
    }
    if (activeDraft?.kind === 'draft') {
      setAiOpen(true)
    }
  }

  function openProjectEdit() {
    if (!project) return
    setProjectName(project.name)
    setProjectDescription(project.description ?? '')
    setActionError('')
    setEditProjectOpen(true)
  }

  function changeViewMode(next: 'card' | 'list') {
    setViewMode(next)
    if (Number.isFinite(id)) window.localStorage.setItem(`grove.view-mode.${id}`, next)
  }

  if (!Number.isFinite(id))
    return (
      <div role="alert" className="px-6 py-[22px] text-body-sm text-destructive">
        项目地址无效。
      </div>
    )
  if (projects.isLoading || tree.isLoading)
    return (
      <div className="space-y-5 px-6 py-[22px]" aria-label="项目加载中">
        <div className="h-[58px] animate-pulse bg-muted/60" />
        <div className="h-[520px] animate-pulse bg-muted/40" />
      </div>
    )
  if (projects.isError || tree.isError)
    return (
      <div className="m-6 border-l-2 border-destructive px-4 py-3">
        <p className="text-body-sm">项目工作台加载失败，请重试。</p>
        <Button
          className="mt-3"
          variant="outline"
          size="sm"
          onClick={() => {
            projects.refetch()
            tree.refetch()
          }}
        >
          重试
        </Button>
      </div>
    )
  if (!project)
    return (
      <div className="m-6 border-l-2 border-destructive px-4 py-3 text-body-sm">
        项目不存在，或你无权访问该项目。
      </div>
    )

  return (
    <section
      className={`w-full px-6 pb-[30px] pt-[22px] ${isDirectoryView ? 'flex h-full flex-col' : ''}`}
    >
      <header className="mb-5 flex min-h-[60px] items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-[22px] font-[650] leading-[30px]">
              {isSourcesView ? '采集与来源' : isDirectoryView ? '知识空间' : project.name}
            </h1>
            {!isDirectoryView && !isSourcesView ? (
              <Badge variant="outline" className="shrink-0">
                {PROJECT_STATUSES.find(({ key }) => key === project.status)?.label}
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 max-w-2xl text-body text-muted-foreground">
            {isSourcesView
              ? `${project.name} · 管理这个项目的原始材料。`
              : isDirectoryView
              ? `${project.name} · 按目录浏览和维护项目知识。`
              : project.description || '尚未填写项目目标与背景'}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isSourcesView ? (
            <Button size="sm" onClick={() => setCaptureOpen(true)}>
              <Plus />
              采集到项目
            </Button>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon-sm" variant="ghost" aria-label="项目更多操作">
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={openProjectEdit}>
                <Pencil />
                编辑项目信息
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  setActionError('')
                  setDeleteProjectOpen(true)
                }}
              >
                <Trash2 />
                删除项目
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {actionError &&
      !nodeForm &&
      !deleteNodeTarget &&
      !moveTarget &&
      !editProjectOpen &&
      !deleteProjectOpen ? (
        <div
          role="alert"
          className="mb-4 border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive"
        >
          {actionError}
        </div>
      ) : null}

      <CaptureDialog
        open={captureOpen}
        onOpenChange={setCaptureOpen}
        projects={[]}
        fixedProjectId={id}
        onCreated={() => queryClient.invalidateQueries({ queryKey: queryKeys.sources })}
      />

      {isSourcesView ? (
        <ProjectSources projectId={id} />
      ) : isDirectoryView ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {activeDraft ? (
            <div className="flex items-center justify-between gap-3 border-b bg-brand-soft/60 px-4 py-2">
              <div className="flex min-w-0 items-center gap-2 text-body-sm">
                <Sparkles className="size-4 shrink-0 text-brand" />
                <span className="truncate">
                  {activeDraft.kind === 'expand'
                    ? `AI 拓展草稿进行中：正在拓展「${draftTargetNode?.name ?? '目标节点'}」`
                    : '与 AI 共创目录草稿进行中'}
                </span>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={discardDraft.isPending}
                  onClick={() => discardDraft.mutate()}
                >
                  <X />
                  放弃草稿
                </Button>
                <Button size="sm" onClick={continueActiveDraft}>
                  继续处理
                </Button>
              </div>
            </div>
          ) : null}
          <div
            data-testid="knowledge-layout"
            className="grid min-h-0 flex-1 grid-cols-[250px_minmax(0,1fr)] border-t"
          >
            <aside className="min-h-0 min-w-0 overflow-y-auto border-r px-[10px] py-[14px]">
            <div className="mb-2 flex h-[34px] items-center justify-between px-1">
              <div className="flex min-w-0 items-baseline gap-2">
                <h2 className="truncate text-body font-[650]">项目目录</h2>
                <span className="text-caption text-muted-foreground">{project.node_count}</span>
              </div>
              {nodes.length > 0 ? (
                <Button
                  size="icon-xs"
                  variant="ghost"
                  onClick={() => openAddNode(null)}
                  aria-label="创建根节点"
                >
                  <Plus />
                </Button>
              ) : null}
            </div>
            {nodes.length > 0 ? (
              <NodeTree
                nodes={nodes}
                selectedId={effectiveSelectedId}
                onSelect={(node) => setSelectedId(node.id)}
                callbacks={{
                  onAddChild: openAddNode,
                  onRename: (node) => {
                    setActionError('')
                    setNodeForm({ mode: 'edit', parent: null, node })
                  },
                  onMove: (node) => {
                    setActionError('')
                    setMoveTarget(node)
                    setMoveParentId(null)
                  },
                  onDelete: (node) => {
                    setActionError('')
                    setDeleteNodeTarget(node)
                  },
                  onExpand: (node) => {
                    void handleExpand(node)
                  },
                  onReorder: (parentId, orderedIds) => reorder.mutate({ parentId, orderedIds }),
                }}
              />
            ) : (
              <p className="px-1 py-2 text-caption text-muted-foreground">目录还是空的</p>
            )}
          </aside>
          <div
            data-testid="knowledge-content"
            className="min-h-0 min-w-0 overflow-y-auto px-6 pb-7 pt-3.5"
          >
            {nodes.length === 0 ? (
              <div className="flex min-h-[500px] items-center justify-center text-center">
                <div className="max-w-[380px]">
                  <span className="mx-auto flex size-10 items-center justify-center rounded-md bg-muted">
                    <FolderTree className="size-[18px] text-muted-foreground" />
                  </span>
                  <h2 className="mt-4 text-[16px] font-[650] leading-6">从空目录开始</h2>
                  <p className="mt-1 text-body-sm leading-6 text-muted-foreground">
                    按你的理解方式建立目录，后续可随时编辑、移动和排序。
                  </p>
                  <div className="mt-5 flex justify-center gap-2">
                    <Button onClick={() => openAddNode(null)}>
                      <FolderPlus />
                      手动创建
                    </Button>
                    <Button variant="outline" onClick={() => setAiOpen(true)}>
                      <Sparkles />与 AI 共创目录
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <div>
                {searchActive ? (
                  <div className="mb-4 flex min-h-[50px] items-center justify-between gap-4 border-b">
                    <div className="min-w-0">
                      <h2 className="truncate text-[16px] font-[650] leading-6">搜索结果</h2>
                      <p className="truncate text-caption text-muted-foreground">
                        “{submittedSearch}” · 项目内 {searchResults.data?.length ?? 0} 条
                      </p>
                    </div>
                  </div>
                ) : selectedNode ? (
                  <div className="mb-4 border-b">
                    <p className="truncate text-caption text-muted-foreground">
                      {effectiveSelectedPath?.map((node) => node.name).join(' / ')}
                    </p>
                    <div className="flex min-h-[50px] items-center justify-between gap-4">
                      <div className="min-w-0">
                        <h2 className="truncate text-[16px] font-[650] leading-6">
                          {selectedNode.name}
                        </h2>
                        <p className="truncate text-caption text-muted-foreground">
                          {selectedNode.description || '尚未填写节点说明。'}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleExpand(selectedNode)}
                          disabled={checkingDraft}
                        >
                          <Sparkles />
                          AI 拓展
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setNodeForm({ mode: 'edit', parent: null, node: selectedNode })}
                        >
                          <Pencil />
                          编辑节点
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : null}
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <div className="relative min-w-0 flex-1">
                    <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={searchInput}
                      onChange={(event) => setSearchInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') submitSearch()
                      }}
                      placeholder="搜索本项目的知识…"
                      className="pl-8 pr-16"
                      aria-label="搜索本项目知识"
                    />
                    <button
                      type="button"
                      onClick={submitSearch}
                      aria-label="执行搜索"
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <Search className="size-4" />
                    </button>
                    {searchInput ? (
                      <button
                        type="button"
                        onClick={() => {
                          setSearchInput('')
                          setSubmittedSearch('')
                        }}
                        className="absolute right-9 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        aria-label="清空搜索"
                      >
                        <X className="size-4" />
                      </button>
                    ) : null}
                  </div>
                  {!searchActive ? (
                    <div
                      className="flex items-center rounded-md border"
                      role="group"
                      aria-label="知识范围切换"
                    >
                      <button
                        type="button"
                        onClick={() => setScope('direct')}
                        aria-pressed={scope === 'direct'}
                        className={`flex h-9 items-center px-2.5 text-body-sm ${
                          scope === 'direct'
                            ? 'bg-muted font-medium text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        仅本节点（{directCount}）
                      </button>
                      <button
                        type="button"
                        onClick={() => setScope('descendants')}
                        aria-pressed={scope === 'descendants'}
                        className={`flex h-9 items-center px-2.5 text-body-sm ${
                          scope === 'descendants'
                            ? 'bg-muted font-medium text-foreground'
                            : 'text-muted-foreground hover:text-foreground'
                        }`}
                      >
                        仅后代（{descendantCount}）
                      </button>
                    </div>
                  ) : null}
                  <div
                    className="flex items-center rounded-md border"
                    role="group"
                    aria-label="视图切换"
                  >
                    <button
                      type="button"
                      onClick={() => changeViewMode('card')}
                      aria-pressed={viewMode === 'card'}
                      aria-label="卡片视图"
                      className={`flex h-9 items-center gap-1.5 px-2.5 text-body-sm ${
                        viewMode === 'card'
                          ? 'bg-muted font-medium text-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <LayoutGrid className="size-4" />
                      卡片
                    </button>
                    <button
                      type="button"
                      onClick={() => changeViewMode('list')}
                      aria-pressed={viewMode === 'list'}
                      aria-label="列表视图"
                      className={`flex h-9 items-center gap-1.5 px-2.5 text-body-sm ${
                        viewMode === 'list'
                          ? 'bg-muted font-medium text-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <List className="size-4" />
                      列表
                    </button>
                  </div>
                </div>

                {searchActive ? (
                  <div>
                    {searchResults.isLoading ? (
                      <div className="py-10 text-center text-body-sm text-muted-foreground">
                        正在搜索…
                      </div>
                    ) : (searchResults.data?.length ?? 0) === 0 ? (
                      <div className="flex min-h-[420px] items-center justify-center text-center">
                        <div className="max-w-[320px]">
                          <Search className="mx-auto size-5 text-muted-foreground" />
                          <h3 className="mt-3 text-body font-[650]">没有匹配的正式知识</h3>
                          <p className="mt-1 text-body-sm leading-6 text-muted-foreground">
                            换个关键词试试。
                          </p>
                        </div>
                      </div>
                    ) : viewMode === 'card' ? (
                      <div className="space-y-3 pt-4">
                        {searchResults.data?.map((entry) => (
                          <EntryCard key={entry.id} entry={entry} highlightQuery={submittedSearch} />
                        ))}
                      </div>
                    ) : (
                      <div className="pt-4">
                        <EntryList entries={searchResults.data ?? []} highlightQuery={submittedSearch} />
                      </div>
                    )}
                  </div>
                ) : selectedNode ? (
                  <div>
                    {entries.isLoading ? (
                      <div className="py-10 text-center text-body-sm text-muted-foreground">
                        加载正式知识…
                      </div>
                    ) : (entries.data?.length ?? 0) === 0 ? (
                      <div className="flex min-h-[420px] items-center justify-center text-center">
                        <div className="max-w-[320px]">
                          <BookOpen className="mx-auto size-5 text-muted-foreground" />
                          <h3 className="mt-3 text-body font-[650]">这里还没有正式知识</h3>
                          <p className="mt-1 text-body-sm leading-6 text-muted-foreground">
                            {scope === 'descendants'
                              ? '该目录及其后代暂无可浏览的内容。'
                              : '当前目录下暂无可浏览的内容。'}
                          </p>
                        </div>
                      </div>
                    ) : viewMode === 'card' ? (
                      <div className="space-y-3 pt-4">
                        {entries.data?.map((entry) => (
                          <EntryCard key={entry.id} entry={entry} />
                        ))}
                      </div>
                    ) : (
                      <div className="pt-4">
                        <EntryList entries={entries.data ?? []} />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex min-h-[500px] items-center justify-center text-center">
                    <div>
                      <FolderTree className="mx-auto size-5 text-muted-foreground" />
                      <p className="mt-2 text-body-sm text-muted-foreground">
                        选择一个目录节点查看说明
                      </p>
                    </div>
                  </div>
                )}
              </div>
            )}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid min-h-[604px] grid-cols-[minmax(0,1.4fr)_minmax(280px,.8fr)] gap-7">
          <div className="min-w-0">
            <section>
              <div className="flex h-9 items-center justify-between">
                <div className="flex items-baseline gap-2">
                  <h2 className="text-[16px] font-[650] leading-6">项目目录</h2>
                  <span className="text-caption text-muted-foreground">
                    {project.node_count} 个节点
                  </span>
                </div>
                <Button asChild size="sm" variant="ghost">
                  <Link to={`/projects/${id}?view=directory`}>
                    进入知识空间
                    <ArrowRight />
                  </Link>
                </Button>
              </div>
              <div className="mt-3 border-y">
                <Link
                  to={`/projects/${id}?view=directory`}
                  className="group flex min-h-[76px] items-center gap-3 px-2 hover:bg-muted/50"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                    <FolderTree className="size-[18px] text-brand" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-body font-[650]">
                      {nodes.length > 0 ? '浏览项目知识空间' : '知识空间还是空的'}
                    </span>
                    <span className="mt-0.5 block text-body-sm text-muted-foreground">
                      {nodes.length > 0
                        ? `当前共有 ${project.node_count} 个目录节点`
                        : '进入知识空间，创建第一个根节点。'}
                    </span>
                  </span>
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </section>
            <section className="mt-7 border-t pt-5">
              <h2 className="text-[16px] font-[650] leading-6">项目目标与背景</h2>
              <p className="mt-2 max-w-2xl text-body-sm leading-6 text-muted-foreground">
                {project.description || '尚未填写项目目标与背景。'}
              </p>
              <Button className="mt-3" size="sm" variant="outline" onClick={openProjectEdit}>
                <Pencil />
                编辑项目信息
              </Button>
            </section>
            <ProjectContextPanel projectId={id} nodes={tree.data ?? []} />
          </div>

          <aside className="border-l pl-[22px]">
            <section>
              <div className="flex h-9 items-center justify-between">
                <h2 className="text-body font-[650]">项目状态</h2>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-1.5" role="group" aria-label="项目状态">
                {PROJECT_STATUSES.map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    disabled={changeStatus.isPending}
                    onClick={() => changeStatus.mutate(key)}
                    className={`h-8 rounded-md border text-caption transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${project.status === key ? 'border-brand/30 bg-brand-soft font-semibold text-brand' : 'bg-white text-muted-foreground hover:bg-muted'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </section>
          </aside>
        </div>
      )}

      <NodeFormDialog
        key={
          nodeForm
            ? `${nodeForm.mode}-${nodeForm.node?.id ?? nodeForm.parent?.id ?? 'root'}`
            : 'closed'
        }
        state={nodeForm}
        onClose={() => {
          setNodeForm(null)
          setActionError('')
        }}
        onSubmit={(values) => {
          if (!nodeForm) return
          if (nodeForm.mode === 'edit' && nodeForm.node)
            update.mutate({ nodeId: nodeForm.node.id, ...values })
          else create.mutate({ parentId: nodeForm.parent?.id ?? null, ...values })
        }}
        isPending={create.isPending || update.isPending}
      />

      <Dialog
        open={deleteNodeTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteNodeTarget(null)
            setActionError('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除目录节点</DialogTitle>
            <DialogDescription>
              将删除「{deleteNodeTarget?.name}」及其全部子节点，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          {actionError ? (
            <div
              role="alert"
              className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive"
            >
              {actionError}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteNodeTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={removeNode.isPending}
              onClick={() => deleteNodeTarget && removeNode.mutate(deleteNodeTarget.id)}
            >
              <Trash2 />
              {removeNode.isPending ? '删除中…' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={overwriteNode !== null}
        onOpenChange={(open) => {
          if (!open) setOverwriteNode(null)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>覆盖当前草稿</DialogTitle>
            <DialogDescription>
              项目已有进行中的
              {activeDraft?.kind === 'expand'
                ? `「AI 拓展 ${draftTargetNode?.name ?? '目标节点'}」草稿`
                : '「与 AI 共创目录」草稿'}
              ，继续将覆盖未应用的候选内容，正式目录不受影响。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOverwriteNode(null)}>
              取消
            </Button>
            <Button
              disabled={checkingDraft}
              onClick={() => {
                const node = overwriteNode
                setOverwriteNode(null)
                if (node) setExpandTarget(node)
              }}
            >
              覆盖并继续
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={moveTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setMoveTarget(null)
            setActionError('')
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>移动目录节点</DialogTitle>
            <DialogDescription>选择「{moveTarget?.name}」的新位置。</DialogDescription>
          </DialogHeader>
          {actionError ? (
            <div
              role="alert"
              className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive"
            >
              {actionError}
            </div>
          ) : null}
          <DirectoryTreeSelect
            nodes={nodes}
            value={moveParentId}
            allowRoot
            placeholder="根目录"
            ariaLabel="新父节点"
            filter={moveNodeFilter}
            onSelect={(id) => setMoveParentId(id)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setMoveTarget(null)}>
              取消
            </Button>
            <Button disabled={move.isPending} onClick={() => move.mutate()}>
              {move.isPending ? '移动中…' : '确认移动'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editProjectOpen}
        onOpenChange={(open) => {
          setEditProjectOpen(open)
          if (!open) setActionError('')
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>编辑项目信息</DialogTitle>
            <DialogDescription>目标与背景是一个可选字段。</DialogDescription>
          </DialogHeader>
          {actionError ? (
            <div
              role="alert"
              className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive"
            >
              {actionError}
            </div>
          ) : null}
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="edit-project-name" className="text-body-sm font-medium">
                项目名称
              </label>
              <Input
                id="edit-project-name"
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="edit-project-description" className="text-body-sm font-medium">
                目标与背景（可选）
              </label>
              <Textarea
                id="edit-project-description"
                value={projectDescription}
                onChange={(event) => setProjectDescription(event.target.value)}
                rows={5}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditProjectOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!projectName.trim() || editProject.isPending}
              onClick={() => editProject.mutate()}
            >
              {editProject.isPending ? '保存中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={deleteProjectOpen}
        onOpenChange={(open) => {
          setDeleteProjectOpen(open)
          if (!open) setActionError('')
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除项目</DialogTitle>
            <DialogDescription>
              将删除「{project.name}」及其全部目录节点，此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          {actionError ? (
            <div
              role="alert"
              className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive"
            >
              {actionError}
            </div>
          ) : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteProjectOpen(false)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={removeProject.isPending}
              onClick={() => removeProject.mutate()}
            >
              <Trash2 />
              {removeProject.isPending ? '删除中…' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DirectoryDraftDialog
        projectId={id}
        mode={expandTarget ? 'expand' : 'draft'}
        targetNode={expandTarget}
        open={aiOpen || expandTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAiOpen(false)
            setExpandTarget(null)
            queryClient.invalidateQueries({ queryKey: queryKeys.directoryDraft(id) })
          }
        }}
        onApplied={() => {
          queryClient.invalidateQueries({ queryKey: queryKeys.projectTree(id) })
          queryClient.invalidateQueries({ queryKey: queryKeys.projects })
          queryClient.removeQueries({ queryKey: queryKeys.directoryDraft(id) })
          queryClient.invalidateQueries({ queryKey: queryKeys.directoryDraft(id) })
        }}
      />
    </section>
  )
}
