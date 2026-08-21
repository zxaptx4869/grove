import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  BookOpen,
  Columns3,
  Focus,
  FoldVertical,
  Folder,
  FolderInput,
  FolderOpen,
  FolderTree,
  Search,
  UnfoldVertical,
  X,
} from 'lucide-react'

import { EntryPreviewDialog } from '@/components/features/EntryPreviewDialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  fetchEntry,
  fetchNodeEntries,
  fetchProjectTree,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const NODE_WIDTH = 200
const NODE_HEIGHT = 36
const COLUMN_GAP = 260
const ROW_GAP = 56
const MAX_VISIBLE_NODES = 60
const MAX_DEPTH = 3

interface PlacedNode {
  id: number
  name: string
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
  out: PlacedNode[],
  state: { nextSlot: number },
): void {
  for (const node of nodes) {
    if (out.length >= MAX_VISIBLE_NODES) continue
    const hasChildren = node.children.length > 0
    const collapsed = !forceExpand && collapsedIds.has(node.id)
    const childStart = out.length
    if (!collapsed && hasChildren && depth + 1 <= MAX_DEPTH) {
      placeTree(node.children, node.id, depth + 1, collapsedIds, forceExpand, counts, out, state)
    }
    const childCount = out.length - childStart
    const y =
      childCount > 0
        ? (out[childStart].y + out[out.length - 1].y) / 2
        : state.nextSlot++ * ROW_GAP
    out.push({
      id: node.id,
      name: node.name,
      depth,
      x: depth * COLUMN_GAP,
      y,
      parentId,
      entryCount: node.entry_count,
      subtreeCount: counts.get(node.id) ?? node.entry_count,
      hasChildren,
      collapsed,
    })
  }
}

/** 思维导图：项目级沉浸式目录阅读视图。 */
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
    return Number.isFinite(parsed) ? parsed : null
  })
  const [focusId, setFocusId] = useState<number | null>(null)
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<number>>(new Set())
  const [searchInput, setSearchInput] = useState('')
  const [includeSubtree, setIncludeSubtree] = useState(true)
  const [sideOpen, setSideOpen] = useState(true)
  const [previewEntryId, setPreviewEntryId] = useState<number | null>(null)

  const tree = useQuery({
    queryKey: queryKeys.projectTree(projectId),
    queryFn: () => fetchProjectTree(projectId),
    enabled: Number.isFinite(projectId),
  })

  const counts = useMemo(() => subtreeCountMap(tree.data ?? []), [tree.data])
  const pathNames = useMemo(() => pathNameMap(tree.data ?? []), [tree.data])
  const roots = useMemo(() => {
    const nodes = tree.data ?? []
    if (focusId == null) return nodes
    const path = findNodePath(nodes, focusId)
    return path ? [path[path.length - 1]] : nodes
  }, [tree.data, focusId])
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

  const placed = useMemo(() => {
    const out: PlacedNode[] = []
    const state = { nextSlot: 0 }
    placeTree(roots, null, 0, collapsedIds, searchActive, counts, out, state)
    return { out, state }
  }, [roots, collapsedIds, searchActive, counts])
  const hiddenCount = Math.max(0, totalNodeCount(roots) - placed.out.length)
  const canvasWidth = Math.max(1, ...placed.out.map((item) => item.depth + 1)) * COLUMN_GAP + 24
  const canvasHeight = placed.state.nextSlot * ROW_GAP + 48

  const selectedNode = useMemo(() => {
    if (selectedId == null) return null
    const path = findNodePath(tree.data ?? [], selectedId)
    return path ? path[path.length - 1] : null
  }, [tree.data, selectedId])

  const entries = useQuery({
    queryKey: queryKeys.nodeEntries(
      projectId,
      selectedId ?? 0,
      includeSubtree ? 'subtree' : 'direct',
    ),
    queryFn: () =>
      fetchNodeEntries(
        projectId,
        selectedId as number,
        includeSubtree ? 'subtree' : 'direct',
      ),
    enabled: sideOpen && selectedId != null,
  })
  const preview = useQuery({
    queryKey: queryKeys.readerPreview(previewEntryId ?? 0),
    queryFn: () => fetchEntry(previewEntryId as number),
    enabled: previewEntryId != null,
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
                disabled={selectedId == null}
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
            <div className="min-h-0 flex-1 overflow-auto" data-testid="mind-map-canvas">
              <div className="relative" style={{ width: canvasWidth, height: canvasHeight }}>
                <svg
                  className="absolute inset-0"
                  width={canvasWidth}
                  height={canvasHeight}
                  aria-hidden="true"
                >
                  {placed.out.map((item) => {
                    if (item.parentId == null) return null
                    const parent = placed.out.find((candidate) => candidate.id === item.parentId)
                    if (!parent) return null
                    return (
                      <line
                        key={`${parent.id}-${item.id}`}
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
                  const isSelected = item.id === selectedId
                  const isMatched = searchActive && matches.has(item.id)
                  const dimmed = searchActive && !isMatched
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setSelectedId(item.id)}
                      className={`absolute flex h-9 items-center gap-2 rounded-md border bg-card px-2.5 text-left text-body-sm shadow-sm transition-colors ${
                        isSelected
                          ? 'border-brand/60 bg-brand-soft text-foreground'
                          : 'border-border hover:bg-muted'
                      } ${isMatched ? 'ring-2 ring-brand/40' : ''} ${dimmed ? 'opacity-40' : ''}`}
                      style={{
                        left: item.x,
                        top: item.y - NODE_HEIGHT / 2,
                        width: NODE_WIDTH,
                      }}
                      title={item.name}
                      aria-pressed={isSelected}
                    >
                      {item.hasChildren && !item.collapsed ? (
                        <FolderOpen className="size-4 shrink-0 text-brand" />
                      ) : (
                        <Folder className="size-4 shrink-0 text-muted-foreground" />
                      )}
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                      <span className="shrink-0 text-caption text-muted-foreground">
                        {item.entryCount} / {item.subtreeCount}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </div>

          {sideOpen && selectedNode ? (
            <aside className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l px-4 py-4">
              <div className="min-w-0">
                <p className="text-caption text-muted-foreground">当前节点</p>
                <h2 className="mt-0.5 truncate text-body font-[650]">{selectedNode.name}</h2>
                <p className="mt-0.5 truncate text-caption text-muted-foreground">
                  {pathNames.get(selectedNode.id) ?? selectedNode.name}
                </p>
              </div>
              <Button asChild size="sm" variant="ghost" className="mt-2 w-full justify-start px-2">
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
                          onClick={() => setPreviewEntryId(entry.id)}
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
            </aside>
          ) : null}
        </div>
      )}

      <EntryPreviewDialog
        open={previewEntryId != null}
        entry={preview.data ?? null}
        onOpenChange={(open) => !open && setPreviewEntryId(null)}
      />
    </div>
  )
}
