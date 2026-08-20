import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LayoutGrid, List, Search, Sparkles, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { EmptyState } from '@/components/features/EmptyState'
import { EntryCard, EntryList } from '@/components/features/EntryViews'
import { Input } from '@/components/ui/input'
import {
  searchEntries,
  semanticSearchEntries,
  type SemanticEntryPayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

/** 全局搜索：跨项目查找已确认 Entry，点击跳转到对应项目知识空间。 */
export function SearchPage() {
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [viewMode, setViewMode] = useState<'card' | 'list'>('card')
  const [semanticMode, setSemanticMode] = useState(false)

  function submitSearch() {
    setSubmitted(input.trim())
  }

  function openEntry(projectId: number) {
    navigate(`/projects/${projectId}?view=directory`)
  }

  const results = useQuery({
    queryKey: semanticMode ? queryKeys.semanticSearch(submitted) : queryKeys.search(submitted),
    queryFn: async (): Promise<SemanticEntryPayload[]> => {
      if (semanticMode) {
        return semanticSearchEntries(submitted)
      }
      const items = await searchEntries(submitted)
      return items.map((item) => ({
        ...item,
        reason: '',
        is_fallback: false,
        provider: null,
        model: null,
        error: null,
      }))
    },
    enabled: submitted.length > 0,
  })

  const active = submitted.length > 0

  return (
    <section className="mx-auto w-full max-w-5xl px-6 pb-[30px] pt-[22px]">
      <header className="mb-5">
        <h1 className="text-[22px] font-[650] leading-[30px]">搜索</h1>
        <p className="mt-0.5 text-body text-muted-foreground">
          跨项目查找已确认的正式知识，不改变知识归属。
        </p>
      </header>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') submitSearch()
            }}
            placeholder="输入关键词搜索标题、内容、目录或来源…"
            className="h-10 pl-9 pr-16"
            aria-label="全局搜索"
            autoFocus
          />
          <button
            type="button"
            onClick={submitSearch}
            aria-label="执行搜索"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <Search className="size-4" />
          </button>
          {input ? (
            <button
              type="button"
              onClick={() => {
                setInput('')
                setSubmitted('')
              }}
              className="absolute right-9 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="清空搜索"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => setSemanticMode((value) => !value)}
          aria-pressed={semanticMode}
          className={`flex h-10 items-center gap-1.5 rounded-md border px-3 text-body-sm transition-colors ${
            semanticMode
              ? 'border-brand bg-brand-soft text-brand'
              : 'text-muted-foreground hover:text-foreground'
          }`}
        >
          <Sparkles className="size-4" />
          语义搜索
        </button>
        <div className="flex items-center rounded-md border" role="group" aria-label="视图切换">
          <button
            type="button"
            onClick={() => setViewMode('card')}
            aria-pressed={viewMode === 'card'}
            aria-label="卡片视图"
            className={`flex h-10 items-center gap-1.5 px-2.5 text-body-sm ${
              viewMode === 'card'
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <LayoutGrid className="size-4" />
            卡片
          </button>
          <button
            type="button"
            onClick={() => setViewMode('list')}
            aria-pressed={viewMode === 'list'}
            aria-label="列表视图"
            className={`flex h-10 items-center gap-1.5 px-2.5 text-body-sm ${
              viewMode === 'list'
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <List className="size-4" />
            列表
          </button>
        </div>
      </div>

      {!active ? (
        <EmptyState
          title="输入关键词开始搜索"
          description="搜索范围覆盖标题、核心内容、目录与来源摘要，可跨项目查找正式知识。"
        />
      ) : results.isLoading ? (
        <div className="py-16 text-center text-body-sm text-muted-foreground">正在搜索…</div>
      ) : (results.data?.length ?? 0) === 0 ? (
        <EmptyState title="没有匹配的正式知识" description="换个关键词试试。" />
      ) : (
        <div>
          <p className="mb-3 text-caption text-muted-foreground">
            共 {results.data?.length ?? 0} 条结果
            {semanticMode ? ' · 语义搜索' : ''}
            {semanticMode && results.data?.some((item) => item.is_fallback) ? ' · 已降级' : ''}
          </p>
          {viewMode === 'card' ? (
            <div className="space-y-3">
              {results.data?.map((entry) => (
                <EntryCard
                  key={entry.id}
                  entry={entry}
                  showProject
                  highlightQuery={submitted}
                  reason={entry.reason || undefined}
                  isFallback={entry.is_fallback}
                  error={entry.error || undefined}
                  onSelect={(selected) => openEntry(selected.project_id)}
                />
              ))}
            </div>
          ) : (
            <EntryList
              entries={results.data ?? []}
              showProject
              highlightQuery={submitted}
              onSelect={(selected) => openEntry(selected.project_id)}
            />
          )}
        </div>
      )}
    </section>
  )
}
