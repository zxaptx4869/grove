import { useMemo, useState, type ComponentType } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  BellRing,
  BookOpen,
  Columns3,
  Focus,
  FoldVertical,
  Folder,
  FolderInput,
  FolderOpen,
  FolderTree,
  Lightbulb,
  Minus,
  Network,
  Plus,
  Ruler,
  Search,
  UnfoldVertical,
  X,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  fetchNodeEntries,
  fetchProjectEntries,
  fetchProjectTree,
  type EntryPayload,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const NODE_WIDTH = 210
const NODE_HEIGHT = 36
const CARD_WIDTH = 168
const CARD_HEIGHT = 32
const COLUMN_GAP = 260
const ROW_GAP = 56
const CANVAS_PAD = 28
const MAX_VISIBLE_NODES = 60
const MAX_DEPTH = 3
const VIRTUAL_ROOT_ID = -1

const ENTRY_TYPE_LABELS: Record<string, string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

const ENTRY_TYPE_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  knowledge: BookOpen,
  method: Lightbulb,
  parameter: Ruler,
  reminder: BellRing,
}

interface PlacedNode {
  id: number
  name: string
  kind: 'node' | 'entry'
  entryType?: string
  depth: number
  x: number
  y: number
  parentId: number | null
  entryCount: number
  subtreeCount: number
  hasChildren: boolean
  collapsed: boolean
}

/** 递归计算每个节点「本节点 + 全部严格后代」的 Entry 总数。 */
function subtreeCountMap(nodes: readonly TreeNodePayload[]): Map<number, number> {
  const map = new Map<number, number>()
  const walk = (items: readonly TreeNodePayload[]): number => {
    let total = 0
    for (const node of items) {
      const sum = node.entry_count + walk(node.children)
      map.set(node.id, sum)
      total += sum
    }
    return total
  }
  walk(nodes)
  return map
}

function totalNodeCount(nodes: readonly TreeNodePayload[]): number {
  return nodes.reduce((sum, node) => sum + 1 + totalNodeCount(node.children), 0)
}

function findNodePath(
  nodes: readonly TreeNodePayload[],
  targetId: number,
  path: TreeNodePayload[] = [],
): TreeNodePayload[] | null {
  for (const node of nodes) {
    const next = [...path, node]
    if (node.id === targetId) return next
    const found = findNodePath(node.children, targetId, next)
    if (found) return found
  }
  return null
}

/** 构建 nodeId → 完整路径名称（根 / 子 / 孙）映射。 */
function pathNameMap(
  nodes: readonly TreeNodePayload[],
  map = new Map<number, string>(),
  prefix: string[] = [],
): Map<number, string> {
  for (const node of nodes) {
    const path = [...prefix, node.name]
    map.set(node.id, path.join(' / '))
    pathNameMap(node.children, map, path)
  }
  return map
}

/** 左→右分层布局：父节点垂直居中于其子节点，叶子按行分配槽位。 */
function placeTree(
  nodes: readonly TreeNodePayload[],
  parentId: number | null,
  depth: number,
  collapsedIds: ReadonlySet<number>,
  forceExpand: boolean,
  counts: Map<number, number>,
  revealedNodes: ReadonlySet<number>,
  entriesByNode: Map<number, EntryPayload[]>,
  out: PlacedNode[],
  state: { nextSlot: number },
): void {
  for (const node of nodes) {
    if (out.length >= MAX_VISIBLE_NODES) continue
    const hasChildren = node.children.length > 0
    const collapsed = !forceExpand && collapsedIds.has(node.id)
    const childStart = out.length
    if (!collapsed && hasChildren && depth + 1 <= MAX_DEPTH) {
      placeTree(
        node.children,
        node.id,
        depth + 1,
        collapsedIds,
        forceExpand,
        counts,
        revealedNodes,
        entriesByNode,
        out,
        state,
      )
    }
    // 知识小卡：该节点直接 Entry 以终端分支形式就地展示
    const revealedEntries = revealedNodes.has(node.id) ? (entriesByNode.get(node.id) ?? []) : []
    if (!collapsed && revealedEntries.length > 0 && depth + 1 <= MAX_DEPTH) {
      for (const entry of revealedEntries) {
        if (out.length >= MAX_VISIBLE_NODES) continue
        const y = state.nextSlot++ * ROW_GAP + CANVAS_PAD
        out.push({
          id: entry.id,
          name: entry.title,
          kind: 'entry',
          entryType: entry.main_type,
          depth: depth + 1,
          x: (depth + 1) * COLUMN_GAP + CANVAS_PAD,
          y,
          parentId: node.id,
          entryCount: 0,
          subtreeCount: 0,
          hasChildren: false,
          collapsed: false,
        })
      }
    }
    const childCount = out.length - childStart
    const y =
      childCount > 0
        ? (out[childStart].y + out[out.length - 1].y) / 2
        : state.nextSlot++ * ROW_GAP + CANVAS_PAD
    out.push({
      id: node.id,
      name: node.name,
      kind: 'node',
      depth,
      x: depth * COLUMN_GAP + CANVAS_PAD,
      y,
      parentId,
      entryCount: node.entry_count,
      subtreeCount: counts.get(node.id) ?? node.entry_count,
      hasChildren,
      collapsed,
    })
  }
}

/** 思维导图：项目级沉浸式目录阅读视图，目录骨架 + 知识按需展开。 */
export function MindMapView({
  projectId,
  projectName,
}: {
  projectId: number
  projectName: string
}) {
  const [searchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const raw = searchParams.get('node')
    const parsed = raw ? Number(raw) : NaN
    return Number.isFinite(parsed) ? parsed : VIRTUAL_ROOT_ID
  })
  const [selectedEntry, setSelectedEntry] = useState<EntryPayload | null>(null)
  const [focusId, setFocusId] = useState<number | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<number>>(new Set())
  const [revealedNodes, setRevealedNodes] = useState<ReadonlySet<number>>(new Set())
  const [searchInput, setSearchInput] = useState('')
  const [includeSubtree, setIncludeSubtree] = useState(true)
  const [sideOpen, setSideOpen] = useState(true)

  const tree = useQuery({
    queryKey: queryKeys.projectTree(projectId),
    queryFn: () => fetchProjectTree(projectId),
    enabled: Number.isFinite(projectId),
  })

  const counts = useMemo(() => {
    const map = subtreeCountMap(tree.data ?? [])
    const total =
      tree.data?.reduce((sum, node) => sum + (map.get(node.id) ?? node.entry_count), 0) ?? 0
    map.set(VIRTUAL_ROOT_ID, total)
    return map
  }, [tree.data])
  const pathNames = useMemo(() => {
    const map = pathNameMap(tree.data ?? [])
    map.set(VIRTUAL_ROOT_ID, projectName)
    return map
  }, [tree.data, projectName])
  const virtualRoot = useMemo<TreeNodePayload | null>(() => {
    const nodes = tree.data ?? []
    if (nodes.length === 0) return null
    return {
      id: VIRTUAL_ROOT_ID,
      name: projectName,
      description: null,
      position: 0,
      entry_count: 0,
      children: nodes,
    }
  }, [tree.data, projectName])
  const roots = useMemo(() => {
    if (focusId != null) {
      const path = findNodePath(tree.data ?? [], focusId)
      return path ? [path[path.length - 1]] : []
    }
    return virtualRoot ? [virtualRoot] : []
  }, [tree.data, focusId, virtualRoot])
  const focusPath = useMemo(
    () => (focusId != null ? findNodePath(tree.data ?? [], focusId) : null),
    [tree.data, focusId],
  )

  const searchActive = searchInput.trim().length > 0
  const matches = useMemo(() => {
    const found = new Set<number>()
    if (!searchActive) return found
    const query = searchInput.trim().toLowerCase()
    const walk = (items: readonly TreeNodePayload[]) => {
      for (const node of items) {
        if (node.name.toLowerCase().includes(query)) found.add(node.id)
        walk(node.children)
      }
    }
    walk(roots)
    return found
  }, [roots, searchInput, searchActive])

  const revealedIds = useMemo(() => Array.from(revealedNodes), [revealedNodes])
  const revealedQueries = useQueries({
    queries: revealedIds.map((nodeId) => ({
      queryKey: queryKeys.nodeEntries(projectId, nodeId, 'direct'),
      queryFn: () => fetchNodeEntries(projectId, nodeId, 'direct'),
    })),
  })
  const entriesByNode = useMemo(() => {
    const map = new Map<number, EntryPayload[]>()
    revealedIds.forEach((nodeId, index) => {
      const data = revealedQueries[index]?.data
      if (data) map.set(nodeId, data)
    })
    return map
  }, [revealedIds, revealedQueries])

  const placed = useMemo(() => {
    const out: PlacedNode[] = []
    const state = { nextSlot: 0 }
    placeTree(
      roots,
      null,
      0,
      collapsedIds,
      searchActive,
      counts,
      revealedNodes,
      entriesByNode,
      out,
      state,
    )
    return { out, state }
  }, [roots, collapsedIds, searchActive, counts, revealedNodes, entriesByNode])
  const revealedEntryTotal = revealedIds.reduce(
    (sum, nodeId) => sum + (entriesByNode.get(nodeId)?.length ?? 0),
    0,
  )
  const hiddenCount = Math.max(
    0,
    totalNodeCount(roots) + revealedEntryTotal - placed.out.length,
  )
  const canvasWidth =
    Math.max(1, ...placed.out.map((item) => item.depth + 1)) * COLUMN_GAP +
    NODE_WIDTH +
    CANVAS_PAD * 2
  const canvasHeight = placed.state.nextSlot * ROW_GAP + CANVAS_PAD * 2

  const selectedNode = useMemo(() => {
    if (selectedId == null) return null
    if (selectedId === VIRTUAL_ROOT_ID) return virtualRoot
    const path = findNodePath(tree.data ?? [], selectedId)
    return path ? path[path.length - 1] : null
  }, [tree.data, selectedId, virtualRoot])

  const isProjectRootSelected = selectedId === VIRTUAL_ROOT_ID
  const entries = useQuery({
    queryKey: isProjectRootSelected
      ? queryKeys.projectEntries(projectId)
      : queryKeys.nodeEntries(
          projectId,
          selectedId ?? 0,
          includeSubtree ? 'subtree' : 'direct',
        ),
    queryFn: () =>
      isProjectRootSelected
        ? fetchProjectEntries(projectId)
        : fetchNodeEntries(
            projectId,
            selectedId as number,
            includeSubtree ? 'subtree' : 'direct',
          ),
    enabled: sideOpen && selectedId != null,
  })

  function focusNode(nodeId: number) {
    setFocusId(nodeId)
    setCollapsedIds(new Set())
  }

  function expandAll() {
    setCollapsedIds(new Set())
  }

  function collapseAll() {
    const parentIds = new Set<number>()
    const walk = (items: readonly TreeNodePayload[]) => {
      for (const node of items) {
        if (node.children.length > 0) parentIds.add(node.id)
        walk(node.children)
      }
    }
    walk(roots)
    setCollapsedIds(parentIds)
  }

  function clearSearch() {
    setSearchInput('')
  }

  function toggleReveal(nodeId: number) {
    setRevealedNodes((current) => {
      const next = new Set(current)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  function selectNode(nodeId: number) {
    setSelectedId(nodeId)
    setSelectedEntry(null)
  }

  function selectEntry(entry: EntryPayload) {
    setSelectedId(entry.node_id)
    setSelectedEntry(entry)
  }

  if (tree.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-body-sm text-muted-foreground">
        正在加载目录…
      </div>
    )
  }
  if (tree.isError) {
    return (
      <div className="m-6 border-l-2 border-destructive px-4 py-3">
        <p className="text-body-sm">思维导图加载失败，请重试。</p>
        <Button className="mt-3" variant="outline" size="sm" onClick={() => void tree.refetch()}>
          重试
        </Button>
      </div>
    )
  }
  const nodes = tree.data ?? []
  const empty = nodes.length === 0

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Button asChild size="sm" variant="ghost">
            <Link to={`/projects/${projectId}?view=directory`}>
              <ArrowLeft />
              返回知识空间
            </Link>
          </Button>
          <h1 className="truncate text-body font-[650]">{projectName} · 思维导图</h1>
        </div>
        <Button
          size="icon-sm"
          variant="ghost"
          onClick={() => setSideOpen((open) => !open)}
          aria-label={sideOpen ? '收起阅读侧栏' : '展开阅读侧栏'}
          title={sideOpen ? '收起阅读侧栏' : '展开阅读侧栏'}
        >
          <Columns3 className="size-4" />
        </Button>
      </header>

      {empty ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <div className="max-w-[380px] text-center">
            <FolderTree className="mx-auto size-5 text-muted-foreground" />
            <h2 className="mt-3 text-body font-[650]">目录还是空的</h2>
            <p className="mt-1 text-body-sm leading-6 text-muted-foreground">
              先建立目录结构，再回来用思维导图浏览。
            </p>
            <Button asChild className="mt-5" size="sm" variant="outline">
              <Link to={`/projects/${projectId}?view=directory`}>去知识空间创建目录</Link>
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
              <Button size="sm" variant="outline" onClick={expandAll}>
                <UnfoldVertical />
                展开
              </Button>
              <Button size="sm" variant="outline" onClick={collapseAll}>
                <FoldVertical />
                收起
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={selectedId == null || selectedId === VIRTUAL_ROOT_ID}
                onClick={() => selectedId != null && focusNode(selectedId)}
              >
                <Focus />
                聚焦子树
              </Button>
              <div className="relative min-w-0 max-w-[240px] flex-1">
                <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder="搜索并高亮"
                  className="pl-8 pr-8"
                  aria-label="搜索目录节点"
                />
                {searchInput ? (
                  <button
                    type="button"
                    onClick={clearSearch}
                    aria-label="清空搜索"
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-3.5" />
                  </button>
                ) : null}
              </div>
              {searchActive ? (
                <span className="text-caption text-muted-foreground">
                  {matches.size > 0 ? `匹配 ${matches.size} 个节点` : '没有匹配的目录节点'}
                </span>
              ) : null}
              {hiddenCount > 0 ? (
                <span className="text-caption text-muted-foreground">
                  还有 {hiddenCount} 个节点未显示，聚焦子树后查看
                </span>
              ) : null}
              {focusPath ? (
                <div className="flex min-w-0 items-center gap-1 text-caption text-muted-foreground">
                  <button
                    type="button"
                    className="shrink-0 hover:text-foreground"
                    onClick={() => setFocusId(null)}
                  >
                    项目根
                  </button>
                  {focusPath.slice(0, -1).map((node) => (
                    <span key={node.id} className="flex min-w-0 items-center gap-1">
                      <span className="shrink-0">/</span>
                      <button
                        type="button"
                        className="truncate hover:text-foreground"
                        onClick={() => focusNode(node.id)}
                      >
                        {node.name}
                      </button>
                    </span>
                  ))}
                  <span className="shrink-0">/</span>
                  <span className="truncate text-foreground">
                    {focusPath[focusPath.length - 1].name}
                  </span>
                </div>
              ) : null}
            </div>
            <div
              className="mind-map-grid min-h-0 flex-1 overflow-auto"
              data-testid="mind-map-canvas"
            >
              <div className="relative" style={{ width: canvasWidth, height: canvasHeight }}>
                <svg
                  className="absolute inset-0"
                  width={canvasWidth}
                  height={canvasHeight}
                  aria-hidden="true"
                >
                  {placed.out.map((item) => {
                    if (item.parentId == null) return null
                    const parent = placed.out.find(
                      (candidate) => candidate.id === item.parentId && candidate.kind === 'node',
                    )
                    if (!parent) return null
                    return (
                      <line
                        key={`${parent.id}-${item.id}-${item.kind}`}
                        x1={parent.x + NODE_WIDTH}
                        y1={parent.y}
                        x2={item.x}
                        y2={item.y}
                        className="stroke-border"
                        strokeWidth={1}
                      />
                    )
                  })}
                </svg>
                {placed.out.map((item) => {
                  if (item.kind === 'entry') {
                    const isSelected = selectedEntry?.id === item.id
                    const TypeIcon = ENTRY_TYPE_ICONS[item.entryType ?? 'knowledge'] ?? BookOpen
                    return (
                      <button
                        key={`entry-${item.id}`}
                        type="button"
                        data-map-item="true"
                        onClick={() => {
                          const entry = entriesByNode
                            .get(item.parentId ?? -1)
                            ?.find((candidate) => candidate.id === item.id)
                          if (entry) selectEntry(entry)
                        }}
                        className={`absolute flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-left text-caption transition-colors ${
                          isSelected
                            ? 'border-brand/60 bg-brand-soft text-foreground'
                            : 'border-border bg-card hover:bg-muted'
                        }`}
                        style={{
                          left: item.x + NODE_WIDTH - CARD_WIDTH,
                          top: item.y - CARD_HEIGHT / 2,
                          width: CARD_WIDTH,
                        }}
                        title={item.name}
                        aria-pressed={isSelected}
                      >
                        <TypeIcon className="size-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate">{item.name}</span>
                      </button>
                    )
                  }
                  const isSelected = item.id === selectedId
                  const isMatched = searchActive && matches.has(item.id)
                  const dimmed = searchActive && !isMatched
                  const revealed = revealedNodes.has(item.id)
                  return (
                    <div
                      key={`node-${item.id}`}
                      data-map-item="true"
                      className={`absolute flex h-9 items-center rounded-md border bg-card shadow-sm transition-colors ${
                        isSelected
                          ? 'border-brand/60 bg-brand-soft text-foreground'
                          : 'border-border'
                      } ${dimmed ? 'opacity-40' : ''}`}
                      style={{
                        left: item.x,
                        top: item.y - NODE_HEIGHT / 2,
                        width: NODE_WIDTH,
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => selectNode(item.id)}
                        className={`flex min-w-0 flex-1 items-center gap-2 rounded-l-md px-2.5 text-left text-body-sm ${
                          isMatched ? 'ring-2 ring-brand/40' : ''
                        } ${isSelected ? 'text-foreground' : 'hover:bg-muted/60'}`}
                        aria-pressed={isSelected}
                        title={item.name}
                      >
                        {item.id === VIRTUAL_ROOT_ID ? (
                          <Network className="size-4 shrink-0 text-brand" />
                        ) : item.hasChildren && !item.collapsed ? (
                          <FolderOpen className="size-4 shrink-0 text-brand" />
                        ) : (
                          <Folder className="size-4 shrink-0 text-muted-foreground" />
                        )}
                        <span className="min-w-0 flex-1 truncate">{item.name}</span>
                        <span className="shrink-0 text-caption text-muted-foreground">
                          {item.entryCount} / {item.subtreeCount}
                        </span>
                      </button>
                      {item.entryCount > 0 ? (
                        <button
                          type="button"
                          onClick={() => toggleReveal(item.id)}
                          aria-label={`${revealed ? '收起' : '展开'} ${item.name} 的直接知识`}
                          title={revealed ? '收起直接知识' : '展开直接知识'}
                          className="flex h-9 shrink-0 items-center gap-0.5 rounded-r-md px-1.5 text-caption text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          {revealed ? <Minus className="size-3.5" /> : <Plus className="size-3.5" />}
                          {item.entryCount}
                        </button>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {sideOpen && selectedNode ? (
            <aside className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l px-4 py-4">
              {selectedEntry ? (
                <div className="min-h-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-caption text-muted-foreground">知识详情</p>
                      <h2 className="mt-0.5 text-body font-[650]">{selectedEntry.title}</h2>
                      <p className="mt-0.5 truncate text-caption text-muted-foreground">
                        {pathNames.get(selectedEntry.node_id) ?? selectedEntry.node_name}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="shrink-0"
                      onClick={() => setSelectedEntry(null)}
                    >
                      返回列表
                    </Button>
                  </div>
                  <Badge variant="outline" className="mt-3 bg-brand-soft text-brand">
                    {ENTRY_TYPE_LABELS[selectedEntry.main_type] ?? selectedEntry.main_type}
                  </Badge>
                  <p className="mt-3 whitespace-pre-wrap text-body-sm leading-6">
                    {selectedEntry.content}
                  </p>
                  {selectedEntry.applicable_condition ? (
                    <p className="mt-3 text-body-sm text-muted-foreground">
                      适用条件：{selectedEntry.applicable_condition}
                    </p>
                  ) : null}
                  {selectedEntry.note ? (
                    <p className="mt-2 text-body-sm text-muted-foreground">
                      补充说明：{selectedEntry.note}
                    </p>
                  ) : null}
                  {selectedEntry.evidences.length > 0 ? (
                    <div className="mt-4 border-t pt-3">
                      <p className="text-caption text-muted-foreground">
                        来源证据 {selectedEntry.evidences.length} 条
                      </p>
                      {selectedEntry.evidences.map((evidence) => (
                        <blockquote key={evidence.id} className="mt-2 border-l-2 pl-2 text-caption">
                          <span className="font-medium text-foreground">
                            {evidence.source_title}
                          </span>
                          <span className="mt-0.5 block text-muted-foreground">
                            {evidence.quote || '（无引用片段）'}
                          </span>
                        </blockquote>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : (
                <>
                  <div className="min-w-0">
                    <p className="text-caption text-muted-foreground">当前节点</p>
                    <h2 className="mt-0.5 truncate text-body font-[650]">
                      {selectedNode.name}
                    </h2>
                    <p className="mt-0.5 truncate text-caption text-muted-foreground">
                      {pathNames.get(selectedNode.id) ?? selectedNode.name}
                    </p>
                  </div>
                  {!isProjectRootSelected ? (
                    <>
                      <Button
                        asChild
                        size="sm"
                        variant="ghost"
                        className="mt-2 w-full justify-start px-2"
                      >
                        <Link to={`/projects/${projectId}?view=directory&node=${selectedNode.id}`}>
                          <FolderInput />
                          在知识空间中打开
                        </Link>
                      </Button>
                      <label className="mt-4 flex cursor-pointer items-center justify-between rounded-md border px-3 py-2.5">
                        <span className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={includeSubtree}
                            onChange={(event) => setIncludeSubtree(event.target.checked)}
                            className="size-4"
                          />
                          <span>
                            <span className="block text-body-sm font-medium">包含子树</span>
                            <span className="block text-caption text-muted-foreground">
                              共{' '}
                              {includeSubtree
                                ? counts.get(selectedNode.id) ?? selectedNode.entry_count
                                : selectedNode.entry_count}{' '}
                              条正式知识
                            </span>
                          </span>
                        </span>
                      </label>
                    </>
                  ) : (
                    <p className="mt-4 rounded-md border bg-muted/40 px-3 py-2.5 text-body-sm">
                      全部正式知识 · 共 {counts.get(VIRTUAL_ROOT_ID) ?? 0} 条
                    </p>
                  )}
                  <div className="mt-3 min-h-0 flex-1">
                    {entries.isLoading ? (
                      <p className="py-6 text-center text-caption text-muted-foreground">
                        加载知识…
                      </p>
                    ) : entries.isError ? (
                      <div className="rounded-md border border-destructive/30 px-3 py-2 text-caption text-destructive">
                        知识加载失败。
                        <Button
                          size="sm"
                          variant="outline"
                          className="mt-2"
                          onClick={() => void entries.refetch()}
                        >
                          重试
                        </Button>
                      </div>
                    ) : (entries.data?.length ?? 0) === 0 ? (
                      <div className="py-8 text-center">
                        <BookOpen className="mx-auto size-5 text-muted-foreground" />
                        <p className="mt-2 text-caption text-muted-foreground">
                          这里还没有正式知识
                        </p>
                      </div>
                    ) : (
                      <ul className="divide-y">
                        {entries.data?.map((entry) => (
                          <li key={entry.id}>
                            <button
                              type="button"
                              onClick={() => setSelectedEntry(entry)}
                              className="w-full px-1 py-2.5 text-left hover:bg-muted/60"
                            >
                              <span className="block truncate text-body-sm font-medium">
                                {entry.title}
                              </span>
                              <span className="mt-0.5 block truncate text-caption text-muted-foreground">
                                {pathNames.get(entry.node_id) ?? entry.node_name}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              )}
            </aside>
          ) : null}
        </div>
      )}
    </div>
  )
}
