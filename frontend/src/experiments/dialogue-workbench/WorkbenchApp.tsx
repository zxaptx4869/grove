import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  Bot,
  Check,
  ChevronRight,
  CircleStop,
  Clock3,
  Copy,
  Database,
  Download,
  FileSearch,
  ListOrdered,
  LoaderCircle,
  MessageSquarePlus,
  Send,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  Wrench,
} from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import * as api from './api'
import type {
  AnswerBlock,
  Conversation,
  Feedback,
  ModelCall,
  ToolCall,
  Turn,
  WorkbenchState,
} from './types'

const STAGES: Record<string, string> = {
  queued: '等待执行',
  organizing: '组织回答中',
  querying: '查询知识库中',
  reading_entries: '读取记录中',
  reading_sources: '核验来源中',
  finalizing: '预算内收尾中',
  cancelling: '正在停止',
  completed: '已完成',
  failed: '未完成',
  cancelled: '已停止',
  interrupted: '已中断',
}

const FEEDBACK_LABELS: Record<Feedback['kind'], string> = {
  wrong: '答错了',
  misunderstood: '没理解',
  omitted: '漏答',
}

function formatDate(value?: string | null) {
  if (!value) return '未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function formatDuration(ms?: number) {
  if (ms == null) return '未知'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} 秒`
}

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function statusTone(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'interrupted') return 'error'
  if (status === 'cancelled') return 'warning'
  return 'running'
}

function AnswerBlockView({ block }: { block: AnswerBlock }) {
  if (block.kind === 'text') return block.text ? <p className="answer-copy">{block.text}</p> : null
  if (block.kind === 'insufficient') {
    return (
      <div className="notice-block warning-block">
        <AlertTriangle aria-hidden="true" />
        <span>{block.text || '材料不足，无法完成本轮回答。'}</span>
      </div>
    )
  }
  if (block.kind === 'statistic') {
    return (
      <section className="result-block statistic-block" aria-label="可信统计">
        <div>
          <span className="block-kicker">可信统计</span>
          <strong>{block.text || block.label || '统计结果'}</strong>
        </div>
        {block.value != null && <span className="stat-value">{String(block.value)}</span>}
        {block.buckets && block.buckets.length > 0 && (
          <div className="bucket-list">
            {block.buckets.map((bucket, index) => (
              <div key={`${bucket.key ?? bucket.label}-${index}`}>
                <span>{bucket.label ?? bucket.key ?? '未命名'}</span>
                <strong>{bucket.count ?? 0}</strong>
              </div>
            ))}
          </div>
        )}
      </section>
    )
  }
  if (block.kind === 'list') {
    return (
      <section className="result-block list-block" aria-label={block.label || '知识列表'}>
        <div className="block-heading">
          <ListOrdered aria-hidden="true" />
          <div>
            <strong>{block.label || '知识列表'}</strong>
            <span>{block.items?.length ?? 0} 条，保持工具返回顺序</span>
          </div>
        </div>
        <ol>
          {(block.items ?? []).map((item, index) => (
            <li key={String(item.entry_id ?? index)}>
              <span className="item-index">{index + 1}</span>
              <div>
                <strong>{String(item.title ?? `记录 ${item.entry_id ?? index + 1}`)}</strong>
                <span>
                  {[item.project_name, item.main_type, item.summary]
                    .filter(Boolean)
                    .map(String)
                    .join(' · ')}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>
    )
  }
  if (block.kind === 'evidence') {
    return (
      <details className="source-block">
        <summary>
          <BookOpen aria-hidden="true" />
          <span>查看已核验来源</span>
          <ChevronRight className="detail-chevron" aria-hidden="true" />
        </summary>
        <div className="source-body">
          <span>
            Entry {block.entry_id ?? '未知'} · Source {block.source_id ?? '未知'}
          </span>
          <p>{block.text || '来源正文未随公开结果返回。'}</p>
        </div>
      </details>
    )
  }
  return null
}

function ToolRow({ call }: { call: ToolCall }) {
  const params = call.params ?? {}
  return (
    <div className="trace-row">
      <div className="trace-row-head">
        <Wrench aria-hidden="true" />
        <strong>{call.tool || call.shared_tool || '未知工具'}</strong>
        <span>{call.status || '未知状态'}</span>
        <time>{formatDuration(call.duration_ms)}</time>
      </div>
      <pre>{pretty(params)}</pre>
      {call.result_summary && <p>结果摘要：{pretty(call.result_summary)}</p>}
      {call.result_handle && <p>结果句柄：{call.result_handle}</p>}
      {call.completeness && <p>完整性：{call.completeness}</p>}
      {call.error && <p className="trace-error">{call.error}</p>}
    </div>
  )
}

function ModelRow({ call, index }: { call: ModelCall; index: number }) {
  const input = call.actual_input_tokens ?? call.usage?.input_tokens
  return (
    <div className="trace-row">
      <div className="trace-row-head">
        <Sparkles aria-hidden="true" />
        <strong>{call.finalize_only ? '独立收尾请求' : `模型请求 ${index + 1}`}</strong>
        <span>{call.request_scope || call.kind || '未知范围'}</span>
        <time>{formatDuration(call.duration_ms)}</time>
      </div>
      <p>实际输入 token：{input == null ? '未知' : String(input)}</p>
      <p>
        输入估算：
        {call.estimated_input_tokens == null ? '未知' : `${call.estimated_input_tokens} token`}
      </p>
      <p>费用：未知</p>
      {(call.error || call.error_kind) && (
        <p className="trace-error">{call.error || call.error_kind}</p>
      )}
    </div>
  )
}

function FeedbackEditor({
  conversationId,
  turn,
  disabled,
  onSaved,
}: {
  conversationId: string
  turn: Turn
  disabled: boolean
  onSaved: () => void
}) {
  const [kind, setKind] = useState<Feedback['kind'] | null>(turn.feedback?.kind ?? null)
  const [note, setNote] = useState(turn.feedback?.note ?? '')
  const [open, setOpen] = useState(Boolean(turn.feedback))
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!kind) return
    setSaving(true)
    try {
      await api.saveFeedback(conversationId, turn.id, kind, note)
      toast.success('反馈已保存到本地记录')
      onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '反馈保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (disabled && !turn.feedback) return null
  return (
    <div className="feedback-editor">
      <button type="button" className="feedback-toggle" onClick={() => setOpen(!open)}>
        <ThumbsDown aria-hidden="true" />
        {turn.feedback ? `已标记：${FEEDBACK_LABELS[turn.feedback.kind]}` : '反馈这轮回答'}
      </button>
      {open && (
        <div className="feedback-form">
          <div className="feedback-options" aria-label="反馈类型">
            {(Object.keys(FEEDBACK_LABELS) as Feedback['kind'][]).map((value) => (
              <button
                type="button"
                className={kind === value ? 'selected' : ''}
                onClick={() => setKind(value)}
                disabled={disabled}
                key={value}
              >
                {FEEDBACK_LABELS[value]}
              </button>
            ))}
          </div>
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="补充具体问题（可选）"
            rows={2}
            maxLength={2000}
            disabled={disabled}
          />
          {!disabled && (
            <Button size="sm" variant="outline" disabled={!kind || saving} onClick={save}>
              {saving ? <LoaderCircle className="animate-spin" /> : <Check />}
              保存反馈
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function AssistantTurn({
  conversation,
  turn,
  onRefresh,
}: {
  conversation: Conversation
  turn: Turn
  onRefresh: () => void
}) {
  const running = turn.status === 'queued' || turn.status === 'running'
  const blocks = turn.blocks?.length
    ? turn.blocks
    : turn.answer
      ? [{ kind: 'text', text: turn.answer }]
      : []
  return (
    <article className="turn-pair" data-turn-status={turn.status}>
      <div className="user-message">{turn.user_message}</div>
      <div className="assistant-message">
        <div className="assistant-mark">
          <Bot aria-hidden="true" />
        </div>
        <div className="assistant-body">
          <div className="turn-meta">
            <strong>知识 Agent</strong>
            <span className={`turn-status ${statusTone(turn.status)}`}>
              {running && <LoaderCircle className="animate-spin" aria-hidden="true" />}
              {STAGES[turn.stage] || turn.stage}
            </span>
            {!running && <time>{formatDuration(turn.duration_ms)}</time>}
          </div>
          {blocks.map((block, index) => (
            <AnswerBlockView block={block as AnswerBlock} key={`${block.kind}-${index}`} />
          ))}
          {running && blocks.length === 0 && (
            <div className="stage-line">
              <span />
              {STAGES[turn.stage] || '执行中'}
            </div>
          )}
          {turn.error && (
            <div className="turn-error">
              <AlertTriangle />
              {turn.error}
            </div>
          )}
          {!running && (
            <details className="execution-trace">
              <summary>
                <FileSearch aria-hidden="true" />
                <span>执行记录</span>
                <small>
                  {turn.tool_calls?.length ?? 0} 个工具 · {turn.model_calls?.length ?? 0} 次模型调用
                </small>
                <ChevronRight className="detail-chevron" aria-hidden="true" />
              </summary>
              <div className="trace-body">
                <div className="trace-summary">
                  <span>总耗时 {formatDuration(turn.duration_ms)}</span>
                  <span>收尾：{String(turn.finalization?.status ?? '未发生')}</span>
                  <span>材料：{turn.blocks?.length ?? 0} 个公开块</span>
                </div>
                {(turn.tool_calls ?? []).map((call, index) => (
                  <ToolRow call={call} key={index} />
                ))}
                {(turn.model_calls ?? []).map((call, index) => (
                  <ModelRow call={call} index={index} key={index} />
                ))}
                {(turn.error_details || turn.solve_error) && (
                  <pre className="diagnostic-json">
                    {pretty(turn.error_details || turn.solve_error)}
                  </pre>
                )}
              </div>
            </details>
          )}
          {!running && (
            <FeedbackEditor
              conversationId={conversation.id}
              turn={turn}
              disabled={conversation.read_only}
              onSaved={onRefresh}
            />
          )}
        </div>
      </div>
    </article>
  )
}

export function WorkbenchApp() {
  const [state, setState] = useState<WorkbenchState | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [fatalError, setFatalError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const conversations = useMemo(
    () => state?.sessions.flatMap((session) => session.conversations) ?? [],
    [state],
  )
  const selected =
    conversations.find((conversation) => conversation.id === selectedId) ?? conversations[0]
  const activeTurn = selected?.turns.find((turn) => turn.id === state?.active_turn_id)

  const refresh = useCallback(async () => {
    try {
      setState(await api.fetchState())
    } catch (error) {
      if (error instanceof api.WorkbenchApiError && error.status === 401) {
        setState(await api.bootstrap())
      } else {
        throw error
      }
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function start() {
      try {
        let value = await api.bootstrap()
        const activeConversations =
          value.sessions.find((session) => session.active)?.conversations ?? []
        if (activeConversations.length === 0) {
          const created = (await api.createConversation()) as Conversation
          value = await api.fetchState()
          if (!cancelled) setSelectedId(created.id)
        }
        if (!cancelled) setState(value)
      } catch (error) {
        if (!cancelled) setFatalError(error instanceof Error ? error.message : '工作台启动失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void start()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!state?.active_turn_id) return
    const timer = window.setInterval(() => {
      void refresh()
    }, 450)
    return () => window.clearInterval(timer)
  }, [refresh, state?.active_turn_id])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [selected?.turns.length, activeTurn?.stage])

  async function newConversation() {
    try {
      const conversation = (await api.createConversation()) as Conversation
      await refresh()
      setSelectedId(conversation.id)
      setMessage('')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '新建对话失败')
    }
  }

  async function send() {
    const value = message.trim()
    if (!selected || !value || submitting || state?.active_turn_id) return
    setSubmitting(true)
    setMessage('')
    try {
      await api.submitTurn(selected.id, value, crypto.randomUUID())
      await refresh()
    } catch (error) {
      setMessage(value)
      toast.error(error instanceof Error ? error.message : '消息发送失败')
    } finally {
      setSubmitting(false)
    }
  }

  async function stop() {
    if (!selected || !activeTurn) return
    try {
      await api.cancelTurn(selected.id, activeTurn.id)
      await refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '停止失败')
    }
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void send()
    }
  }

  const budgetExhausted = state ? state.budget.remaining.text_requests <= 0 : false
  const inputDisabled =
    !selected ||
    selected.read_only ||
    Boolean(state?.active_turn_id) ||
    budgetExhausted ||
    state?.metadata.status !== 'ready'

  if (loading)
    return (
      <div className="workbench-loading">
        <LoaderCircle className="animate-spin" />
        正在连接实验服务
      </div>
    )
  if (fatalError || !state)
    return (
      <div className="workbench-loading error">
        <AlertTriangle />
        {fatalError || '无法读取实验状态'}
      </div>
    )

  return (
    <>
      <div className="narrow-notice">
        <Database />
        <strong>请使用电脑访问实验工作台</strong>
        <span>需要至少 1024px 的浏览器宽度。</span>
      </div>
      <main className="workbench-shell">
        <aside className="conversation-rail">
          <header className="rail-brand">
            <span>G</span>
            <div>
              <strong>Agent 实验台</strong>
              <small>{state.metadata.experiment_version}</small>
            </div>
          </header>
          <Button
            className="new-conversation"
            variant="outline"
            onClick={newConversation}
            disabled={Boolean(state.active_turn_id) || state.metadata.status !== 'ready'}
          >
            <MessageSquarePlus />
            新建对话
          </Button>
          <nav aria-label="实验对话">
            {state.sessions
              .filter((session) => session.active || session.conversations.length > 0)
              .map((session) => (
                <section key={session.id}>
                  <h2>
                    {session.active ? '本次运行' : formatDate(session.created_at)}
                    {!session.active && session.offline ? ' · 离线验收' : ''}
                  </h2>
                  {session.conversations.map((conversation) => (
                    <button
                      type="button"
                      className={
                        selected?.id === conversation.id
                          ? 'conversation-item selected'
                          : 'conversation-item'
                      }
                      onClick={() => setSelectedId(conversation.id)}
                      key={conversation.id}
                    >
                      <span>{conversation.title}</span>
                      <small>
                        {conversation.read_only ? '只读' : `${conversation.turns.length} 轮`}
                      </small>
                    </button>
                  ))}
                </section>
              ))}
          </nav>
          <button
            type="button"
            className="export-button"
            onClick={() => void api.downloadExport().catch((error) => toast.error(String(error)))}
          >
            <Download />
            导出脱敏记录
          </button>
        </aside>

        <section className="chat-column">
          <header className="chat-header">
            <div>
              <h1>{selected?.title || '知识 Agent 实验'}</h1>
              <p>统一对话循环 · 单实验串行</p>
            </div>
            <Badge
              variant="outline"
              className={state.metadata.offline ? 'offline-badge' : 'live-badge'}
            >
              {state.metadata.offline ? '离线桩，仅验收' : '真实模型'}
            </Badge>
          </header>
          {selected?.recovery_notice && (
            <div className="recovery-notice">
              <AlertTriangle />
              {selected.recovery_notice}
            </div>
          )}
          <div className="message-scroll">
            {selected?.turns.length ? (
              selected.turns.map((turn) => (
                <AssistantTurn
                  conversation={selected}
                  turn={turn}
                  onRefresh={() => void refresh()}
                  key={turn.id}
                />
              ))
            ) : (
              <div className="empty-state">
                <Bot />
                <strong>开始自由提问</strong>
                <p>可以追问、切换话题，也可以引用此前列表中的对象。</p>
              </div>
            )}
            <div ref={endRef} />
          </div>
          <footer className="composer-wrap">
            {(budgetExhausted || state.metadata.unsafe_reason) && (
              <div className="composer-warning">
                <AlertTriangle />
                {state.metadata.unsafe_reason || '本批文本请求预算已用尽，不会自动重置。'}
              </div>
            )}
            <div className="composer">
              <Textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder={
                  selected?.read_only ? '旧运行只读，请新建对话' : '问知识库中的任何问题…'
                }
                rows={3}
                disabled={inputDisabled}
                aria-label="输入消息"
              />
              {activeTurn ? (
                <Button
                  size="icon"
                  variant="destructive"
                  onClick={stop}
                  title="停止生成"
                  aria-label="停止生成"
                >
                  <CircleStop />
                </Button>
              ) : (
                <Button
                  size="icon"
                  onClick={() => void send()}
                  disabled={inputDisabled || !message.trim() || submitting}
                  title="发送"
                  aria-label="发送"
                >
                  <Send />
                </Button>
              )}
            </div>
            <p>Enter 发送，Shift + Enter 换行。回答仅用于实验判断。</p>
          </footer>
        </section>

        <aside className="diagnostic-rail">
          <section className="diagnostic-section">
            <h2>运行状态</h2>
            <div className={`run-state ${state.metadata.status}`}>
              <ShieldCheck />
              <div>
                <strong>{state.metadata.status === 'ready' ? '隔离环境就绪' : '实验已停止'}</strong>
                <span>
                  {state.active_turn_id ? STAGES[activeTurn?.stage || 'queued'] : '等待提问'}
                </span>
              </div>
            </div>
            <dl>
              <div>
                <dt>Provider</dt>
                <dd>{state.metadata.provider}</dd>
              </div>
              <div>
                <dt>模型</dt>
                <dd>{state.metadata.model}</dd>
              </div>
              <div>
                <dt>数据快照</dt>
                <dd>{formatDate(state.metadata.snapshot_at)}</dd>
              </div>
              <div>
                <dt>指纹</dt>
                <dd>{state.metadata.snapshot_fingerprint}</dd>
              </div>
            </dl>
          </section>
          <section className="diagnostic-section">
            <h2>共享预算</h2>
            <div className="budget-number">
              <strong>{state.budget.remaining.text_requests}</strong>
              <span>次文本请求剩余</span>
            </div>
            <div className="budget-bar">
              <span
                style={{
                  width: `${Math.min(100, (state.budget.used.text_requests / state.budget.text_requests_per_batch) * 100)}%`,
                }}
              />
            </div>
            <dl>
              <div>
                <dt>文本请求</dt>
                <dd>
                  {state.budget.used.text_requests} / {state.budget.text_requests_per_batch}
                </dd>
              </div>
              <div>
                <dt>向量请求</dt>
                <dd>
                  {state.budget.used.embedding_requests} /{' '}
                  {state.budget.embedding_requests_per_batch}
                </dd>
              </div>
              <div>
                <dt>单轮文本上限</dt>
                <dd>{state.budget.text_requests_per_turn}</dd>
              </div>
              <div>
                <dt>单次输入硬上限</dt>
                <dd>{state.budget.model_input_tokens_per_request} token</dd>
              </div>
              <div>
                <dt>求解 / 收尾</dt>
                <dd>
                  {state.budget.solve_seconds_per_turn}s / {state.budget.finalize_seconds}s
                </dd>
              </div>
            </dl>
            <p className="budget-note">
              新建对话和刷新不会重置预算。估算与实际 usage 在每轮执行记录中分开显示。
            </p>
          </section>
          <section className="diagnostic-section storage-section">
            <h2>本地记录</h2>
            <div>
              <Database />
              <code>{state.metadata.storage_path}</code>
              <button
                type="button"
                aria-label="复制记录路径"
                title="复制路径"
                onClick={() =>
                  void navigator.clipboard
                    .writeText(state.metadata.storage_path)
                    .then(() => toast.success('路径已复制'))
                }
              >
                <Copy />
              </button>
            </div>
            <p>仅保存脱敏回答、公开诊断和反馈。</p>
          </section>
          <section className="diagnostic-section legend-section">
            <h2>执行阶段</h2>
            <p>
              <Clock3 />
              页面只展示模型派发、工具查询、来源核验和收尾等真实事件，不展示隐藏推理。
            </p>
          </section>
        </aside>
      </main>
    </>
  )
}
