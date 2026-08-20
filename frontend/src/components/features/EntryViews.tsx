import { Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { EntryPayload } from '@/lib/api'

export type EntryViewPayload = EntryPayload & { project_name?: string }

const ENTRY_TYPE_LABELS: Record<EntryPayload['main_type'], string> = {
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

function distinctSources(entry: EntryViewPayload) {
  const seen = new Set<number>()
  return entry.evidences.filter((evidence) => {
    if (seen.has(evidence.source_id)) return false
    seen.add(evidence.source_id)
    return true
  })
}

function sourceSummary(entry: EntryViewPayload): string {
  const sources = distinctSources(entry)
  if (sources.length === 0) return '—'
  const first = sources[0].source_title || '未命名来源'
  return sources.length === 1 ? first : `${first} · 等 ${sources.length} 条`
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 搜索结果高亮：只染命中文字，不加背景不加粗。 */
export function HighlightText({ text, query }: { text: string; query?: string }) {
  if (!query) return <>{text}</>
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, 'gi'))
  const lowered = query.toLowerCase()
  return (
    <>
      {parts.map((part, index) =>
        part !== '' && part.toLowerCase() === lowered ? (
          <span key={index} className="text-[#b45309]">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </>
  )
}

/** 卡片视图：突出内容与来源，适合阅读与回顾。 */
export function EntryCard({
  entry,
  showProject = false,
  highlightQuery,
  reason,
  isFallback = false,
  onSelect,
  onShowSimilar,
}: {
  entry: EntryViewPayload
  showProject?: boolean
  highlightQuery?: string
  reason?: string
  isFallback?: boolean
  onSelect?: (entry: EntryViewPayload) => void
  onShowSimilar?: (entry: EntryViewPayload) => void
}) {
  const clickable = Boolean(onSelect)
  return (
    <article
      className={`rounded-md border p-3 ${
        clickable ? 'cursor-pointer transition-colors hover:bg-muted/40' : ''
      }`}
      onClick={clickable ? () => onSelect?.(entry) : undefined}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onSelect?.(entry)
              }
            }
          : undefined
      }
    >
      {showProject && entry.project_name ? (
        <p className="mb-2 text-caption text-muted-foreground">{entry.project_name}</p>
      ) : null}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="bg-brand-soft text-brand">
              {ENTRY_TYPE_LABELS[entry.main_type]}
            </Badge>
            {entry.info_nature ? (
              <Badge variant="outline" className="bg-muted/60 text-foreground">
                {INFO_NATURE_LABELS[entry.info_nature] ?? entry.info_nature}
              </Badge>
            ) : null}
          </div>
          <h3 className="mt-1 text-body font-[650]">
            <HighlightText text={entry.title} query={highlightQuery} />
          </h3>
        </div>
        <Badge className="shrink-0 bg-confirmed-soft text-confirmed">已确认</Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-body-sm leading-6">
        <HighlightText text={entry.content} query={highlightQuery} />
      </p>
      {entry.applicable_condition ? (
        <p className="mt-2 text-body-sm text-muted-foreground">
          适用条件：{entry.applicable_condition}
        </p>
      ) : null}
      {entry.note ? (
        <p className="mt-2 text-body-sm text-muted-foreground">补充说明：{entry.note}</p>
      ) : null}
      {reason ? (
        <p className="mt-2 text-caption text-muted-foreground">相关理由：{reason}</p>
      ) : null}
      {isFallback ? (
        <Badge variant="outline" className="mt-2 bg-muted/60">
          已降级
        </Badge>
      ) : null}
      {onShowSimilar ? (
        <div className="mt-3 border-t pt-2">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onShowSimilar(entry)
            }}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-body-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <Sparkles className="size-4" />
            相关知识
          </button>
        </div>
      ) : null}
      {entry.evidences.length > 0 ? (
        <details className="mt-3 border-t pt-2 text-caption text-muted-foreground">
          <summary className="cursor-pointer">来源证据 {entry.evidences.length} 条</summary>
          <div className="mt-2 space-y-1">
            {entry.evidences.map((evidence) => (
              <blockquote key={evidence.id} className="border-l-2 px-2">
                <span className="font-medium text-foreground">{evidence.source_title}</span>
                <span className="mt-0.5 block">{evidence.quote || '（无引用片段）'}</span>
              </blockquote>
            ))}
          </div>
        </details>
      ) : null}
    </article>
  )
}

/** 列表视图：突出标题、目录、类型、来源与更新时间，适合扫描。 */
export function EntryList({
  entries,
  showProject = false,
  highlightQuery,
  onSelect,
}: {
  entries: EntryViewPayload[]
  showProject?: boolean
  highlightQuery?: string
  onSelect?: (entry: EntryViewPayload) => void
}) {
  return (
    <Table className="table-fixed">
      <TableHeader>
        <TableRow>
          {showProject ? <TableHead className="w-[16%]">项目</TableHead> : null}
          <TableHead className={showProject ? 'w-[26%]' : 'w-[32%]'}>标题</TableHead>
          <TableHead className={showProject ? 'w-[14%]' : 'w-[18%]'}>目录</TableHead>
          <TableHead className={showProject ? 'w-[10%]' : 'w-[12%]'}>类型</TableHead>
          <TableHead className={showProject ? 'w-[22%]' : 'w-[26%]'}>来源</TableHead>
          <TableHead className="w-[12%]">更新时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => (
          <TableRow
            key={entry.id}
            onClick={onSelect ? () => onSelect(entry) : undefined}
            className={onSelect ? 'cursor-pointer' : undefined}
          >
            {showProject ? (
              <TableCell>
                <span className="block truncate text-muted-foreground">
                  {entry.project_name ?? '—'}
                </span>
              </TableCell>
            ) : null}
            <TableCell className="text-body font-medium">
              <span className="block truncate">
                <HighlightText text={entry.title} query={highlightQuery} />
              </span>
            </TableCell>
            <TableCell>
              <span className="block truncate text-muted-foreground">{entry.node_name}</span>
            </TableCell>
            <TableCell>
              <Badge variant="outline" className="bg-brand-soft text-brand">
                {ENTRY_TYPE_LABELS[entry.main_type]}
              </Badge>
            </TableCell>
            <TableCell>
              <span className="block truncate text-muted-foreground">{sourceSummary(entry)}</span>
            </TableCell>
            <TableCell className="text-caption text-muted-foreground">
              {formatDate(entry.updated_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
