import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  Bot,
  ChevronRight,
  CircleStop,
  FileSearch,
  ListOrdered,
  LoaderCircle,
  MessageSquarePlus,
  Quote,
  RefreshCw,
  RotateCcw,
  Send,
  Sparkles,
  Wrench,
} from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  cancelKnowledgeRun,
  createKnowledgeConversation,
  fetchKnowledgeMessages,
  fetchKnowledgeRunObservability,
  listKnowledgeConversations,
  submitKnowledgeMessage,
  type KnowledgeAnswerBlock,
  type KnowledgeConversationPayload,
  type KnowledgeMessagePayload,
  type KnowledgeObservabilityPayload,
  type KnowledgeRunPayload,
} from '@/lib/api'

const ACTIVE_RUN_STATUSES = new Set(['waiting', 'processing'])

const STATUS_LABELS: Record<string, string> = {
  waiting: '等待执行',
  processing: '正在处理',
  completed: '已完成',
  partial: '部分完成',
  partial_completed: '部分完成',
  not_executed: '未执行',
  unsupported: '暂不支持',
  failed: '未完成',
  cancelled: '已停止',
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function runDisplayStatus(run?: KnowledgeRunPayload | null) {
  if (!run) return 'completed'
  if (run.status === 'partial') return 'partial_completed'
  return run.dialogue_loop_status || run.status
}

function statusClasses(status: string) {
  if (status === 'completed') return 'border-success/30 bg-success-soft text-success'
  if (status === 'partial_completed' || status === 'not_executed') {
    return 'border-warning/30 bg-warning-soft text-warning'
  }
  if (status === 'unsupported' || status === 'failed') {
    return 'border-error/30 bg-error-soft text-error'
  }
  if (status === 'cancelled') return 'border-warning/30 bg-warning-soft text-warning'
  return 'border-ai-candidate/30 bg-ai-candidate-soft text-ai-candidate'
}

function blockTitle(block: KnowledgeAnswerBlock) {
  if (block.result_type === 'projects' || block.semantics?.subject === 'projects') {
    return '当前 Workspace 可访问项目'
  }
  if (block.semantics?.subject === 'directories') {
    return `${block.semantics.project_name || '当前项目'} · ${block.semantics.display_name || '项目目录'}`
  }
  return block.label || '正式记录列表'
}

function itemTitle(item: Record<string, unknown>, index: number) {
  return String(item.name ?? item.title ?? item.label ?? `记录 ${index + 1}`)
}

function AnswerBlockView({ block }: { block: KnowledgeAnswerBlock }) {
  if (block.kind === 'text') {
    return block.text ? <p className="whitespace-pre-wrap text-[14px] leading-7">{block.text}</p> : null
  }

  if (block.kind === 'insufficient') {
    return (
      <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5 text-sm text-warning" data-testid="agent-block-insufficient">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>{block.text || '材料不足，无法完成本轮回答。'}</span>
      </div>
    )
  }

  if (block.kind === 'candidate' || block.kind === 'candidate_text_only') {
    return (
      <section className="rounded-md border border-ai-candidate/30 bg-ai-candidate-soft/50 p-3" data-testid="agent-block-candidate">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ai-candidate">
          <Sparkles className="size-4" aria-hidden="true" />
          <span>AI 候选稿 · 待确认</span>
        </div>
        <p className="whitespace-pre-wrap text-[14px] leading-7 text-foreground">{block.text || block.content || '候选内容为空。'}</p>
      </section>
    )
  }

  if (block.kind === 'statistic') {
    return (
      <section className="rounded-md border border-border bg-card p-3" data-testid="agent-block-statistic">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <span className="text-[11px] font-semibold text-confirmed">可信统计</span>
            <h3 className="mt-0.5 text-sm font-semibold">{block.label || '知识库统计'}</h3>
            <p className="mt-1 text-xs text-muted-foreground">{block.semantics?.query_object || '正式记录'}</p>
          </div>
          {block.value !== null && block.value !== undefined ? (
            <strong className="text-2xl font-bold text-confirmed">{String(block.value)}</strong>
          ) : null}
        </div>
        {block.buckets?.length ? (
          <div className="mt-3 grid gap-1.5 border-t pt-2">
            {block.buckets.map((bucket, index) => (
              <div className="flex items-center justify-between text-sm" key={`${bucket.key || bucket.label}-${index}`}>
                <span>{bucket.label || bucket.key || '未命名'}</span>
                <strong>{bucket.count ?? 0}</strong>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    )
  }

  if (block.kind === 'list') {
    const total = block.semantics?.total_count
    const returned = block.semantics?.returned_count ?? block.items?.length ?? 0
    return (
      <section className="overflow-hidden rounded-md border border-border bg-card" data-testid="agent-block-list">
        <div className="flex items-center gap-2 border-b px-3 py-2.5">
          <ListOrdered className="size-4 text-confirmed" aria-hidden="true" />
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold">{blockTitle(block)}</h3>
            <p className="text-xs text-muted-foreground">{total === undefined ? `${returned} 条` : `总数 ${total}，本次返回 ${returned}`}</p>
          </div>
        </div>
        <ol className="divide-y">
          {(block.items || []).map((item, index) => (
            <li className="grid grid-cols-[24px_minmax(0,1fr)] gap-2 px-3 py-2.5" key={`${String(item.id ?? item.entry_id ?? item.node_id ?? index)}`}>
              <span className="flex size-5 items-center justify-center rounded bg-muted text-[11px] text-muted-foreground">{index + 1}</span>
              <div className="min-w-0">
                <strong className="block truncate text-sm">{itemTitle(item, index)}</strong>
                <span className="block truncate text-xs text-muted-foreground">
                  {String(item.project_name ?? item.path ?? item.summary ?? item.excerpt ?? '')}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>
    )
  }

  if (block.kind === 'entry') {
    return (
      <section className="rounded-md border border-border bg-card" data-testid="agent-block-entry">
        <div className="flex items-center gap-2 border-b px-3 py-2.5">
          <BookOpen className="size-4 text-confirmed" aria-hidden="true" />
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold">{block.title || block.entry_title || '已读取知识正文'}</h3>
            <p className="truncate text-xs text-muted-foreground">{[block.project_name, block.node_path].filter(Boolean).join(' · ')}</p>
          </div>
        </div>
        <div className="whitespace-pre-wrap px-3 py-3 text-sm leading-7">{block.content || block.text || '正文为空。'}</div>
      </section>
    )
  }

  if (block.kind === 'evidence') {
    return (
      <details className="group rounded-md border border-border bg-card" data-testid="agent-block-evidence">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm font-medium [&::-webkit-details-marker]:hidden">
          <Quote className="size-4 text-confirmed" aria-hidden="true" />
          <span>查看已核验来源</span>
          <ChevronRight className="ml-auto size-4 transition-transform group-open:rotate-90" aria-hidden="true" />
        </summary>
        <div className="border-t px-3 py-3 text-sm leading-6">
          <p className="text-xs text-muted-foreground">{[block.entry_title, block.source_title].filter(Boolean).join(' · ') || `Entry ${block.entry_id ?? '未知'} · Source ${block.source_id ?? '未知'}`}</p>
          <p className="mt-2 whitespace-pre-wrap">{block.text || block.content || '来源正文未随公开结果返回。'}</p>
        </div>
      </details>
    )
  }

  return null
}

function ExecutionDetails({ trace }: { trace?: KnowledgeObservabilityPayload }) {
  if (!trace) return null
  return (
    <details className="group mt-3 rounded-md border border-border/80 bg-muted/30 text-xs" data-testid="agent-execution-details">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-muted-foreground [&::-webkit-details-marker]:hidden">
        <FileSearch className="size-3.5" aria-hidden="true" />
        <span>执行记录</span>
        <span className="ml-auto">{trace.tool_calls.length} 个工具 · {trace.model_invocations.length} 次模型调用</span>
        <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden="true" />
      </summary>
      <div className="grid gap-2 border-t px-3 py-2.5">
        {trace.tool_calls.map((call) => (
          <div className="flex items-center gap-2" key={call.id}>
            <Wrench className="size-3.5" aria-hidden="true" />
            <span>{call.tool_name}</span>
            <span className="text-muted-foreground">{call.status}</span>
            {call.error ? <span className="text-error">{call.error}</span> : null}
          </div>
        ))}
        {trace.model_invocations.map((call) => (
          <div className="flex items-center gap-2" key={call.id}>
            <Sparkles className="size-3.5" aria-hidden="true" />
            <span>{call.provider}{call.model ? ` · ${call.model}` : ''}</span>
            <span className={call.is_fallback ? 'text-warning' : 'text-muted-foreground'}>{call.outcome}</span>
          </div>
        ))}
      </div>
    </details>
  )
}

function AssistantMessage({
  message,
  run,
  trace,
  onContinue,
}: {
  message: KnowledgeMessagePayload
  run?: KnowledgeRunPayload
  trace?: KnowledgeObservabilityPayload
  onContinue: (run: KnowledgeRunPayload) => void
}) {
  const status = runDisplayStatus(run)
  const running = Boolean(run && ACTIVE_RUN_STATUSES.has(run.status))
  const blocks = run?.dialogue_blocks || []
  const fallbackText = blocks.length === 0 ? run?.answer?.answer || message.content : null
  return (
    <article className="flex gap-3" data-testid="agent-assistant-message">
      <div className="flex size-7 shrink-0 items-center justify-center rounded-md bg-ai-candidate-soft text-ai-candidate">
        <Bot className="size-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-h-7 flex-wrap items-center gap-2">
          <strong className="text-sm">知识 Agent</strong>
          <Badge variant="outline" className={`h-6 rounded-full px-2 text-[11px] ${statusClasses(status)}`}>
            {running ? <LoaderCircle className="size-3 animate-spin" aria-hidden="true" /> : null}
            {STATUS_LABELS[status] || status}
          </Badge>
          {run?.updated_at ? <time className="ml-auto text-xs text-muted-foreground">{formatTime(run.updated_at)}</time> : null}
        </div>
        <div className="mt-2 grid gap-2">
          {blocks.map((block, index) => <AnswerBlockView block={block} key={`${block.kind}-${index}`} />)}
          {fallbackText ? <p className="whitespace-pre-wrap text-sm leading-7">{fallbackText}</p> : null}
          {running && !blocks.length ? (
            <div className="flex items-center gap-2 rounded-md bg-muted/60 px-3 py-2 text-sm text-muted-foreground" role="status">
              <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              <span>{run?.current_step === 'dialogue_loop' ? '统一对话循环处理中…' : '正在准备本轮回答…'}</span>
            </div>
          ) : null}
          {run && ['partial_completed', 'not_executed', 'unsupported', 'failed'].includes(status) ? (
            <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>{run.error || STATUS_LABELS[status] || '本轮未完整完成。'}</span>
            </div>
          ) : null}
          {run?.can_continue ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
              <span className="text-muted-foreground">本轮保留了已完成材料，可以继续未完成步骤。</span>
              <Button size="sm" variant="outline" onClick={() => onContinue(run)} data-testid="agent-continue">
                <RotateCcw />继续
              </Button>
            </div>
          ) : null}
          {!running ? <ExecutionDetails trace={trace} /> : null}
        </div>
      </div>
    </article>
  )
}

function MessageList({
  messages,
  runs,
  traces,
  onContinue,
}: {
  messages: KnowledgeMessagePayload[]
  runs: KnowledgeRunPayload[]
  traces: Record<number, KnowledgeObservabilityPayload>
  onContinue: (run: KnowledgeRunPayload) => void
}) {
  const runMap = useMemo(() => new Map(runs.map((run) => [run.id, run])), [runs])
  if (!messages.length) {
    return (
      <div className="flex min-h-[55vh] flex-col items-center justify-center text-center text-muted-foreground" data-testid="agent-empty-state">
        <Bot className="mb-3 size-8 text-brand" aria-hidden="true" />
        <strong className="text-base text-foreground">开始一轮知识对话</strong>
        <p className="mt-1 text-sm">可以查询项目、阅读正式记录，也可以继续追问上一轮结果。</p>
      </div>
    )
  }
  return (
    <div className="grid gap-8">
      {messages.map((message) => {
        if (message.message_type === 'scope_change') {
          return <div className="text-center text-xs text-muted-foreground" key={message.id}>{message.content}</div>
        }
        if (message.role === 'user') {
          return <div className="ml-auto max-w-[74%] rounded-md rounded-br-sm bg-brand px-3.5 py-2.5 text-sm leading-6 text-white" data-testid="agent-user-message" key={message.id}>{message.content}</div>
        }
        const run = message.run_id ? runMap.get(message.run_id) : undefined
        return <AssistantMessage key={message.id} message={message} run={run} trace={run ? traces[run.id] : undefined} onContinue={onContinue} />
      })}
    </div>
  )
}

export function KnowledgeAgentPage() {
  const [conversations, setConversations] = useState<KnowledgeConversationPayload[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [messages, setMessages] = useState<KnowledgeMessagePayload[]>([])
  const [runs, setRuns] = useState<KnowledgeRunPayload[]>([])
  const [traces, setTraces] = useState<Record<number, KnowledgeObservabilityPayload>>({})
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const selectedIdRef = useRef<number | null>(null)
  const tracesRef = useRef<Record<number, KnowledgeObservabilityPayload>>({})

  const selected = conversations.find((conversation) => conversation.id === selectedId) || null
  const activeRun = runs.find((run) => ACTIVE_RUN_STATUSES.has(run.status)) || null
  const activeRunId = activeRun?.id ?? null

  const refresh = useCallback(async (preferredId: number | null = selectedIdRef.current) => {
    setRefreshing(true)
    try {
      let nextConversations = await listKnowledgeConversations()
      if (!nextConversations.length) {
        const created = await createKnowledgeConversation()
        nextConversations = [created]
      }
      const nextId = preferredId && nextConversations.some((item) => item.id === preferredId)
        ? preferredId
        : nextConversations[0].id
      const page = await fetchKnowledgeMessages(nextId)
      setConversations(nextConversations)
      selectedIdRef.current = nextId
      setSelectedId(nextId)
      setMessages(page.items)
      setRuns(page.runs)
      const missingRuns = page.runs.filter((run) => !ACTIVE_RUN_STATUSES.has(run.status) && !tracesRef.current[run.id])
      if (missingRuns.length) {
        const entries = await Promise.all(missingRuns.map(async (run) => {
          try {
            return await fetchKnowledgeRunObservability(run.id)
          } catch {
            return null
          }
        }))
        setTraces((current) => {
          const next = { ...current }
          entries.forEach((entry) => {
            if (entry) next[entry.run_id] = entry
          })
          tracesRef.current = next
          return next
        })
      }
      setError(null)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError('登录状态已失效，请重新登录。')
      } else {
        setError(cause instanceof Error ? cause.message : '知识 Agent 暂时无法连接。')
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0)
    return () => window.clearTimeout(timer)
  }, [refresh])

  useEffect(() => {
    if (selectedId === null) return
    const timer = window.setTimeout(() => void refresh(selectedId), 0)
    return () => window.clearTimeout(timer)
  }, [refresh, selectedId])

  useEffect(() => {
    if (!selectedId || activeRunId === null) return
    const timer = window.setInterval(() => void refresh(selectedId), 900)
    return () => window.clearInterval(timer)
  }, [activeRunId, selectedId, refresh])

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages.length, activeRun?.current_step])

  async function createConversation() {
    try {
      const conversation = await createKnowledgeConversation()
      setMessage('')
      await refresh(conversation.id)
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : '新建会话失败')
    }
  }

  async function send(value = message) {
    const trimmed = value.trim()
    if (!selectedId || !trimmed || submitting || activeRun) return
    setSubmitting(true)
    setMessage('')
    try {
      await submitKnowledgeMessage(selectedId, trimmed, crypto.randomUUID())
      await refresh(selectedId)
    } catch (cause) {
      setMessage(trimmed)
      toast.error(cause instanceof Error ? cause.message : '消息发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function stop() {
    if (!activeRun) return
    try {
      await cancelKnowledgeRun(activeRun.id)
      await refresh(selectedId)
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : '停止失败')
    }
  }

  async function continueRun() {
    await send('继续')
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void send()
    }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground" role="status"><LoaderCircle className="size-4 animate-spin" />正在读取知识对话…</div>
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[228px_minmax(0,1fr)] bg-card" data-testid="knowledge-agent-page">
      <aside className="flex min-h-0 flex-col border-r bg-sidebar" data-testid="agent-conversation-rail">
        <div className="flex items-center justify-between border-b px-3 py-3">
          <div className="flex min-w-0 items-center gap-2">
            <Bot className="size-4 shrink-0 text-brand" aria-hidden="true" />
            <h1 className="truncate text-sm font-semibold">知识 Agent</h1>
          </div>
          <Button size="icon-sm" variant="ghost" onClick={() => void refresh(selectedId)} disabled={refreshing} title="刷新会话" aria-label="刷新会话">
            <RefreshCw className={refreshing ? 'animate-spin' : ''} />
          </Button>
        </div>
        <div className="p-3">
          <Button className="w-full justify-start" variant="outline" onClick={() => void createConversation()} disabled={Boolean(activeRun)} data-testid="agent-new-conversation">
            <MessageSquarePlus />新建会话
          </Button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="知识 Agent 对话">
          {conversations.map((conversation) => (
            <button
              type="button"
              key={conversation.id}
              onClick={() => {
                selectedIdRef.current = conversation.id
                setSelectedId(conversation.id)
              }}
              className={`mb-1 flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors ${selectedId === conversation.id ? 'bg-brand-soft text-brand' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
              data-testid="agent-conversation-item"
            >
              <span className="min-w-0 truncate">{conversation.title || '新对话'}</span>
              {conversation.recent_run_status && ACTIVE_RUN_STATUSES.has(conversation.recent_run_status) ? <LoaderCircle className="size-3.5 shrink-0 animate-spin" aria-label="处理中" /> : null}
            </button>
          ))}
        </nav>
      </aside>

      <section className="flex min-h-0 min-w-0 flex-col bg-card">
        <header className="flex min-h-[58px] shrink-0 items-center justify-between gap-4 border-b px-6">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold">{selected?.title || '知识 Agent'}</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">{selected?.scope_type === 'project' ? `项目：${selected.project_name || '当前项目'}` : 'Workspace 全部知识'}</p>
          </div>
          <Badge variant="outline" className="border-confirmed/30 bg-confirmed-soft text-confirmed">正式 Agent</Badge>
        </header>
        {error ? <div className="flex items-center gap-2 border-b border-error/20 bg-error-soft px-6 py-2.5 text-sm text-error" role="alert"><AlertTriangle className="size-4" />{error}</div> : null}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-7" data-testid="agent-message-list">
          <MessageList messages={messages} runs={runs} traces={traces} onContinue={() => void continueRun()} />
          <div ref={endRef} />
        </div>
        <footer className="shrink-0 border-t bg-card px-6 py-4">
          <div className="flex items-end gap-2">
            <Textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="问知识库中的任何问题…"
              rows={2}
              maxLength={2000}
              disabled={!selectedId || Boolean(activeRun) || submitting}
              aria-label="输入知识问题"
              data-testid="agent-composer"
            />
            {activeRun ? (
              <Button size="icon" variant="destructive" onClick={() => void stop()} title="停止当前运行" aria-label="停止当前运行" data-testid="agent-stop">
                <CircleStop />
              </Button>
            ) : (
              <Button size="icon" onClick={() => void send()} disabled={!message.trim() || submitting || !selectedId} title="发送消息" aria-label="发送消息" data-testid="agent-send">
                {submitting ? <LoaderCircle className="animate-spin" /> : <Send />}
              </Button>
            )}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">回答只作为当前 Workspace 的知识检索与整理结果；AI 候选稿需要人工确认。</p>
        </footer>
      </section>
    </div>
  )
}
