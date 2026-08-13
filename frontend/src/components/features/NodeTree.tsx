import { useState } from 'react'
import { Button } from '@/components/ui/button'
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
  /** 当前选中节点（受控），用于内容区联动 */
  selectedId?: number | null
  onSelect?: (node: TreeNodePayload) => void
}

/**
 * 目录树真组件（数据驱动）：展开/折叠、增删改、排序。
 * 排序支持原生拖拽（桌面）与上移/下移按钮（键盘/触屏可达）。
 */
export function NodeTree({
  nodes,
  callbacks,
  selectedId = null,
  onSelect,
}: NodeTreeProps) {
  const [collapsed, setCollapsed] = useState<ReadonlySet<number>>(new Set())
  const [draggingId, setDraggingId] = useState<number | null>(null)

  function toggle(nodeId: number) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(nodeId)) {
        next.delete(nodeId)
      } else {
        next.add(nodeId)
      }
      return next
    })
  }

  function swapIds(items: readonly TreeNodePayload[], from: number, to: number): number[] {
    const ids = items.map((item) => item.id)
    ;[ids[from], ids[to]] = [ids[to], ids[from]]
    return ids
  }

  function move(
    index: number,
    direction: -1 | 1,
    parentId: number | null,
    siblings: readonly TreeNodePayload[],
  ) {
    callbacks.onReorder(parentId, swapIds(siblings, index, index + direction))
  }

  function handleDrop(
    targetId: number,
    parentId: number | null,
    siblings: readonly TreeNodePayload[],
  ) {
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

  function renderItems(
    items: readonly TreeNodePayload[],
    parentId: number | null,
    depth: number,
  ) {
    return items.map((node, index) => {
      const isCollapsed = collapsed.has(node.id)
      return (
        <div
          key={node.id}
          draggable
          onDragStart={() => setDraggingId(node.id)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => handleDrop(node.id, parentId, items)}
        >
          <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md px-2 py-1.5 hover:bg-muted"
            style={{ paddingLeft: depth * 16 + 8 }}
          >
            <button
              type="button"
              className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-muted-foreground/10 disabled:opacity-30"
              onClick={() => toggle(node.id)}
              disabled={node.children.length === 0}
              aria-label={isCollapsed ? `展开 ${node.name}` : `折叠 ${node.name}`}
            >
              {node.children.length > 0 ? (isCollapsed ? '▸' : '▾') : '·'}
            </button>
            <button
              type="button"
              className={`min-w-0 flex-1 truncate rounded px-1 py-0.5 text-left text-body-sm font-medium ${
                selectedId === node.id ? 'bg-ai-candidate-soft text-ai-candidate' : ''
              }`}
              onClick={() => onSelect?.(node)}
              aria-selected={selectedId === node.id}
            >
              {node.name}
            </button>
            <div className="ml-auto flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => callbacks.onAddChild(node)}
                aria-label={`给 ${node.name} 添加子节点`}
              >
                加子
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => callbacks.onRename(node)}
                aria-label={`重命名 ${node.name}`}
              >
                改
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => callbacks.onMove(node)}
                aria-label={`移动 ${node.name}`}
              >
                移
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => callbacks.onDelete(node)}
                aria-label={`删除 ${node.name}`}
              >
                删
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={index === 0}
                onClick={() => move(index, -1, parentId, items)}
                aria-label={`上移 ${node.name}`}
              >
                ↑
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={index === items.length - 1}
                onClick={() => move(index, 1, parentId, items)}
                aria-label={`下移 ${node.name}`}
              >
                ↓
              </Button>
            </div>
          </div>
          {node.description ? (
            <p
              className="text-caption text-muted-foreground"
              style={{ paddingLeft: depth * 16 + 36 }}
            >
              {node.description}
            </p>
          ) : null}
          {!isCollapsed && node.children.length > 0
            ? renderItems(node.children, node.id, depth + 1)
            : null}
        </div>
      )
    })
  }

  return (
    <div className="space-y-0.5">
      {nodes.length === 0 ? (
        <p className="text-body-sm text-muted-foreground">
          目录为空，点击「添加根节点」开始组织知识。
        </p>
      ) : (
        renderItems(nodes, null, 0)
      )}
    </div>
  )
}
