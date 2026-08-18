import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Folder, FolderTree, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { TreeNodePayload } from '@/lib/api'

interface DirectoryTreeSelectProps {
  nodes: TreeNodePayload[]
  value: number | null
  allowRoot?: boolean
  loading?: boolean
  placeholder?: string
  ariaLabel?: string
  filter?: (node: TreeNodePayload) => boolean
  onSelect: (nodeId: number | null) => void
}

interface NodeEntry {
  id: number
  name: string
  depth: number
  path: string
  parentId: number | null
  entryCount: number
  hasChildren: boolean
  order: number
}

function HighlightText({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLowerCase()
  if (!needle) return <>{text}</>
  const lower = text.toLowerCase()
  const parts: ReactNode[] = []
  let index = 0
  let key = 0
  for (;;) {
    const found = lower.indexOf(needle, index)
    if (found < 0) {
      parts.push(text.slice(index))
      break
    }
    if (found > index) parts.push(text.slice(index, found))
    parts.push(
      <span key={key++} className="font-medium text-ai-candidate">
        {text.slice(found, found + needle.length)}
      </span>,
    )
    index = found + needle.length
  }
  return <>{parts}</>
}

export function DirectoryTreeSelect({
  nodes,
  value,
  allowRoot = false,
  loading = false,
  placeholder = '选择目录节点',
  ariaLabel = '目录',
  filter,
  onSelect,
}: DirectoryTreeSelectProps) {
  const [open, setOpen] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [query, setQuery] = useState('')
  const treeRef = useRef<HTMLDivElement>(null)

  const entries = useMemo(() => {
    const result: NodeEntry[] = []
    let order = 0
    const walk = (list: TreeNodePayload[], depth: number, parentId: number | null, path: string) => {
      for (const node of list) {
        if (filter && !filter(node)) continue
        const nodePath = path ? `${path} / ${node.name}` : node.name
        result.push({
          id: node.id,
          name: node.name,
          depth,
          path: nodePath,
          parentId,
          entryCount: node.entry_count,
          hasChildren: node.children.some((child) => !filter || filter(child)),
          order: order++,
        })
        walk(node.children, depth + 1, node.id, nodePath)
      }
    }
    walk(nodes, 0, null, '')
    return result
  }, [nodes, filter])

  const byId = useMemo(() => new Map(entries.map((entry) => [entry.id, entry])), [entries])
  const childrenByParent = useMemo(() => {
    const map = new Map<number | null, NodeEntry[]>()
    for (const entry of entries) {
      const list = map.get(entry.parentId) ?? []
      list.push(entry)
      map.set(entry.parentId, list)
    }
    return map
  }, [entries])
  const selectedPath = value != null ? byId.get(value)?.path ?? null : null

  const visible = useMemo(() => {
    const search = query.trim().toLowerCase()
    if (search) {
      const matched = new Set<number>()
      const ancestors = new Set<number>()
      for (const entry of entries) {
        if (entry.path.toLowerCase().includes(search)) {
          matched.add(entry.id)
          let parent = entry.parentId
          while (parent != null) {
            ancestors.add(parent)
            parent = byId.get(parent)?.parentId ?? null
          }
        }
      }
      const visibleIds = new Set([...matched, ...ancestors])
      return {
        rows: entries
          .filter((entry) => visibleIds.has(entry.id))
          .sort((left, right) => left.order - right.order)
          .map((entry) => ({
            ...entry,
            expanded: ancestors.has(entry.id) || expandedIds.has(entry.id),
          })),
        hasMatch: matched.size > 0,
      }
    }

    const rows: Array<NodeEntry & { expanded: boolean }> = []
    const walk = (entry: NodeEntry) => {
      rows.push({ ...entry, expanded: expandedIds.has(entry.id) })
      if (expandedIds.has(entry.id)) {
        for (const child of childrenByParent.get(entry.id) ?? []) walk(child)
      }
    }
    for (const entry of childrenByParent.get(null) ?? []) walk(entry)
    return { rows, hasMatch: true }
  }, [entries, byId, childrenByParent, expandedIds, query])

  function toggleExpanded(nodeId: number) {
    setExpandedIds((current) => {
      const next = new Set(current)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  useEffect(() => {
    const el = treeRef.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      const canScrollUp = el.scrollTop > 0
      const canScrollDown = el.scrollTop + el.clientHeight < el.scrollHeight
      if ((event.deltaY < 0 && canScrollUp) || (event.deltaY > 0 && canScrollDown)) {
        event.preventDefault()
        el.scrollTop += event.deltaY
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  const triggerLabel =
    selectedPath ?? (allowRoot && value == null ? '根目录' : placeholder)

  function choose(nodeId: number | null) {
    onSelect(nodeId)
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={(next) => {
      setOpen(next)
      if (!next) setQuery('')
    }}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          aria-label={ariaLabel}
          className="h-9 w-full justify-start gap-2 px-3 font-normal"
        >
          <FolderTree className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-left">{triggerLabel}</span>
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        collisionPadding={8}
        className="w-[320px] p-0"
      >
        <div className="shrink-0 border-b p-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              aria-label="搜索目录"
              placeholder="搜索目录"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-8 pl-8"
            />
          </div>
        </div>
        <div
          ref={treeRef}
          className="h-64 overflow-y-auto overscroll-contain p-1"
        >
          {loading ? (
            <div className="space-y-1.5 p-2">
              {[1, 2, 3].map((item) => (
                <div key={item} className="h-8 animate-pulse rounded bg-muted/50" />
              ))}
            </div>
          ) : entries.length === 0 ? (
            <p className="px-3 py-4 text-center text-caption text-muted-foreground">
              还没有目录节点
            </p>
          ) : visible.hasMatch ? (
            <div role="listbox" aria-label={ariaLabel}>
              {allowRoot ? (
                <DirectoryRow
                  depth={0}
                  label="根目录"
                  selected={value == null}
                  highlight={query}
                  onSelect={() => choose(null)}
                  icon={<FolderTree className="size-3.5 text-muted-foreground" />}
                />
              ) : null}
              {visible.rows.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center gap-1"
                  style={{ paddingLeft: entry.depth * 16 }}
                >
                  {entry.hasChildren ? (
                    <button
                      type="button"
                      aria-label={`${entry.expanded ? '收起' : '展开'}「${entry.name}」`}
                      onClick={() => toggleExpanded(entry.id)}
                      className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {entry.expanded ? (
                        <ChevronDown className="size-3.5" />
                      ) : (
                        <ChevronRight className="size-3.5" />
                      )}
                    </button>
                  ) : (
                    <span className="size-5 shrink-0" />
                  )}
                  <DirectoryRow
                    depth={0}
                    label={entry.name}
                    count={entry.entryCount}
                    selected={value === entry.id}
                    highlight={query}
                    onSelect={() => choose(entry.id)}
                    icon={<Folder className="size-3.5 text-muted-foreground" />}
                  />
                </div>
              ))}
            </div>
          ) : (
            <p className="px-3 py-4 text-center text-caption text-muted-foreground">
              没有匹配的目录
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

function DirectoryRow({
  depth,
  label,
  count,
  highlight,
  selected,
  onSelect,
  icon,
}: {
  depth: number
  label: string
  count?: number
  highlight?: string
  selected: boolean
  onSelect: () => void
  icon: ReactNode
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onSelect}
      style={{ paddingLeft: depth * 16 }}
      className={cn(
        'flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded px-1.5 text-body-sm',
        selected ? 'bg-brand-soft font-medium text-brand' : 'text-foreground hover:bg-muted',
      )}
    >
      {icon}
      <span className="min-w-0 flex-1 truncate text-left">
        <HighlightText text={label} query={highlight ?? ''} />
      </span>
      {count != null ? (
        <span className="shrink-0 text-caption text-muted-foreground">{count}</span>
      ) : null}
    </button>
  )
}
