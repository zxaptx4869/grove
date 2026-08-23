import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Send, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

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
  applyRevisionSuggestion,
  refineRevisionSuggestion,
  requestRevisionSuggestion,
  type EntryPayload,
  type RevisionChatMessagePayload,
  type RevisionDraftPayload,
} from '@/lib/api'

const MAIN_TYPE_LABELS = [
  { value: 'knowledge', label: '知识' },
  { value: 'method', label: '方法' },
  { value: 'parameter', label: '参数' },
  { value: 'reminder', label: '提醒' },
] as const

interface DraftFormState {
  title: string
  content: string
  main_type: EntryPayload['main_type']
  info_nature: string
  applicable_condition: string
  note: string
  change_summary: string
}

function formFromDraft(
  draft: RevisionDraftPayload,
  entry: EntryPayload,
): DraftFormState {
  return {
    title: draft.title ?? entry.title,
    content: draft.content ?? entry.content,
    main_type: draft.main_type ?? entry.main_type,
    info_nature: draft.info_nature ?? entry.info_nature ?? '',
    applicable_condition: draft.applicable_condition ?? entry.applicable_condition ?? '',
    note: draft.note ?? entry.note ?? '',
    change_summary: draft.change_summary,
  }
}

/** AI 修订建议面板：一次性对话调整草稿，应用后结论沉淀为 Entry 版本。 */
export function RevisionSuggestionDialog({
  open,
  entry,
  onOpenChange,
  onApplied,
}: {
  open: boolean
  entry: EntryPayload | null
  onOpenChange: (open: boolean) => void
  onApplied: (entry: EntryPayload) => void
}) {
  const [messages, setMessages] = useState<RevisionChatMessagePayload[]>([])
  const [draft, setDraft] = useState<RevisionDraftPayload | null>(null)
  const [form, setForm] = useState<DraftFormState | null>(null)
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // 打开面板或切换 Entry 时重置一次性对话（React 渲染期派生状态模式）
  const [previous, setPrevious] = useState<{
    open: boolean
    entryId: number | null
  }>({ open: false, entryId: null })
  const current = { open, entryId: entry?.id ?? null }
  if (current.open !== previous.open || current.entryId !== previous.entryId) {
    setPrevious(current)
    if (open && entry) {
      setMessages([])
      setDraft(null)
      setForm(null)
      setInstruction('')
      setBusy(false)
      setError('')
    }
  }

  const apply = useMutation({
    mutationFn: () => {
      const current = form!
      return applyRevisionSuggestion(entry!.id, {
        title: current.title.trim(),
        content: current.content.trim(),
        main_type: current.main_type,
        info_nature: current.info_nature.trim() || null,
        applicable_condition: current.applicable_condition.trim() || null,
        note: current.note.trim() || null,
        change_summary: current.change_summary.trim() || null,
      })
    },
    onSuccess: (updated) => {
      toast.success('修订已应用')
      onApplied(updated)
    },
    onError: (reason: Error) => {
      toast.error(`应用失败：${reason.message}`)
    },
  })

  async function generate() {
    if (!entry || busy) return
    const text = instruction.trim()
    setBusy(true)
    setError('')
    setInstruction('')
    try {
      const result = await requestRevisionSuggestion(entry.id, text || null)
      const nextMessages = [
        ...(text ? [{ role: 'user' as const, content: text }] : []),
        { role: 'assistant' as const, content: result.reply_text },
      ]
      setMessages(nextMessages)
      if (result.draft) {
        setDraft(result.draft)
        setForm(formFromDraft(result.draft, entry))
      }
      if (result.is_fallback) {
        setError(result.error ?? '文本模型不可用')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生成修订建议失败')
    } finally {
      setBusy(false)
    }
  }

  async function refine() {
    if (!entry || busy) return
    const text = instruction.trim()
    if (!text) return
    const history = messages
    setBusy(true)
    setError('')
    setInstruction('')
    try {
      const result = await refineRevisionSuggestion(entry.id, {
        instruction: text,
        messages: history,
        draft,
      })
      setMessages([
        ...history,
        { role: 'user', content: text },
        { role: 'assistant', content: result.reply_text },
      ])
      if (result.draft) {
        setDraft(result.draft)
        setForm(formFromDraft(result.draft, entry))
      }
      if (result.is_fallback) {
        setError(result.error ?? '文本模型不可用')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '继续调整失败')
    } finally {
      setBusy(false)
    }
  }

  function sendMessage() {
    if (messages.length === 0) {
      void generate()
    } else {
      void refine()
    }
  }

  const canApply = Boolean(
    form && form.title.trim() && form.content.trim() && !apply.isPending,
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>AI 修订建议</DialogTitle>
          <DialogDescription>
            {entry ? `针对「${entry.title}」· 对话关闭后不保存` : ''}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-[260px] space-y-3 overflow-y-auto rounded-md border p-3">
          {messages.length === 0 ? (
            <p className="text-body-sm text-muted-foreground">
              告诉 AI 想怎么调整，或直接生成草稿；之后可以继续对话打磨。
            </p>
          ) : (
            messages.map((message, index) => (
              <div
                key={index}
                className={`max-w-[85%] rounded-md px-3 py-2 text-body-sm ${
                  message.role === 'user'
                    ? 'ml-auto bg-brand-soft text-brand'
                    : 'bg-muted/60 text-foreground'
                }`}
              >
                {message.content}
              </div>
            ))
          )}
          {busy ? (
            <div className="max-w-[85%] rounded-md bg-muted/60 px-3 py-2 text-body-sm text-muted-foreground">
              AI 思考中…
            </div>
          ) : null}
        </div>
        {error ? (
          <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-body-sm text-amber-700">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}
        <div className="flex gap-2">
          <Input
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && instruction.trim() && !busy) sendMessage()
            }}
            placeholder={
              messages.length === 0 ? '想怎么修订这条知识？（可留空直接生成）' : '继续告诉 AI 怎么调整…'
            }
            disabled={busy}
            aria-label="修订指令"
          />
          <Button onClick={sendMessage} disabled={busy || (messages.length > 0 && !instruction.trim())}>
            <Send />
            {messages.length === 0 ? '生成' : '继续调整'}
          </Button>
        </div>
        {form ? (
          <div className="space-y-3 rounded-md border border-brand/30 p-3">
            <div className="flex items-center gap-2">
              <Badge className="bg-ai-candidate-soft text-ai-candidate">
                <Sparkles className="mr-1 size-3.5" />
                AI 候选草稿
              </Badge>
              {draft?.reason ? (
                <span className="text-caption text-muted-foreground">修订原因：{draft.reason}</span>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="revision-title" className="text-body-sm font-medium">
                标题
              </label>
              <Input
                id="revision-title"
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="revision-content" className="text-body-sm font-medium">
                核心内容
              </label>
              <Textarea
                id="revision-content"
                value={form.content}
                onChange={(event) => setForm({ ...form, content: event.target.value })}
                rows={5}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="revision-type" className="text-body-sm font-medium">
                  主类型
                </label>
                <select
                  id="revision-type"
                  className="h-9 w-full rounded-md border px-2 text-body-sm"
                  value={form.main_type}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      main_type: event.target.value as EntryPayload['main_type'],
                    })
                  }
                >
                  {MAIN_TYPE_LABELS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="revision-nature" className="text-body-sm font-medium">
                  信息性质
                </label>
                <Input
                  id="revision-nature"
                  value={form.info_nature}
                  onChange={(event) => setForm({ ...form, info_nature: event.target.value })}
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="revision-condition" className="text-body-sm font-medium">
                适用条件
              </label>
              <Textarea
                id="revision-condition"
                value={form.applicable_condition}
                onChange={(event) =>
                  setForm({ ...form, applicable_condition: event.target.value })
                }
                rows={2}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="revision-note" className="text-body-sm font-medium">
                补充说明
              </label>
              <Textarea
                id="revision-note"
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
                rows={2}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="revision-summary" className="text-body-sm font-medium">
                变更说明
              </label>
              <Input
                id="revision-summary"
                value={form.change_summary}
                onChange={(event) => setForm({ ...form, change_summary: event.target.value })}
              />
            </div>
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy || apply.isPending}>
            放弃
          </Button>
          <Button onClick={() => apply.mutate()} disabled={!canApply}>
            应用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
