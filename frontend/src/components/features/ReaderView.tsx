import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BookOpen, Send, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { DirectoryTreeSelect } from '@/components/features/DirectoryTreeSelect'
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
  askReader,
  fetchEntry,
  fetchProjectTree,
  saveReaderAnswer,
  type EntryPayload,
  type ReaderAnswerPayload,
  type ReaderScope,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

interface ReaderMessage {
  role: 'user' | 'assistant'
  content: string
  answer?: ReaderAnswerPayload
}

const MAIN_TYPE_LABELS: Record<string, string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

const INFO_NATURE_LABELS: Record<string, string> = {
  fact: '事实',
  experience: '经验',
  advice: '建议',
  speculation: '推测',
  other: '其他',
}

/** AI 阅读视图：节点或项目范围的带引用问答，回答可保存为候选。 */
export function ReaderView({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient()
  const [scope, setScope] = useState<ReaderScope>('project')
  const [nodeId, setNodeId] = useState<number | null>(null)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<ReaderMessage[]>([])
  const [asking, setAsking] = useState(false)
  const [previewEntryId, setPreviewEntryId] = useState<number | null>(null)
  const [saveTarget, setSaveTarget] = useState<{
    question: string
    answer: ReaderAnswerPayload
  } | null>(null)

  const tree = useQuery({
    queryKey: queryKeys.projectTree(projectId),
    queryFn: () => fetchProjectTree(projectId),
    enabled: Number.isFinite(projectId),
  })

  const preview = useQuery({
    queryKey: queryKeys.readerPreview(previewEntryId ?? 0),
    queryFn: () => fetchEntry(previewEntryId!),
    enabled: previewEntryId != null,
  })

  const save = useMutation({
    mutationFn: (payload: {
      question: string
      title: string
      content: string
      citations: { entry_id: number; source_id: number; quote: string }[]
      main_type?: 'knowledge' | 'method' | 'parameter' | 'reminder' | null
      info_nature?: 'fact' | 'experience' | 'advice' | 'speculation' | 'other' | null
    }) => saveReaderAnswer(projectId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.reviewCandidates(projectId) })
      queryClient.invalidateQueries({ queryKey: queryKeys.sources })
      toast.success('已保存为候选，可在确认台确认')
      setSaveTarget(null)
    },
    onError: (error: Error) => {
      toast.error(`保存失败：${error.message}`)
    },
  })

  async function submit() {
    const text = question.trim()
    if (!text || asking) return
    setQuestion('')
    setAsking(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    try {
      const answer = await askReader(projectId, {
        message: text,
        scope,
        node_id: scope === 'node' ? nodeId : undefined,
      })
      setMessages((prev) => [...prev, { role: 'assistant', content: answer.answer, answer }])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `提问失败：${error instanceof Error ? error.message : '未知错误'}`,
        },
      ])
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center rounded-md border" role="group" aria-label="问答范围">
          <button
            type="button"
            onClick={() => setScope('project')}
            aria-pressed={scope === 'project'}
            className={`h-9 px-3 text-body-sm ${
              scope === 'project'
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            项目
          </button>
          <button
            type="button"
            onClick={() => setScope('node')}
            aria-pressed={scope === 'node'}
            className={`h-9 px-3 text-body-sm ${
              scope === 'node'
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            节点
          </button>
        </div>
        {scope === 'node' ? (
          <DirectoryTreeSelect
            nodes={tree.data ?? []}
            value={nodeId}
            loading={tree.isLoading}
            onSelect={setNodeId}
            ariaLabel="问答节点"
          />
        ) : null}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-md border bg-background p-4">
        {messages.length === 0 ? (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center text-center">
            <BookOpen className="size-6 text-muted-foreground" />
            <p className="mt-2 text-body font-[650]">基于已确认知识提问</p>
            <p className="mt-1 max-w-md text-body-sm leading-6 text-muted-foreground">
              只回答当前范围内已确认的正式知识，关键结论会附上 Entry 与 Source 引用。
            </p>
          </div>
        ) : (
          messages.map((message, index) =>
            message.role === 'user' ? (
              <div key={index} className="flex justify-end">
                <div className="max-w-[75%] rounded-lg bg-brand-soft px-3 py-2 text-body-sm leading-6">
                  {message.content}
                </div>
              </div>
            ) : (
              <div key={index} className="flex justify-start">
                <div className="max-w-[88%] rounded-lg border bg-background px-3 py-2">
                  <div className="mb-1 flex items-center gap-1.5 text-caption text-muted-foreground">
                    <Sparkles className="size-3.5" />
                    AI 阅读
                    {message.answer?.is_fallback ? (
                      <Badge variant="outline" className="bg-muted/60">
                        {message.answer.error ? '模型调用失败 · 已降级' : '已降级'}
                      </Badge>
                    ) : null}
                  </div>
                  <p className="whitespace-pre-wrap text-body-sm leading-6">{message.content}</p>
                  {message.answer ? (
                    <AssistantAnswer
                      answer={message.answer}
                      onPreview={(entryId) => setPreviewEntryId(entryId)}
                      onSave={() => {
                        const lastQuestion =
                          [...messages].reverse().find((item) => item.role === 'user')?.content ?? ''
                        setSaveTarget({ question: lastQuestion, answer: message.answer! })
                      }}
                    />
                  ) : null}
                </div>
              </div>
            ),
          )
        )}
        {asking ? (
          <div className="flex justify-start">
            <div className="rounded-lg border bg-background px-3 py-2 text-body-sm text-muted-foreground">
              正在阅读知识库…
            </div>
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex gap-2">
        <Input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') submit()
          }}
          placeholder={
            scope === 'node' && nodeId == null ? '请先选择问答节点' : '输入你的问题…'
          }
          disabled={asking || (scope === 'node' && nodeId == null)}
          aria-label="AI 阅读问题"
        />
        <Button onClick={submit} disabled={asking || !question.trim() || (scope === 'node' && nodeId == null)}>
          <Send />
          提问
        </Button>
      </div>

      <EntryPreviewDialog
        open={previewEntryId != null}
        entry={preview.data ?? null}
        onOpenChange={(open) => {
          if (!open) setPreviewEntryId(null)
        }}
      />

      <SaveAnswerDialog
        key={saveTarget ? `${saveTarget.question}-${saveTarget.answer.answer.length}` : 'closed'}
        open={saveTarget != null}
        question={saveTarget?.question ?? ''}
        answer={saveTarget?.answer ?? null}
        saving={save.isPending}
        onCancel={() => setSaveTarget(null)}
        onConfirm={(title, content) => {
          if (!saveTarget) return
          save.mutate({
            question: saveTarget.question,
            title,
            content,
            citations: saveTarget.answer.citations.map((citation) => ({
              entry_id: citation.entry_id,
              source_id: citation.source_id,
              quote: citation.quote,
            })),
            main_type: saveTarget.answer.main_type,
            info_nature: saveTarget.answer.info_nature,
          })
        }}
      />
    </div>
  )
}

function AssistantAnswer({
  answer,
  onPreview,
  onSave,
}: {
  answer: ReaderAnswerPayload
  onPreview: (entryId: number) => void
  onSave: () => void
}) {
  return (
    <div className="mt-2 space-y-2 border-t pt-2">
      {answer.insufficient ? (
        <div className="flex items-start gap-1.5 text-caption text-muted-foreground">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{answer.insufficient_note ?? '知识库中相关信息不足'}</span>
        </div>
      ) : null}
      {answer.citations.length > 0 ? (
        <details className="mt-1">
          <summary className="cursor-pointer text-caption text-muted-foreground">
            引用（{answer.citations.length}）
          </summary>
          <div className="mt-1 space-y-1">
            {answer.citations.map((citation) => (
              <button
                key={`${citation.entry_id}-${citation.source_id}`}
                type="button"
                onClick={() => onPreview(citation.entry_id)}
                className="block w-full rounded-md border p-2 text-left text-body-sm transition-colors hover:bg-muted/40"
              >
                <span className="font-medium">{citation.entry_title}</span>
                <span className="ml-2 text-caption text-muted-foreground">
                  {citation.source_title}
                </span>
                {citation.quote ? (
                  <span className="mt-0.5 block text-caption text-muted-foreground">
                    “{citation.quote}”
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        </details>
      ) : null}
      {answer.conflicts.length > 0 ? (
        <div className="space-y-1">
          <p className="text-caption text-muted-foreground">存在冲突观点</p>
          {answer.conflicts.map((conflict, index) => (
            <div key={index} className="rounded-md border border-destructive/40 bg-error-soft/60 p-2 text-body-sm">
              {conflict.summary}
            </div>
          ))}
        </div>
      ) : null}
      {answer.save_recommended ? (
        <Button size="sm" variant="outline" onClick={onSave}>
          <BookOpen />
          保存为知识
        </Button>
      ) : null}
    </div>
  )
}

function EntryPreviewDialog({
  open,
  entry,
  onOpenChange,
}: {
  open: boolean
  entry: EntryPayload | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{entry?.title ?? '加载中…'}</DialogTitle>
          <DialogDescription>{entry ? `${entry.node_name} · 已确认` : ''}</DialogDescription>
        </DialogHeader>
        {entry ? (
          <div className="space-y-2">
            <p className="whitespace-pre-wrap text-body-sm leading-6">{entry.content}</p>
            {entry.evidences.length > 0 ? (
              <div className="border-t pt-2 text-caption text-muted-foreground">
                来源：{entry.evidences.map((evidence) => evidence.source_title).join('、')}
              </div>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function SaveAnswerDialog({
  open,
  question,
  answer,
  saving,
  onCancel,
  onConfirm,
}: {
  open: boolean
  question: string
  answer: ReaderAnswerPayload | null
  saving: boolean
  onCancel: () => void
  onConfirm: (title: string, content: string) => void
}) {
  const [title, setTitle] = useState(() => question.slice(0, 100) || 'AI 阅读回答')
  const [content, setContent] = useState(() => answer?.answer ?? '')

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>保存为知识</DialogTitle>
          <DialogDescription>
            保存后将作为候选进入确认台，确认后才成为正式知识。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {answer?.main_type || answer?.info_nature ? (
            <div className="flex flex-wrap items-center gap-2 text-body-sm">
              <span className="text-muted-foreground">AI 推荐类型：</span>
              {answer?.main_type ? (
                <Badge variant="outline">
                  {MAIN_TYPE_LABELS[answer.main_type] ?? answer.main_type}
                </Badge>
              ) : null}
              {answer?.info_nature ? (
                <Badge variant="outline">
                  {INFO_NATURE_LABELS[answer.info_nature] ?? answer.info_nature}
                </Badge>
              ) : null}
            </div>
          ) : null}
          <label className="block">
            <span className="mb-1 block text-body-sm font-medium">标题</span>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={255}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-body-sm font-medium">内容</span>
            <Textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={8}
              maxLength={8000}
            />
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={saving}>
            取消
          </Button>
          <Button
            disabled={saving || !title.trim() || !content.trim()}
            onClick={() => onConfirm(title.trim(), content.trim())}
          >
            {saving ? '正在分析目录与重复…' : '保存为候选'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
