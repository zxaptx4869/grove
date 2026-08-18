import { useEffect, useMemo, useState } from 'react'
import { Check, FolderPlus, Plus, RotateCw, Trash2, X } from 'lucide-react'

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
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  applyDirectoryDraft,
  createDirectoryDraft,
  discardDirectoryDraft,
  submitDirectoryDraftMessage,
  submitDirectoryDraftClarify,
  updateDirectoryDraftNodes,
  type DirectoryDraftPayload,
  type DraftMessagePayload,
  type DraftNodePayload,
} from '@/lib/api'

interface EditableNode {
  uid: string
  name: string
  description: string | null
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
        name: node.name,
        description: node.description,
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

function sourceBadge(draft: DirectoryDraftPayload) {
  if (draft.provider === 'llm' && !draft.is_fallback) {
    return (
      <Badge className="bg-confirmed-soft text-confirmed">真实模型</Badge>
    )
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
  return (
    <div className="space-y-2 border-l-2 border-muted pl-3" style={{ marginLeft: depth * 12 }}>
      <div className="flex items-center gap-2">
        <Input
          className="h-8 flex-1"
          value={node.name}
          aria-label="节点名称"
          onChange={(event) => onChange({ ...node, name: event.target.value })}
        />
        <Button
          size="icon-sm"
          variant="ghost"
          aria-label="新增子节点"
          onClick={() =>
            onChange({
              ...node,
              children: [
                ...node.children,
                { uid: `draft-${Math.random().toString(36).slice(2)}`, name: '新节点', description: null, children: [] },
              ],
            })
          }
        >
          <Plus />
        </Button>
        <Button size="icon-sm" variant="ghost" aria-label="删除节点" onClick={onRemove}>
          <Trash2 />
        </Button>
      </div>
      <Textarea
        rows={2}
        value={node.description ?? ''}
        aria-label="节点说明"
        placeholder="节点说明（可选）"
        onChange={(event) => onChange({ ...node, description: event.target.value || null })}
      />
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

export function DirectoryDraftDialog({
  projectId,
  open,
  onOpenChange,
  onApplied,
}: {
  projectId: number
  open: boolean
  onOpenChange: (open: boolean) => void
  onApplied?: () => void
}) {
  const [draft, setDraft] = useState<DirectoryDraftPayload | null>(null)
  const [tree, setTree] = useState<EditableNode[]>([])
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [messages, setMessages] = useState<DraftMessagePayload[]>([])
  const [messageInput, setMessageInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    setLoading(true)
    createDirectoryDraft(projectId)
      .then((data) => {
        setDraft(data)
        setMessages(data.messages ?? [])
        if (data.status === 'pending_confirm') setTree(flattenToNested(data.nodes))
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : '创建草稿失败'),
      )
      .finally(() => setLoading(false))
  }, [open, projectId])

  const nodeCount = useMemo(() => countNodes(tree), [tree])

  function applyDraftData(data: DirectoryDraftPayload) {
    setDraft(data)
    setMessages(data.messages ?? [])
    if (data.status === 'pending_confirm') setTree(flattenToNested(data.nodes))
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
      const data = await submitDirectoryDraftClarify(projectId, answers)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '提交澄清失败')
    } finally {
      setBusy(false)
    }
  }

  async function saveTree() {
    setBusy(true)
    setError('')
    try {
      const data = await updateDirectoryDraftNodes(projectId, tree)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存草稿失败')
    } finally {
      setBusy(false)
    }
  }

  async function applyDraft() {
    setBusy(true)
    setError('')
    try {
      const data = await applyDirectoryDraft(projectId)
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
    setError('')
    setMessageInput('')
    setMessages((current) => [
      ...current,
      { id: -Date.now(), role: 'user', content, created_at: new Date().toISOString() },
    ])
    try {
      const data = await submitDirectoryDraftMessage(projectId, content)
      applyDraftData(data)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '发送消息失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>与 AI 共创目录</DialogTitle>
          <DialogDescription>
            AI 只生成候选目录草稿，确认后才会创建正式节点。
            {draft ? sourceBadge(draft) : null}
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <div className="rounded-md border-l-2 border-destructive bg-error-soft px-3 py-2 text-body-sm text-destructive">
            {error}
          </div>
        ) : null}

        {loading ? (
          <div className="space-y-2 py-8">
            <div className="h-5 w-40 animate-pulse rounded bg-muted/50" />
            <div className="h-32 animate-pulse rounded bg-muted/40" />
          </div>
        ) : draft?.status === 'awaiting_input' ? (
          <div className="max-h-[50vh] space-y-4 overflow-y-auto">
            {draft.clarify.map((question) => {
              const value = answers[question.id]
              const selected = Array.isArray(value) ? value : value ? [value] : []
              return (
                <div key={question.id} className="space-y-2 rounded-md border p-3">
                  <p className="text-body font-[650]">{question.text}</p>
                  <div className="flex flex-wrap gap-2">
                    {question.options.map((option) => {
                      const active = selected.includes(option)
                      return (
                        <Button
                          key={option}
                          size="sm"
                          variant={active ? 'default' : 'outline'}
                          onClick={() => toggleOption(question.id, option, question.multiple)}
                        >
                          {active ? <Check /> : null}
                          {option}
                        </Button>
                      )
                    })}
                  </div>
                  <Input
                    value={Array.isArray(value) ? '' : (value ?? '')}
                    placeholder="或自由输入答案"
                    onChange={(event) =>
                      setAnswers((current) => ({
                        ...current,
                        [question.id]: event.target.value,
                      }))
                    }
                  />
                </div>
              )
            })}
          </div>
        ) : draft?.status === 'pending_confirm' ? (
          <div className="grid max-h-[55vh] grid-cols-2 gap-4 overflow-hidden">
            <div className="min-h-0 space-y-2 overflow-y-auto pr-2">
              <p className="text-caption text-muted-foreground">
                将创建 {nodeCount} 个节点 · 受影响 Entry 0 条
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  setTree((current) => [
                    ...current,
                    { uid: `draft-${Math.random().toString(36).slice(2)}`, name: '新节点', description: null, children: [] },
                  ])
                }
              >
                <FolderPlus />
                添加根节点
              </Button>
              {tree.map((node) => (
                <TreeNodeEditor
                  key={node.uid}
                  node={node}
                  depth={0}
                  onChange={(updated) => setTree(mapNodes(tree, updated.uid, () => updated))}
                  onRemove={() => setTree(removeNode(tree, node.uid))}
                />
              ))}
            </div>
            <div className="flex min-h-0 flex-col">
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-md border p-3">
                {messages.length === 0 ? (
                  <p className="text-caption text-muted-foreground">
                    可以直接告诉 AI 怎么调整目录。
                  </p>
                ) : (
                  messages.map((message) => (
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
                  ))
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
                  发送
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <p className="py-8 text-center text-body-sm text-muted-foreground">
            草稿正在生成或已处理，请稍后重试。
          </p>
        )}

        <DialogFooter>
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
              <Button variant="outline" disabled={busy} onClick={saveTree}>
                保存编辑
              </Button>
              <Button disabled={busy || nodeCount === 0} onClick={applyDraft}>
                应用目录
              </Button>
            </>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
