import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { BookOpen, FolderInput, FolderTree } from 'lucide-react'

import { EntryPopover } from '@/components/features/EntryPopover'
import { Button } from '@/components/ui/button'
import {
  fetchNodeEntries,
  fetchProjectEntries,
  fetchProjectTree,
  type EntryPayload,
  type TreeNodePayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const SIZE = 720
const CX = SIZE / 2
const CY = SIZE / 2
const PALETTE = ['#256b43', '#2f7d4f', '#4b9a6a', '#7fbf9b', '#9fd4b6', '#c3e4d1']
const PROJECT_ROOT_ID = -1
const MIN_ZOOM = 120
const MAX_SLICES = 300

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

interface ViewBox {
  x: number
  y: number
  w: number
  h: number
}

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

function subtreeDepth(node: SunNode): number {
  return node.children.reduce((max, child) => Math.max(max, subtreeDepth(child) + 1), 0)
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

function fullCirclePath(r: number): string {
  const [x0, y0] = polar(CX, CY, r, 0)
  const [x1, y1] = polar(CX, CY, r, Math.PI)
  return `M ${x0} ${y0} A ${r} ${r} 0 1 1 ${x1} ${y1} A ${r} ${r} 0 1 1 ${x0} ${y0} Z`
}

/** 旭日图模式：全局结构/知识密度浏览，支持钻取、缩放与大纲联动。 */
export function SunburstPanel({
  projectId,
  projectName,
  initialNodeId,
  sideOpen,
  onOpenInMindMap,
}: {
  projectId: number
  projectName: string
  initialNodeId?: number | null
  sideOpen: boolean
  onOpenInMindMap: (nodeId: number) => void
}) {
  const [rootId, setRootId] = useState<number>(PROJECT_ROOT_ID)
  const [selectedId, setSelectedId] = useState<number>(() => {
    const raw = initialNodeId
    return raw != null && Number.isFinite(raw) ? raw : PROJECT_ROOT_ID
  })
  const [pinnedEntry, setPinnedEntry] = useState<EntryPayload | null>(null)
  const [pinnedPos, setPinnedPos] = useState<{ x: number; y: number } | null>(null)
  const [previewEntry, setPreviewEntry] = useState<EntryPayload | null>(null)
  const [previewPos, setPreviewPos] = useState<{ x: number; y: number } | null>(null)
  const [hoverIds, setHoverIds] = useState<number[] | null>(null)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const [view, setView] = useState<ViewBox>({ x: 0, y: 0, w: SIZE, h: SIZE })
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{ x: number; y: number } | null>(null)

  const tree = useQuery({
    queryKey: queryKeys.projectTree(projectId),
    queryFn: () => fetchProjectTree(projectId),
    enabled: Number.isFinite(projectId),
  })

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
  const ringHeight = Math.max(
    24,
    Math.floor((SIZE / 2 - 14) / (currentRoot ? subtreeDepth(currentRoot) + 1 : 1)),
  )

  const entries = useQuery({
    queryKey:
      selectedId === PROJECT_ROOT_ID
        ? queryKeys.projectEntries(projectId)
        : queryKeys.nodeEntries(projectId, selectedId, 'direct'),
    queryFn: () =>
      selectedId === PROJECT_ROOT_ID
        ? fetchProjectEntries(projectId)
        : fetchNodeEntries(projectId, selectedId, 'direct'),
    enabled: Number.isFinite(projectId) && selectedNode != null,
  })

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = svg.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return
      const px = event.clientX - rect.left
      const py = event.clientY - rect.top
      setView((current) => {
        const factor = Math.exp(-event.deltaY * 0.0015)
        const nw = Math.max(MIN_ZOOM, Math.min(SIZE, current.w * factor))
        const nh = nw
        const sx = current.x + (px / rect.width) * current.w
        const sy = current.y + (py / rect.height) * current.h
        return {
          x: sx - (px / rect.width) * nw,
          y: sy - (py / rect.height) * nh,
          w: nw,
          h: nh,
        }
      })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  function zoomAroundCenter(factor: number) {
    setView((current) => {
      const nw = Math.max(MIN_ZOOM, Math.min(SIZE, current.w * factor))
      return {
        x: current.x + (current.w - nw) / 2,
        y: current.y + (current.h - nw) / 2,
        w: nw,
        h: nw,
      }
    })
  }

  function resetView() {
    setView({ x: 0, y: 0, w: SIZE, h: SIZE })
  }

  function drill(node: SunNode) {
    let next: SunNode = node
    if (node.id === rootId) {
      next = node.ancestors.at(-1) ?? projectRoot!
    }
    setRootId(next.id)
    setSelectedId(next.id)
    setPinnedEntry(null)
    setPinnedPos(null)
  }

  function pinEntry(entry: EntryPayload, event: React.MouseEvent<HTMLElement>) {
    setSelectedId(entry.node_id)
    setPinnedEntry((current) => (current?.id === entry.id ? null : entry))
    const rect = event.currentTarget.getBoundingClientRect()
    setPinnedPos({ x: rect.left, y: rect.top })
  }

  function previewEntryAt(entry: EntryPayload, event: React.MouseEvent<HTMLElement>) {
    setPreviewEntry(entry)
    const rect = event.currentTarget.getBoundingClientRect()
    setPreviewPos({ x: rect.left, y: rect.top })
  }

  function renderSlices(node: SunNode, start: number, span: number, depth: number): ReactNode[] {
    const parts: ReactNode[] = []
    const total = Math.max(node.subtreeCount, 1)
    const r0 = depth * ringHeight
    const r1 = (depth + 1) * ringHeight
    const color = PALETTE[Math.min(depth, PALETTE.length - 1)]
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

    const isFullCircle = span >= Math.PI * 2 - 0.001
    parts.push(
      <path
        key={`${node.id}-main`}
        d={
          isFullCircle
            ? r0 === 0
              ? fullCirclePath(r1)
              : `${fullCirclePath(r1)} ${fullCirclePath(r0)}`
            : arcPath(r0, r1, start, start + span)
        }
        fill={color}
        fillRule={isFullCircle ? 'evenodd' : undefined}
        stroke="#ffffff"
        strokeWidth={1}
        className={baseClass}
        {...handlers}
      />,
    )

    const childSpan = span - (span * node.directCount) / total
    if (childSpan > 0 && node.children.length > 0) {
      const childTotal = Math.max(
        node.children.reduce((sum, child) => sum + child.subtreeCount, 0),
        1,
      )
      let cursor = start + (span - childSpan)
      node.children.forEach((child) => {
        const part = (childSpan * child.subtreeCount) / childTotal
        parts.push(...renderSlices(child, cursor, part, depth + 1))
        cursor += part
      })
    }

    const midR = (r0 + r1) / 2
    const arcLength = midR * span
    const isHovered = hoverIds?.includes(node.id) ?? false
    if (arcLength > (isHovered ? 14 : 30) && span > (isHovered ? 0.04 : 0.1)) {
      const mid = start + span / 2
      const [lx, ly] = polar(CX, CY, midR, mid)
      const maxChars = Math.max(2, Math.min(8, Math.floor(arcLength / 7)))
      const label = node.name.length > maxChars ? node.name.slice(0, maxChars) : node.name
      parts.push(
        <text
          key={`${node.id}-label`}
          x={lx}
          y={ly + 3}
          textAnchor="middle"
          className={`pointer-events-none select-none text-[11px] font-medium ${
            depth >= 4 ? 'fill-[#1f5137]' : 'fill-[#f3faf6]'
          }`}
        >
          {label}
        </text>,
      )
    }
    return parts
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
        <p className="text-body-sm">旭日图加载失败，请重试。</p>
        <Button className="mt-3" variant="outline" size="sm" onClick={() => void tree.refetch()}>
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
            <Link to={`/projects/${projectId}?view=directory`}>去知识空间</Link>
          </Button>
        </div>
      </div>
    )
  }

  const activeRoot = currentRoot ?? projectRoot
  const slices = renderSlices(activeRoot, 0, Math.PI * 2, 0)
  const totalSlices = slices.length
  const overCap = totalSlices > MAX_SLICES

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2">
          <Button size="sm" variant="outline" onClick={() => zoomAroundCenter(1.25)}>
            放大
          </Button>
          <Button size="sm" variant="outline" onClick={() => zoomAroundCenter(0.8)}>
            缩小
          </Button>
          <Button size="sm" variant="outline" onClick={resetView}>
            适应窗口
          </Button>
          {activeRoot !== projectRoot ? (
            <div className="flex min-w-0 items-center gap-1 text-caption text-muted-foreground">
              <button
                type="button"
                className="shrink-0 hover:text-foreground"
                onClick={() => drill(projectRoot)}
              >
                项目根
              </button>
              {activeRoot.ancestors.map((ancestor) => (
                <span key={ancestor.id} className="flex min-w-0 items-center gap-1">
                  <span className="shrink-0">/</span>
                  <button
                    type="button"
                    className="truncate hover:text-foreground"
                    onClick={() => drill(ancestor)}
                  >
                    {ancestor.name}
                  </button>
                </span>
              ))}
              <span className="shrink-0">/</span>
              <span className="truncate text-foreground">{activeRoot.name}</span>
            </div>
          ) : null}
          {overCap ? (
            <span className="text-caption text-muted-foreground">
              扇区较多，建议钻取查看
            </span>
          ) : null}
          <span className="ml-auto text-caption text-muted-foreground">
            滚轮缩放 · 拖拽平移
          </span>
        </div>
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <svg
            ref={svgRef}
            className="block h-full w-full cursor-grab active:cursor-grabbing"
            viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
            preserveAspectRatio="xMidYMid meet"
            onMouseDown={(event) => {
              dragRef.current = { x: event.clientX, y: event.clientY }
            }}
            onMouseMove={(event) => {
              if (!dragRef.current) return
              const rect = event.currentTarget.getBoundingClientRect()
              const dx = (event.clientX - dragRef.current.x) * (view.w / rect.width)
              const dy = (event.clientY - dragRef.current.y) * (view.h / rect.height)
              dragRef.current = { x: event.clientX, y: event.clientY }
              setView((current) => ({ ...current, x: current.x - dx, y: current.y - dy }))
            }}
            onMouseUp={() => {
              dragRef.current = null
            }}
            onMouseLeave={() => {
              dragRef.current = null
            }}
          >
            {slices}
          </svg>
        </div>
      </div>

      {sideOpen ? (
        <aside
          aria-label="全景侧栏"
          className="flex w-[300px] shrink-0 flex-col overflow-y-auto border-l px-4 py-4"
        >
          <p className="text-caption text-muted-foreground">目录大纲</p>
          <div className="mt-1 max-h-[34%] min-h-0 overflow-y-auto rounded-md border p-1.5">
            {activeRoot !== projectRoot ? (
              <button
                type="button"
                className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-body-sm text-muted-foreground hover:bg-muted"
                onClick={() => drill(projectRoot)}
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
                onSelect={drill}
              />
            ))}
          </div>
          <div className="min-w-0">
            <p className="text-caption text-muted-foreground">当前节点</p>
            <h2 className="mt-0.5 truncate text-body font-[650]">{selectedNode?.name ?? ''}</h2>
            <p className="mt-0.5 truncate text-caption text-muted-foreground">
              {selectedNode?.path ?? ''}
            </p>
          </div>
          {selectedNode && selectedNode.id !== PROJECT_ROOT_ID ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                className="mt-2 w-full justify-start px-2"
                onClick={() => onOpenInMindMap(selectedNode.id)}
              >
                在思维导图中查看
              </Button>
              <Button asChild size="sm" variant="ghost" className="w-full justify-start px-2">
                <Link to={`/projects/${projectId}?view=directory&node=${selectedNode.id}`}>
                  <FolderInput />
                  在知识空间中打开
                </Link>
              </Button>
            </>
          ) : null}
          <p className="mt-4 text-caption text-muted-foreground">
            {selectedId === PROJECT_ROOT_ID
              ? '项目全部知识'
              : `${selectedNode?.name ?? ''} · 直接知识 ${selectedNode?.directCount ?? 0} 条`}
          </p>
          <div className="mt-2 min-h-0 flex-1">
            {entries.isLoading ? (
              <p className="py-6 text-center text-caption text-muted-foreground">加载知识…</p>
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
                <p className="mt-2 text-caption text-muted-foreground">这里还没有正式知识</p>
              </div>
            ) : (
              <ul className="space-y-2">
                {entries.data?.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={(event) => pinEntry(entry, event)}
                      onMouseEnter={(event) => previewEntryAt(entry, event)}
                      onMouseLeave={() => setPreviewEntry(null)}
                      className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                        pinnedEntry?.id === entry.id
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
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      ) : null}

      {tooltip ? (
        <div
          className="pointer-events-none fixed z-50 max-w-[260px] rounded-md bg-foreground px-2.5 py-2 text-body-sm text-background shadow-lg"
          style={{ left: tooltip.x + 14, top: tooltip.y + 14 }}
        >
          <strong>{tooltip.node.name}</strong>
          <div className="text-caption opacity-80">{tooltip.node.path}</div>
          <div className="text-caption opacity-80">
            直接 {tooltip.node.directCount} · 后代{' '}
            {tooltip.node.subtreeCount - tooltip.node.directCount} · 合计{' '}
            {tooltip.node.subtreeCount}
          </div>
        </div>
      ) : null}

      {pinnedEntry && pinnedPos ? (
        <EntryPopover
          entry={pinnedEntry}
          position={pinnedPos}
          pinned
          onClose={() => {
            setPinnedEntry(null)
            setPinnedPos(null)
          }}
        />
      ) : previewEntry && previewPos ? (
        <EntryPopover
          entry={previewEntry}
          position={previewPos}
          pinned={false}
          onClose={() => undefined}
        />
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
          node.id === selectedId
            ? 'bg-brand-soft text-brand'
            : 'text-foreground hover:bg-muted'
        }`}
        style={{ paddingLeft: 8 + depth * 16 }}
      >
        <span className="truncate">{node.name}</span>
        <span className="ml-auto shrink-0 text-caption text-muted-foreground">
          直 {node.directCount} · 后 {node.subtreeCount - node.directCount}
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
