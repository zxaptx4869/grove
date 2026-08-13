import { useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderInput,
  FolderOpen,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { TreeNodePayload } from '@/lib/api'

export interface NodeTreeCallbacks {
  onAddChild: (parent: TreeNodePayload | null) => void
  onRename: (node: TreeNodePayload) => void
  onDelete: (node: TreeNodePayload) => void
  onMove: (node: TreeNodePayload) => void
  onReorder: (parentId: number | null, orderedIds: number[]) => void
}

export interface NodeTreeProps {
  nodes: readonly TreeNodePayload[]
  callbacks: NodeTreeCallbacks
  selectedId?: number | null
  onSelect?: (node: TreeNodePayload) => void
}

/** 目录树只呈现层级与名称，低频编辑操作统一收进节点菜单。 */
export function NodeTree({ nodes, callbacks, selectedId = null, onSelect }: NodeTreeProps) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set())
  const [draggingId, setDraggingId] = useState<number | null>(null)

  function toggle(nodeId: number) {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (next.has(nodeId)) next.delete(nodeId)
      else next.add(nodeId)
      return next
    })
  }

  function swapIds(items: readonly TreeNodePayload[], from: number, to: number) {
    const ids = items.map((item) => item.id)
    ;[ids[from], ids[to]] = [ids[to], ids[from]]
    return ids
  }

  function handleDrop(targetId: number, parentId: number | null, siblings: readonly TreeNodePayload[]) {
    if (draggingId === null || draggingId === targetId) {
      setDraggingId(null)
      return
    }
    const ids = siblings.map((item) => item.id)
    const from = ids.indexOf(draggingId)
    const to = ids.indexOf(targetId)
    if (from === -1 || to === -1) {
      setDraggingId(null)
      return
    }
    ids.splice(from, 1)
    ids.splice(to, 0, draggingId)
    callbacks.onReorder(parentId, ids)
    setDraggingId(null)
  }

  function renderItems(items: readonly TreeNodePayload[], parentId: number | null, depth: number) {
    return items.map((node, index) => {
      const isCollapsed = collapsed.has(node.id)
      const hasChildren = node.children.length > 0
      const isSelected = selectedId === node.id

      return (
        <div
          key={node.id}
          draggable
          onDragStart={() => setDraggingId(node.id)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => handleDrop(node.id, parentId, items)}
        >
          <div
            className={`group flex h-9 items-center rounded-md pr-1 ${isSelected ? 'bg-brand-soft text-foreground' : 'hover:bg-muted/80'}`}
            style={{ paddingLeft: depth * 16 + 4 }}
          >
            <button
              type="button"
              className="flex size-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-black/5 disabled:opacity-30"
              onClick={() => toggle(node.id)}
              disabled={!hasChildren}
              aria-label={isCollapsed ? `展开 ${node.name}` : `折叠 ${node.name}`}
            >
              {hasChildren ? (isCollapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />) : <span className="size-3.5" />}
            </button>
            {isCollapsed || !hasChildren ? <Folder className="mr-2 size-4 shrink-0 text-muted-foreground" /> : <FolderOpen className="mr-2 size-4 shrink-0 text-brand" />}
            <button
              type="button"
              className="min-w-0 flex-1 truncate text-left text-body-sm"
              onClick={() => onSelect?.(node)}
              aria-selected={isSelected}
              title={node.description || node.name}
            >
              {node.name}
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon-xs" variant="ghost" className="opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100" aria-label={`${node.name} 更多操作`}><MoreHorizontal /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-40">
                <DropdownMenuItem onSelect={() => callbacks.onAddChild(node)}><Plus />添加子节点</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => callbacks.onRename(node)}><Pencil />编辑节点</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => callbacks.onMove(node)}><FolderInput />移动到…</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={index === 0} onSelect={() => callbacks.onReorder(parentId, swapIds(items, index, index - 1))}><ArrowUp />上移</DropdownMenuItem>
                <DropdownMenuItem disabled={index === items.length - 1} onSelect={() => callbacks.onReorder(parentId, swapIds(items, index, index + 1))}><ArrowDown />下移</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={() => callbacks.onDelete(node)}><Trash2 />删除节点</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
          {!isCollapsed && hasChildren ? renderItems(node.children, node.id, depth + 1) : null}
        </div>
      )
    })
  }

  return <div className="space-y-0.5">{renderItems(nodes, null, 0)}</div>
}
