import { useEffect, useMemo, useRef, useState } from 'react'
import { Lock, Pencil, RotateCw, Trash2, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  applyDirectoryDraft,
  createDirectoryDraft,
  discardDirectoryDraft,
  expandDirectoryDraft,
  fetchDirectoryDraft,
  submitDirectoryDraftMessage,
  submitDirectoryDraftClarify,
  updateDirectoryDraftNodes,
  type DirectoryDraftPayload,
  type DraftDiffNodePayload,
  type DraftMessagePayload,
  type DraftNodePayload,
} from '@/lib/api'

interface EditableNode {
  uid: string
  id: number | null
  name: string
  description: string | null
  selected: boolean
  children: EditableNode[]
}

function flattenToNested(nodes: DraftNodePayload[]): EditableNode[] {
  const byParent = new Map<number | null, DraftNodePayload[]>()
  for (const node of nodes) {
    const list = byParent.get(node.parent_id) ?? []
    list.push(node)
    byParent.set(node.parent_id, list)
  }
  let uid = 0
  const build = (parent: number | null): EditableNode[] =>
    (byParent.get(parent) ?? [])
      .sort((left, right) => left.position - right.position)
      .map((node) => ({
        uid: `draft-${uid++}`,
        id: node.id,
        name: node.name,
        description: node.description,
        selected: node.selected ?? true,
        children: build(node.id),
      }))
  return build(null)
}

function countNodes(nodes: readonly EditableNode[]): number {
  return nodes.reduce(
    (total, node) => total + 1 + countNodes(node.children),
    0,
  )
}

function countSelected(nodes: readonly EditableNode[]): number {
  return nodes.reduce(
    (total, node) =>
      total +
      (node.selected ? 1 : 0) +
      countSelected(node.children),
    0,
  )
}

function mapNodes(
  nodes: readonly EditableNode[],
  uid: string,
  updater: (node: EditableNode) => EditableNode,
): EditableNode[] {
  return nodes.map((node) => {
    if (node.uid === uid) return updater(node)
    return { ...node, children: mapNodes(node.children, uid, updater) }
  })
}

function removeNode(nodes: readonly EditableNode[], uid: string): EditableNode[] {
  return nodes
    .filter((node) => node.uid !== uid)
    .map((node) => ({ ...node, children: removeNode(node.children, uid) }))
}

function mapById(
  nodes: readonly EditableNode[],
  id: number,
  updater: (node: EditableNode) => EditableNode,
): EditableNode[] {
  return nodes.map((node) => {
    if (node.id === id) return updater(node)
    return { ...node, children: mapById(node.children, id, updater) }
  })
}

function sourceBadge(draft: DirectoryDraftPayload) {
  if (draft.provider === 'llm' && !draft.is_fallback) {
    return <Badge className="bg-confirmed-soft text-confirmed">真实模型</Badge>
  }
  if (draft.is_fallback || draft.provider === 'offline' || draft.provider === 'demo') {
    return <Badge className="bg-error-soft text-destructive">离线生成</Badge>
  }
  return <Badge className="bg-muted text-muted-foreground">来源未标注</Badge>
}

function TreeNodeEditor({
  node,
  depth,
  onChange,
  onRemove,
}: {
  node: EditableNode
  depth: number
  onChange: (node: EditableNode) => void
  onRemove: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(node.name)
  const [editDesc, setEditDesc] = useState(node.description ?? '')

  function save() {
    onChange({
      ...node,
      name: editName.trim() || node.name,
      description: editDesc.trim() || null,
    })
    setEditing(false)
  }

  return (
    <div className="space-y-2 border-l-2 border-muted pl-3" style={{ marginLeft: depth * 12 }}>
      <div className="group flex items-center gap-2">
        <input
          type="checkbox"
          aria-label={`采用 ${node.name}`}
          checked={node.selected}
          onChange={() => onChange({ ...node, selected: !node.selected })}
        />
        {editing ? (
          <>
            <Input
              className="h-8 w-40"
              value={editName}
              aria-label="节点名称"
              autoFocus
              onChange={(event) => setEditName(event.target.value)}
            />
            <Button size="sm" onClick={save}>
              保存
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              取消
            </Button>
          </>
        ) : (
          <>
            <span className="shrink-0 truncate text-body-sm font-medium">{node.name}</span>
            {node.description ? (
              <span className="min-w-0 flex-1 truncate text-caption text-muted-foreground">
                {node.description}
              </span>
            ) : null}
            <span className="flex items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`编辑 ${node.name}`}
                onClick={() => {
                  setEditName(node.name)
                  setEditDesc(node.description ?? '')
                  setEditing(true)
                }}
              >
                <Pencil />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`删除 ${node.name}`}
                onClick={onRemove}
              >
                <Trash2 />
              </Button>
            </span>
          </>
        )}
      </div>
      {editing ? (
        <Textarea
          rows={2}
          value={editDesc}
          aria-label="节点说明"
          placeholder="节点说明（可选）"
          onChange={(event) => setEditDesc(event.target.value)}
        />
      ) : null}
      {node.children.map((child) => (
        <TreeNodeEditor
          key={child.uid}
          node={child}
          depth={depth + 1}
          onChange={(updated) =>
            onChange({ ...node, children: mapNodes(node.children, updated.uid, () => updated) })
          }
          onRemove={() => onChange({ ...node, children: removeNode(node.children, child.uid) })}
        />
      ))}
    </div>
  )
}

function DiffTree({
  diff,
  depth,
  selectedByDraftId,
  removedIds,
  onToggleAdded,
  onToggleRemoved,
}: {
  diff: readonly DraftDiffNodePayload[]
  depth: number
  selectedByDraftId: ReadonlyMap<number, boolean>
  removedIds: ReadonlySet<number>
  onToggleAdded: (nodeId: number, selected: boolean) => void
  onToggleRemoved: (realNodeId: number, checked: boolean) => void
}) {
  return (
    <div className="space-y-2 border-l-2 border-muted pl-3" style={{ marginLeft: depth * 12 }}>
      {diff.map((entry) => {
        const key =
          entry.kind === 'removed'
            ? `removed-${entry.real_node_id}`
            : `draft-${entry.node_id}`
        return (
          <div key={key}>
            <div className="flex min-h-8 items-center gap-2">
              {entry.kind === 'added' ? (
                <input
                  type="checkbox"
                  aria-label={`采用新增节点 ${entry.name}`}
                  checked={selectedByDraftId.get(entry.node_id ?? -1) ?? true}
                  onChange={(event) => {
                    if (entry.node_id != null) {
                      onToggleAdded(entry.node_id, event.target.checked)
                    }
                  }}
                />
              ) : entry.kind === 'removed' ? (
                entry.blocked ? (
                  <Lock className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                ) : (
                  <input
                    type="checkbox"
                    aria-label={`移除节点 ${entry.name}`}
                    checked={removedIds.has(entry.real_node_id ?? -1)}
                    onChange={(event) => {
                      if (entry.real_node_id != null) {
                        onToggleRemoved(entry.real_node_id, event.target.checked)
                      }
                    }}
                  />
                )
              ) : (
                <span className="w-4 shrink-0" aria-hidden />
              )}
              <span
                className={`shrink-0 rounded px-1.5 text-[11px] leading-5 ${
                  entry.kind === 'added'
                    ? 'bg-brand-soft text-brand'
                    : entry.kind === 'removed'
                      ? 'bg-error-soft text-destructive'
                      : 'bg-muted text-muted-foreground'
                }`}
              >
                {entry.kind === 'added' ? '新增' : entry.kind === 'kept' ? '保留' : '建议移除'}
              </span>
              <span className="truncate text-body-sm font-medium">{entry.name}</span>
              {entry.description ? (
                <span className="min-w-0 flex-1 truncate text-caption text-muted-foreground">
                  {entry.description}
                </span>
              ) : null}
              {entry.blocked ? (
                <span className="shrink-0 text-caption text-destructive">
                  含 {entry.blocker_count} 条正式知识，不可移除
                </span>
              ) : null}
            </div>
            {entry.children.length > 0 ? (
              <DiffTree
                diff={entry.children}
                depth={depth + 1}
                selectedByDraftId={selectedByDraftId}
                removedIds={removedIds}
                onToggleAdded={onToggleAdded}
                onToggleRemoved={onToggleRemoved}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export function DirectoryDraftDialog({
  projectId,
  mode = 'draft',
  targetNode,
  open,
  onOpenChange,
  onApplied,
}: {
  projectId: number
  mode?: 'draft' | 'expand'
  targetNode?: { id: number; name: string } | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onApplied?: () => void
}) {
  const [draft, setDraft] = useState<DirectoryDraftPayload | null>(null)
  const [tree, setTree] = useState<EditableNode[]>([])
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [otherText, setOtherText] = useState<Record<string, string>>({})
  const [messages, setMessages] = useState<DraftMessagePayload[]>([])
  const [messageInput, setMessageInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [error, setError] = useState('')
  const [waitSeconds, setWaitSeconds] = useState(0)
  const [removedIds, setRemovedIds] = useState<ReadonlySet<number>>(new Set())
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastDiffRef = useRef('')

  function applyDraftData(data: DirectoryDraftPayload) {
    setDraft(data)
    setMessages(data.messages ?? [])
    if (data.status === 'pending_confirm') setTree(flattenToNested(data.nodes))
    if (data.kind === 'expand') {
      const key = JSON.stringify(data.diff ?? [])
      if (key !== lastDiffRef.current) {
        lastDiffRef.current = key
        const next = new Set<number>()
        const collect = (entries: readonly DraftDiffNodePayload[]) => {
          for (const entry of entries) {
            if (
              entry.kind === 'removed' &&
              entry.real_node_id != null &&
              !entry.blocked
            ) {
              next.add(entry.real_node_id)
            }
            collect(entry.children)
          }
        }
        collect(data.diff ?? [])
        setRemovedIds(next)
      }
    }
  }

  function updateTree(
    updater: (current: EditableNode[]) => EditableNode[],
  ) {
    setTree((current) => updater(current))
    setDirty(true)
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => {
    if (!open) {
      stopPolling()
      return
    }
    setError('')
    setLoading(true)
    let cancelled = false
    async function openDraft() {
      let existing: DirectoryDraftPayload | null = null
      try {
        existing = await fetchDirectoryDraft(projectId)
      } catch {
        // 无活跃草稿时视为首次发起
      }
      const matches =
        existing != null &&
        (mode === 'expand'
          ? existing.kind === 'expand' &&
            targetNode != null &&
            existing.target_node_id === targetNode.id
          : existing.kind === 'draft')
      try {
        const data = matches
          ? existing
          : mode === 'expand' && targetNode
            ? await expandDirectoryDraft(projectId, targetNode.id)
            : await createDirectoryDraft(projectId)
        if (data && !cancelled) applyDraftData(data)
      } catch (reason: unknown) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '创建草稿失败')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void openDraft()
    return () => {
      cancelled = true
      stopPolling()
    }
  }, [open, projectId, mode, targetNode])

  useEffect(() => {
    if (!draft || draft.status !== 'drafting') {
      stopPolling()
      return
    }
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const data = await fetchDirectoryDraft(projectId)
        applyDraftData(data)
        if (data.status !== 'drafting') stopPolling()
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '获取草稿失败')
        stopPolling()
      }
    }, 1000)
    return stopPolling
  }, [draft?.status, projectId])

  const nodeCount = useMemo(() => countNodes(tree), [tree])
  const selectedCount = useMemo(() => countSelected(tree), [tree])
  const selectedByDraftId = useMemo(() => {
    const map = new Map<number, boolean>()
    if (!draft) return map
    for (const node of draft.nodes) map.set(node.id, node.selected)
    return map
  }, [draft])
  const diffStats = useMemo(() => {
    const stats = { added: 0, removed: 0, blocked: 0 }
    const collect = (entries: readonly DraftDiffNodePayload[]) => {
      for (const entry of entries) {
        if (entry.kind === 'added') stats.added += 1
        if (entry.kind === 'removed') {
          stats.removed += 1
          if (entry.blocked) stats.blocked += 1
        }
        collect(entry.children)
      }
    }
    collect(draft?.diff ?? [])
    return stats
  }, [draft])

  async function persistTree(force = false) {
    if (!force && !dirty) return
    try {
      const data = await updateDirectoryDraftNodes(projectId, tree)
      setDraft(data)
      setDirty(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存草稿失败')
    }
  }

  useEffect(() => {
    if (!dirty || !draft || draft.status !== 'pending_confirm') return
    const timer = setTimeout(() => {
      void persistTree()
    }, 600)
    return () => clearTimeout(timer)
  }, [dirty, tree, draft?.status])

  function toggleAddedNode(nodeId: number, selected: boolean) {
    updateTree((current) => mapById(current, nodeId, (node) => ({ ...node, selected })))
  }

  function toggleRemovedNode(realNodeId: number, checked: boolean) {
    setRemovedIds((current) => {
      const next = new Set(current)
      if (checked) next.add(realNodeId)
      else next.delete(realNodeId)
      return next
    })
  }

  function toggleOption(questionId: string, option: string, multiple: boolean) {
    setAnswers((current) => {
      if (!multiple) return { ...current, [questionId]: option }
      const existing = Array.isArray(current[questionId]) ? current[questionId] : []
      const next = existing.includes(option)
        ? existing.filter((item) => item !== option)
        : [...existing, option]
      return { ...current, [questionId]: next }
    })
  }

  async function submitAnswers() {
    if (!draft) return
    setBusy(true)
    setError('')
    try {
      const merged = { ...answers }
      for (const [questionId, text] of Object.entries(otherText)) {
        const current = merged[questionId]
        if (Array.isArray(current)) {
          merged[questionId] = current
            .filter((item) => item !== '其他')
            .concat(text ? [text] : [])
        } else if (current === '其他') {
          merged[questionId] = text || '其他'
        }
      }
      const data = await submitDirectoryDraftClarify(projectId, merged)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '提交澄清失败')
    } finally {
      setBusy(false)
    }
  }

  async function applyDraft() {
    setBusy(true)
    setError('')
    try {
      await persistTree(true)
      const data =
        draft?.kind === 'expand'
          ? await applyDirectoryDraft(projectId, [...removedIds])
          : await applyDirectoryDraft(projectId)
      setDraft(data)
      onApplied?.()
      onOpenChange(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '应用目录失败')
    } finally {
      setBusy(false)
    }
  }

  async function discard() {
    setBusy(true)
    setError('')
    try {
      await discardDirectoryDraft(projectId)
      onOpenChange(false)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '丢弃草稿失败')
    } finally {
      setBusy(false)
    }
  }

  async function sendMessage() {
    const content = messageInput.trim()
    if (!content || !draft) return
    setBusy(true)
    setThinking(true)
    setError('')
    setMessageInput('')
    setMessages((current) => [
      ...current,
      { id: -Date.now(), role: 'user', content, created_at: new Date().toISOString() },
    ])
    try {
      await persistTree(true)
      const data = await submitDirectoryDraftMessage(projectId, content)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发送消息失败')
    } finally {
      setBusy(false)
      setThinking(false)
    }
  }

  async function retryDraft() {
    setBusy(true)
    setError('')
    try {
      const data =
        mode === 'expand' && targetNode
          ? await expandDirectoryDraft(projectId, targetNode.id)
          : await createDirectoryDraft(projectId)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重新发起失败')
    } finally {
      setBusy(false)
    }
  }

  const generating =
    loading || draft?.status === 'drafting'

  useEffect(() => {
    if (!generating) {
      setWaitSeconds(0)
      return
    }
    setWaitSeconds(0)
    const timer = setInterval(() => setWaitSeconds((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [generating])

  return open ? (
    <div className="fixed inset-0 z-50 bg-black/40" onClick={() => onOpenChange(false)}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={mode === 'expand' ? 'AI 拓展节点' : '与 AI 共创目录'}
        className="absolute right-0 top-0 flex h-full w-[min(960px,100vw)] flex-col bg-card shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-3 border-b px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-[18px] font-[650] leading-6">
              {mode === 'expand'
                ? `AI 拓展节点「${targetNode?.name ?? ''}」`
                : '与 AI 共创目录'}
            </h2>
            <p className="text-caption text-muted-foreground">
              AI 只生成候选草稿，确认后才会创建正式节点。
            </p>
            {draft ? (
              <div className="mt-2">{sourceBadge(draft)}</div>
            ) : null}
          </div>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="关闭"
            onClick={() => onOpenChange(false)}
          >
            <X />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error ? (
            <div className="mb-3 rounded-md border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive">
              {error}
            </div>
          ) : null}

          {generating ? (
            <div className="flex items-center gap-2 py-10 text-body-sm text-muted-foreground">
              <RotateCw className="size-4 animate-spin" />
              <span>
                {draft?.next_action === 'clarify'
                  ? `AI 正在生成澄清问题…（已等待 ${waitSeconds} 秒）`
                  : mode === 'expand'
                    ? `AI 正在生成拓展结构…（已等待 ${waitSeconds} 秒）`
                    : `AI 正在生成候选树…（已等待 ${waitSeconds} 秒）`}
                {waitSeconds >= 20 ? (
                  <span className="mt-1 block text-amber-600">
                    生成较慢，可稍候或关闭后重新发起。
                  </span>
                ) : null}
              </span>
            </div>
          ) : draft?.status === 'awaiting_input' ? (
            <div className="space-y-4">
              {draft.clarify.map((question) => {
                const value = answers[question.id]
                const selected = Array.isArray(value) ? value : value ? [value] : []
                const otherSelected = selected.includes('其他')
                return (
                  <div key={question.id} className="space-y-2 rounded-md border p-3">
                    <p className="text-body font-[650]">{question.text}</p>
                    <div className="space-y-1.5">
                      {question.options.map((option) => {
                        const active = selected.includes(option)
                        return (
                          <label
                            key={option}
                            className="flex cursor-pointer items-center gap-2 text-body-sm"
                          >
                            <input
                              type={question.multiple ? 'checkbox' : 'radio'}
                              name={question.id}
                              checked={active}
                              onChange={() => toggleOption(question.id, option, question.multiple)}
                            />
                            {option}
                          </label>
                        )
                      })}
                      <label className="flex cursor-pointer items-center gap-2 text-body-sm">
                        <input
                          type={question.multiple ? 'checkbox' : 'radio'}
                          name={question.id}
                          checked={otherSelected}
                          onChange={() => toggleOption(question.id, '其他', question.multiple)}
                        />
                        其他
                      </label>
                    </div>
                    {otherSelected ? (
                      <Input
                        value={otherText[question.id] ?? ''}
                        placeholder="请输入自定义答案"
                        onChange={(event) =>
                          setOtherText((current) => ({
                            ...current,
                            [question.id]: event.target.value,
                          }))
                        }
                      />
                    ) : null}
                  </div>
                )
              })}
            </div>
          ) : draft?.status === 'pending_confirm' ? (
            <div className="grid h-full grid-cols-2 gap-4">
              <div className="min-h-0 space-y-2 overflow-y-auto pr-2">
                {draft?.kind === 'expand' ? (
                  <>
                    <p className="text-caption text-muted-foreground">
                      新增 {diffStats.added} · 建议移除 {diffStats.removed}
                      {diffStats.blocked > 0 ? `（其中 ${diffStats.blocked} 个受保护不可移除）` : ''}
                    </p>
                    {diffStats.blocked > 0 ? (
                      <p className="rounded-md border-l-2 border-destructive bg-error-soft px-3 py-2 text-caption text-destructive">
                        含正式知识的节点无法由 AI 移除，如需改名/移动/改说明请使用手动编辑。
                      </p>
                    ) : null}
                    <DiffTree
                      diff={draft?.diff ?? []}
                      depth={0}
                      selectedByDraftId={selectedByDraftId}
                      removedIds={removedIds}
                      onToggleAdded={toggleAddedNode}
                      onToggleRemoved={toggleRemovedNode}
                    />
                  </>
                ) : (
                  <>
                    <p className="text-caption text-muted-foreground">
                      已选 {selectedCount} / {nodeCount} 个节点 · 受影响 Entry 0 条
                    </p>
                    {tree.map((node) => (
                      <TreeNodeEditor
                        key={node.uid}
                        node={node}
                        depth={0}
                        onChange={(updated) =>
                          updateTree((current) => mapNodes(current, updated.uid, () => updated))
                        }
                        onRemove={() => updateTree((current) => removeNode(current, node.uid))}
                      />
                    ))}
                  </>
                )}
              </div>
              <div className="flex min-h-0 flex-col">
                <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-md border p-3">
                  {messages.length === 0 ? (
                    <p className="text-caption text-muted-foreground">
                      可以直接告诉 AI 怎么调整目录。
                    </p>
                  ) : (
                    <>
                      {messages.map((message) => (
                        <div
                          key={message.id}
                          className={`max-w-[85%] rounded-md px-3 py-2 text-body-sm ${
                            message.role === 'user'
                              ? 'ml-auto bg-brand-soft text-brand'
                              : message.role === 'system'
                                ? 'bg-muted text-muted-foreground'
                                : 'bg-muted/60'
                          }`}
                        >
                          {message.content}
                        </div>
                      ))}
                      {thinking ? (
                        <div className="max-w-[85%] rounded-md bg-muted/60 px-3 py-2 text-body-sm text-muted-foreground">
                          AI 思考中…
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
                <div className="mt-2 flex items-end gap-2">
                  <Textarea
                    className="flex-1"
                    rows={3}
                    value={messageInput}
                    placeholder="告诉 AI 怎么调整目录…"
                    onChange={(event) => setMessageInput(event.target.value)}
                  />
                  <Button disabled={busy || !messageInput.trim()} onClick={sendMessage}>
                    {busy ? <RotateCw className="animate-spin" /> : null}
                    发送
                  </Button>
                </div>
              </div>
            </div>
          ) : draft?.status === 'failed' ? (
            <div className="space-y-3 py-8 text-center">
              <p className="text-body-sm text-destructive">
                草稿生成失败：{draft.last_error ?? '未知错误'}
              </p>
              <Button variant="outline" disabled={busy} onClick={retryDraft}>
                <RotateCw className={busy ? 'animate-spin' : ''} />
                重新发起
              </Button>
            </div>
          ) : (
            <p className="py-8 text-center text-body-sm text-muted-foreground">
              草稿已处理或正在处理，请稍候。
            </p>
          )}
        </div>

        <footer className="flex justify-end gap-2 border-t px-6 py-4">
          <Button variant="ghost" disabled={busy || !draft} onClick={discard}>
            <X />
            丢弃
          </Button>
          {draft?.status === 'awaiting_input' ? (
            <Button disabled={busy} onClick={submitAnswers}>
              {busy ? <RotateCw className="animate-spin" /> : null}
              提交并生成
            </Button>
          ) : null}
          {draft?.status === 'pending_confirm' ? (
            <>
              <Button
                disabled={
                  busy ||
                  (draft?.kind === 'expand'
                    ? diffStats.added === 0 && removedIds.size === 0
                    : selectedCount === 0)
                }
                onClick={applyDraft}
              >
                {draft?.kind === 'expand' ? '应用拓展' : '应用目录'}
              </Button>
            </>
          ) : null}
        </footer>
      </aside>
    </div>
  ) : null
}
