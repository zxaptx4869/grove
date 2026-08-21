import { useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, FolderTree } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  fetchNodeEntries,
  fetchProjectEntries,
  fetchProjects,
  fetchProjectTree,
  type ProjectStatus,
  type EntryPayload,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const PROJECT_STATUSES: ProjectStatus[] = ['active', 'paused', 'completed', 'archived']
const SIZE = 620
const CX = SIZE / 2
const CY = SIZE / 2
const RING = 118
const PALETTE = ['#2f7d4f', '#4b9a6a', '#7fbf9b', '#b7dcc8']
const DIRECT_COLOR = '#1f5137'
const PROJECT_ROOT_ID = -1

interface SunNode {
  id: number
  name: string
  directCount: number
  subtreeCount: number
  children: SunNode[]
  ancestors: SunNode[]
  path: string
}

interface TooltipState {
  x: number
  y: number
  node: SunNode
}

/** 从真实目录树构建旭日图节点（含祖先链与子树计数）。 */
function buildSunNodes(
  nodes: readonly TreeNodePayload[],
  ancestors: SunNode[] = [],
  pathParts: string[] = [],
): SunNode[] {
  return nodes.map((node) => {
    const current: SunNode = {
      id: node.id,
      name: node.name,
      directCount: node.entry_count,
      children: [],
      ancestors,
      path: pathParts.concat(node.name).join(' / '),
      subtreeCount: 0,
    }
    current.children = buildSunNodes(
      node.children,
      ancestors.concat(current),
      pathParts.concat(node.name),
    )
    current.subtreeCount =
      current.directCount +
      current.children.reduce((sum, child) => sum + child.subtreeCount, 0)
    return current
  })
}

function findSunNode(nodes: readonly SunNode[], id: number): SunNode | null {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findSunNode(node.children, id)
    if (found) return found
  }
  return null
}

function polar(cx: number, cy: number, r: number, angle: number): [number, number] {
  return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)]
}

function arcPath(r0: number, r1: number, a0: number, a1: number): string {
  const large = a1 - a0 > Math.PI ? 1 : 0
  const [x0, y0] = polar(CX, CY, r0, a0)
  const [x1, y1] = polar(CX, CY, r0, a1)
  const [x2, y2] = polar(CX, CY, r1, a1)
  const [x3, y3] = polar(CX, CY, r1, a0)
  return [
    `M ${x0} ${y0}`,
    `A ${r0} ${r0} 0 ${large} 1 ${x1} ${y1}`,
    `L ${x2} ${y2}`,
    `A ${r1} ${r1} 0 ${large} 0 ${x3} ${y3}`,
    'Z',
  ].join(' ')
}

/** 探索原型：旭日图全局视图 + 目录大纲联动阅读，使用真实项目数据。 */
export function KnowledgeOverviewPrototype() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const [rootId, setRootId] = useState<number>(PROJECT_ROOT_ID)
  const [selectedId, setSelectedId] = useState<number>(PROJECT_ROOT_ID)
  const [selectedEntry, setSelectedEntry] = useState<EntryPayload | null>(null)
  const [hoverIds, setHoverIds] = useState<number[] | null>(null)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  const projects = useQuery({
    queryKey: [...queryKeys.projects, 'all-statuses'],
    queryFn: async () =>
      (await Promise.all(PROJECT_STATUSES.map((status) => fetchProjects(status)))).flat(),
    enabled: Number.isFinite(id),
    staleTime: 30_000,
  })
  const tree = useQuery({
    queryKey: queryKeys.projectTree(id),
    queryFn: () => fetchProjectTree(id),
    enabled: Number.isFinite(id),
  })
  const projectName =
    projects.data?.find((project) => project.id === id)?.name ?? '项目'

  const sunRoots = useMemo(() => buildSunNodes(tree.data ?? []), [tree.data])
  const projectRoot = useMemo<SunNode | null>(() => {
    if (sunRoots.length === 0) return null
    return {
      id: PROJECT_ROOT_ID,
      name: projectName,
      directCount: 0,
      subtreeCount: sunRoots.reduce((sum, node) => sum + node.subtreeCount, 0),
      children: sunRoots,
      ancestors: [],
      path: projectName,
    }
  }, [sunRoots, projectName])

  const currentRoot = useMemo(() => {
    if (rootId === PROJECT_ROOT_ID) return projectRoot
    return findSunNode(sunRoots, rootId)
  }, [rootId, projectRoot, sunRoots])
  const selectedNode = useMemo(() => {
    if (selectedId === PROJECT_ROOT_ID) return projectRoot
    return findSunNode(sunRoots, selectedId)
  }, [selectedId, projectRoot, sunRoots])

  const entries = useQuery({
    queryKey:
      selectedId === PROJECT_ROOT_ID
        ? queryKeys.projectEntries(id)
        : queryKeys.nodeEntries(id, selectedId, 'direct'),
    queryFn: () =>
      selectedId === PROJECT_ROOT_ID
        ? fetchProjectEntries(id)
        : fetchNodeEntries(id, selectedId, 'direct'),
    enabled: Number.isFinite(id) && selectedNode != null,
  })

  function drill(node: SunNode) {
    let next: SunNode = node
    if (node.id === rootId) {
      next = node.ancestors.at(-1) ?? projectRoot!
    }
    setRootId(next.id)
    setSelectedId(next.id)
    setSelectedEntry(null)
  }

  function renderSlices(node: SunNode, start: number, span: number, depth: number): ReactNode[] {
    const parts: ReactNode[] = []
    const total = Math.max(node.subtreeCount, 1)
    const r0 = depth * RING
    const r1 = (depth + 1) * RING
    const color = PALETTE[Math.min(depth, PALETTE.length - 1)]
    let cursor = start
    const dimmed = hoverIds != null && !hoverIds.includes(node.id)
    const baseClass = `cursor-pointer transition-opacity duration-100 ${
      dimmed ? 'opacity-25' : 'opacity-100'
    }`

    const handlers = {
      onMouseEnter: () => {
        setHoverIds([...node.ancestors.map((ancestor) => ancestor.id), node.id])
      },
      onMouseMove: (event: React.MouseEvent<SVGPathElement>) =>
        setTooltip({ x: event.clientX, y: event.clientY, node }),
      onMouseLeave: () => {
        setHoverIds(null)
        setTooltip(null)
      },
      onClick: () => drill(node),
    }

    // 节点主体扇区：宽度 = 该节点子树知识量
    parts.push(
      <path
        key={`${node.id}-main`}
        d={arcPath(r0, r1, start, start + span)}
        fill={color}
        stroke="#ffffff"
        strokeWidth={1}
        className={baseClass}
        {...handlers}
      />,
    )
    // 直接知识：扇区起始处的深色楔形
    if (node.directCount > 0) {
      const directSpan = (span * node.directCount) / total
      parts.push(
        <path
          key={`${node.id}-direct`}
          d={arcPath(r0, r1, start, start + directSpan)}
          fill={DIRECT_COLOR}
          stroke="#ffffff"
          strokeWidth={1}
          className={baseClass}
          aria-label={`${node.name} 直接知识 ${node.directCount} 条`}
          {...handlers}
        />,
      )
      cursor += directSpan
    }

    const childSpan = span - (span * node.directCount) / total
    if (childSpan > 0 && node.children.length > 0) {
      const childTotal = Math.max(
        node.children.reduce((sum, child) => sum + child.subtreeCount, 0),
        1,
      )
      node.children.forEach((child) => {
        const part = (childSpan * child.subtreeCount) / childTotal
        parts.push(...renderSlices(child, cursor, part, depth + 1))
        cursor += part
      })
    }

    const angleDeg = (span * 180) / Math.PI
    if (angleDeg > 10) {
      const mid = start + span / 2
      const midR = (r0 + r1) / 2
      const [lx, ly] = polar(CX, CY, midR, mid)
      parts.push(
        <text
          key={`${node.id}-label`}
          x={lx}
          y={ly + 3}
          textAnchor="middle"
          className="pointer-events-none select-none fill-[#f3faf6] text-[11px] font-medium"
        >
          {node.name.length > 6 ? node.name.slice(0, 6) : node.name}
        </text>,
      )
    }
    return parts
  }

  if (!Number.isFinite(id)) {
    return <div className="p-6 text-body-sm text-destructive">项目地址无效。</div>
  }
  if (tree.isLoading || projects.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-body-sm text-muted-foreground">
        正在加载项目数据…
      </div>
    )
  }
  if (tree.isError || projects.isError) {
    return (
      <div className="m-6 border-l-2 border-destructive px-4 py-3">
        <p className="text-body-sm">加载失败，请重试。</p>
        <Button
          className="mt-3"
          variant="outline"
          size="sm"
          onClick={() => {
            void tree.refetch()
            void projects.refetch()
          }}
        >
          重试
        </Button>
      </div>
    )
  }
  if (!projectRoot) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="max-w-[380px] text-center">
          <FolderTree className="mx-auto size-5 text-muted-foreground" />
          <h2 className="mt-3 text-body font-[650]">目录还是空的</h2>
          <p className="mt-1 text-body-sm leading-6 text-muted-foreground">
            先建立目录并整理知识，再回来看全局全景。
          </p>
          <Button asChild className="mt-5" size="sm" variant="outline">
            <Link to={`/projects/${id}?view=directory`}>去知识空间</Link>
          </Button>
        </div>
      </div>
    )
  }

  const activeRoot = currentRoot ?? projectRoot
  const slices = renderSlices(activeRoot, 0, Math.PI * 2, 0)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-[52px] shrink-0 items-center justify-between gap-3 border-b px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Button asChild size="sm" variant="ghost">
            <Link to={`/projects/${id}?view=directory`}>
              <ArrowLeft />
              返回知识空间
            </Link>
          </Button>
          <h1 className="truncate text-body font-[650]">{projectName} · 知识全景</h1>
          <span className="rounded-md bg-muted px-1.5 py-0.5 text-caption text-muted-foreground">
            探索原型 · 临时页面
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1 text-caption text-muted-foreground">
          {activeRoot === projectRoot ? (
            <span className="font-medium text-foreground">项目根</span>
          ) : (
            <>
              <button
                type="button"
                className="hover:text-foreground"
                onClick={() => {
                  setRootId(PROJECT_ROOT_ID)
                  setSelectedId(PROJECT_ROOT_ID)
                  setSelectedEntry(null)
                }}
              >
                项目根
              </button>
              {activeRoot.ancestors.map((ancestor) => (
                <span key={ancestor.id} className="flex items-center gap-1">
                  <span>/</span>
                  <button
                    type="button"
                    className="hover:text-foreground"
                    onClick={() => drill(ancestor)}
                  >
                    {ancestor.name}
                  </button>
                </span>
              ))}
              <span>/</span>
              <span className="font-medium text-foreground">{activeRoot.name}</span>
            </>
          )}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_320px]">
        <div className="relative min-w-0 overflow-hidden p-4">
          <svg
            className="mx-auto block"
            width={SIZE}
            height={SIZE}
            viewBox={`0 0 ${SIZE} ${SIZE}`}
          >
            {slices}
          </svg>
          <div className="absolute bottom-4 left-5 flex items-center gap-3 rounded-md border bg-card/85 px-3 py-1.5 text-caption text-muted-foreground">
            <span className="flex items-center gap-1">
              <i className="size-2 rounded-full bg-[#2f7d4f]" />
              深度 1
            </span>
            <span className="flex items-center gap-1">
              <i className="size-2 rounded-full bg-[#4b9a6a]" />
              深度 2
            </span>
            <span className="flex items-center gap-1">
              <i className="size-2 rounded-full bg-[#7fbf9b]" />
              深度 3
            </span>
            <span className="flex items-center gap-1">
              <i className="size-2 rounded-full bg-[#1f5137]" />
              直接知识
            </span>
            <span>扇区宽度 = 子树知识量</span>
          </div>
        </div>

        <aside className="flex min-h-0 flex-col border-l bg-card">
          <section className="flex max-h-[42%] min-h-0 flex-col px-4 pb-3 pt-4">
            <p className="mb-2 text-caption text-muted-foreground">
              目录大纲（点击联动旭日图）
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto rounded-md border p-1.5">
              {activeRoot !== projectRoot ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-body-sm text-muted-foreground hover:bg-muted"
                  onClick={() => {
                    setRootId(PROJECT_ROOT_ID)
                    setSelectedId(PROJECT_ROOT_ID)
                    setSelectedEntry(null)
                  }}
                >
                  ← 项目根
                </button>
              ) : null}
              {activeRoot.children.map((child) => (
                <OutlineRow
                  key={child.id}
                  node={child}
                  depth={activeRoot === projectRoot ? 0 : 1}
                  selectedId={selectedId}
                  onSelect={(node) => drill(node)}
                />
              ))}
            </div>
          </section>

          <section className="flex min-h-0 flex-1 flex-col px-4 py-3">
            <p className="mb-2 text-caption text-muted-foreground">
              {selectedId === PROJECT_ROOT_ID
                ? '项目全部知识'
                : `${selectedNode?.name ?? ''} · 直接知识 ${selectedNode?.directCount ?? 0} 条`}
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto">
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
                <ul className="space-y-2">
                  {entries.data?.map((entry) => (
                    <li key={entry.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedEntry(entry)}
                        className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                          selectedEntry?.id === entry.id
                            ? 'border-brand bg-brand-soft'
                            : 'border-border hover:bg-muted'
                        }`}
                      >
                        <span className="text-caption font-semibold text-brand">
                          {entry.main_type}
                        </span>
                        <span className="mt-0.5 block text-body-sm font-medium">
                          {entry.title}
                        </span>
                        <span className="mt-0.5 block truncate text-caption text-muted-foreground">
                          {selectedNode?.path ?? ''}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {selectedEntry ? (
                <div className="mt-4 border-t pt-3">
                  <h3 className="text-body font-[650]">{selectedEntry.title}</h3>
                  <p className="mt-2 whitespace-pre-wrap text-body-sm leading-6">
                    {selectedEntry.content}
                  </p>
                  {selectedEntry.applicable_condition ? (
                    <p className="mt-2 text-body-sm text-muted-foreground">
                      适用条件：{selectedEntry.applicable_condition}
                    </p>
                  ) : null}
                  {selectedEntry.evidences.length > 0 ? (
                    <div className="mt-3 space-y-1">
                      {selectedEntry.evidences.map((evidence) => (
                        <p key={evidence.id} className="border-l-2 pl-2 text-caption text-muted-foreground">
                          来源：{evidence.source_title}
                        </p>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          </section>
        </aside>
      </div>

      {tooltip ? (
        <div
          className="pointer-events-none fixed z-50 max-w-[260px] rounded-md bg-foreground px-2.5 py-2 text-body-sm text-background shadow-lg"
          style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
        >
          <strong>{tooltip.node.name}</strong>
          <div className="text-caption opacity-80">{tooltip.node.path}</div>
          <div className="text-caption opacity-80">
            直接 {tooltip.node.directCount} 条 · 子树 {tooltip.node.subtreeCount} 条
          </div>
        </div>
      ) : null}
    </div>
  )
}

function OutlineRow({
  node,
  depth,
  selectedId,
  onSelect,
}: {
  node: SunNode
  depth: number
  selectedId: number
  onSelect: (node: SunNode) => void
}) {
  return (
    <>
      <button
        type="button"
        onClick={() => onSelect(node)}
        className={`flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-body-sm ${
          node.id === selectedId ? 'bg-brand-soft text-brand' : 'text-foreground hover:bg-muted'
        }`}
        style={{ paddingLeft: 8 + depth * 16 }}
      >
        <span className="truncate">{node.name}</span>
        <span className="ml-auto shrink-0 text-caption text-muted-foreground">
          {node.directCount} / {node.subtreeCount}
        </span>
      </button>
      {node.children.map((child) => (
        <OutlineRow
          key={child.id}
          node={child}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      ))}
    </>
  )
}
