import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Send, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
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

/** AI 修订建议右抽屉：左侧候选草稿、右侧一次性对话，应用后结论沉淀为 Entry 版本。 */
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
  const [aiMeta, setAiMeta] = useState<{
    instruction: string
    ai_reply: string
    reason: string
    provider: string | null
    model: string | null
  }>({ instruction: '', ai_reply: '', reason: '', provider: null, model: null })

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
      setAiMeta({ instruction: '', ai_reply: '', reason: '', provider: null, model: null })
    }
  }

  const apply = useMutation({
    mutationFn: () => {
      const currentForm = form!
      return applyRevisionSuggestion(entry!.id, {
        title: currentForm.title.trim(),
        content: currentForm.content.trim(),
        main_type: currentForm.main_type,
        info_nature: currentForm.info_nature.trim() || null,
        applicable_condition: currentForm.applicable_condition.trim() || null,
        note: currentForm.note.trim() || null,
        change_summary: currentForm.change_summary.trim() || null,
        instruction: aiMeta.instruction || null,
        ai_reply: aiMeta.ai_reply || null,
        reason: aiMeta.reason || null,
        provider: aiMeta.provider,
        model: aiMeta.model,
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
      setAiMeta({
        instruction: text || '',
        ai_reply: result.reply_text,
        reason: result.draft?.reason ?? '',
        provider: result.provider,
        model: result.model,
      })
      if (result.intent === 'propose' && result.draft) {
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
      setAiMeta({
        instruction: text,
        ai_reply: result.reply_text,
        reason: result.draft?.reason ?? aiMeta.reason,
        provider: result.provider,
        model: result.model,
      })
      if (result.intent === 'propose' && result.draft) {
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
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-[min(960px,100vw)] max-w-none flex-col gap-0 p-0">
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>AI 修订建议</SheetTitle>
          <SheetDescription>
            {entry
              ? `针对「${entry.title}」· AI 只生成候选草稿，对话关闭后不保存`
              : ''}
          </SheetDescription>
        </SheetHeader>

        <div className="grid min-h-0 flex-1 grid-cols-2 gap-4 overflow-hidden px-6 py-4">
          <div className="min-h-0 overflow-y-auto pr-1">
            {entry ? (
              <div className="rounded-md border bg-muted/30 p-3">
                <p className="text-caption font-medium text-muted-foreground">
                  当前内容（参考）
                </p>
                <h4 className="mt-1 text-body font-[650]">{entry.title}</h4>
                <p className="mt-1 whitespace-pre-wrap text-body-sm leading-6">
                  {entry.content}
                </p>
              </div>
            ) : null}
            {form ? (
              <div className="mt-3 space-y-3 rounded-md border border-brand/30 p-3">
                <div className="flex items-center gap-2">
                  <Badge className="bg-ai-candidate-soft text-ai-candidate">
                    <Sparkles className="mr-1 size-3.5" />
                    AI 候选草稿
                  </Badge>
                  {draft?.external_supplemented ? (
                    <Badge variant="outline" className="bg-amber-100 text-amber-700">
                      含 AI 外部补充
                    </Badge>
                  ) : null}
                </div>
                {draft?.reason ? (
                  <p className="text-caption text-muted-foreground">
                    修订原因：{draft.reason}
                  </p>
                ) : null}
                <div className="space-y-1.5">
                  <label htmlFor="revision-title" className="text-body-sm font-medium">
                    标题
                  </label>
                  <Textarea
                    id="revision-title"
                    value={form.title}
                    onChange={(event) => setForm({ ...form, title: event.target.value })}
                    rows={1}
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
                    rows={8}
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
                    <Textarea
                      id="revision-nature"
                      value={form.info_nature}
                      onChange={(event) =>
                        setForm({ ...form, info_nature: event.target.value })
                      }
                      rows={1}
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
                <div>
                  <p className="text-body-sm font-medium">变更说明（只读）</p>
                  <p className="mt-1 whitespace-pre-wrap text-body-sm leading-6 text-muted-foreground">
                    {form.change_summary || '（无）'}
                  </p>
                </div>
              </div>
            ) : busy ? (
              <p className="mt-3 text-body-sm text-muted-foreground">AI 思考中…</p>
            ) : (
              <p className="mt-3 rounded-md border border-dashed p-3 text-body-sm text-muted-foreground">
                AI 提出修订建议时，候选草稿会出现在这里；提问、讨论只会得到回复。
              </p>
            )}
          </div>

          <div className="flex min-h-0 flex-col">
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto rounded-md border p-3">
              {messages.length === 0 ? (
                <p className="text-body-sm text-muted-foreground">
                  跟 AI 讨论这条知识，或直接说想怎么改；AI 只在提出修订时生成草稿。
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
              <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-body-sm text-amber-700">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}
            <div className="mt-2 flex items-end gap-2">
              <Textarea
                aria-label="修订指令"
                className="min-h-0 flex-1"
                rows={3}
                value={instruction}
                placeholder={
                  messages.length === 0
                    ? '跟 AI 讨论这条知识，或直接说想怎么改…'
                    : '继续讨论或调整…'
                }
                onChange={(event) => setInstruction(event.target.value)}
                disabled={busy}
              />
              <Button
                disabled={busy || !instruction.trim()}
                onClick={sendMessage}
              >
                <Send />
                发送
              </Button>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t px-6 py-3">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy || apply.isPending}
          >
            放弃
          </Button>
          <Button onClick={() => apply.mutate()} disabled={!canApply}>
            应用
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
