import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
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
import {
  fetchEntryVersions,
  restoreEntryVersion,
  type EntryChangeType,
  type EntryPayload,
  type EntryVersionPayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const CHANGE_TYPE_LABELS: Record<EntryChangeType, string> = {
  created: '创建',
  edited: '编辑',
  ai_revision: 'AI 修订',
  restored: '恢复',
}

const MAIN_TYPE_LABELS: Record<string, string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 版本历史右抽屉：左侧版本列表、右侧快照，可恢复到所选版本。 */
export function EntryVersionHistoryDialog({
  open,
  entry,
  onOpenChange,
  onRestored,
}: {
  open: boolean
  entry: EntryPayload | null
  onOpenChange: (open: boolean) => void
  onRestored: (entry: EntryPayload) => void
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [confirmRestoreId, setConfirmRestoreId] = useState<number | null>(null)
  // 关闭面板时重置选择（React 渲染期派生状态模式）
  const [previousOpen, setPreviousOpen] = useState(false)
  if (open !== previousOpen) {
    setPreviousOpen(open)
    if (!open) {
      setSelectedId(null)
      setConfirmRestoreId(null)
    }
  }

  const versions = useQuery({
    queryKey: queryKeys.entryVersions(entry?.id ?? 0),
    queryFn: () => fetchEntryVersions(entry!.id),
    enabled: open && entry != null,
  })

  const selected = versions.data?.find((version) => version.id === selectedId) ?? null

  const restore = useMutation({
    mutationFn: (versionId: number) => restoreEntryVersion(entry!.id, versionId),
    onSuccess: (updated) => {
      toast.success('已恢复到所选版本')
      setConfirmRestoreId(null)
      onRestored(updated)
    },
    onError: (error: Error) => {
      toast.error(`恢复失败：${error.message}`)
    },
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-[min(960px,100vw)] max-w-none flex-col gap-0 p-0">
        <SheetHeader className="border-b px-6 py-4">
          <SheetTitle>版本历史</SheetTitle>
          <SheetDescription>
            {entry ? `${entry.title} · 只保留最近 10 条版本` : ''}
          </SheetDescription>
        </SheetHeader>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4 overflow-hidden px-6 py-4">
          <div className="min-h-0 overflow-y-auto border-r pr-3">
            {versions.isLoading ? (
              <p className="text-body-sm text-muted-foreground">加载中…</p>
            ) : (versions.data?.length ?? 0) === 0 ? (
              <p className="text-body-sm text-muted-foreground">暂无版本记录。</p>
            ) : (
              <div className="space-y-1.5">
                {versions.data?.map((version) => (
                  <button
                    key={version.id}
                    type="button"
                    onClick={() => {
                      setSelectedId(version.id)
                      setConfirmRestoreId(null)
                    }}
                    aria-pressed={selectedId === version.id}
                    className={`w-full rounded-md border px-3 py-2 text-left transition-colors ${
                      selectedId === version.id ? 'bg-brand-soft' : 'hover:bg-muted/40'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-body font-[650]">v{version.version_number}</span>
                      <Badge variant="outline" className="bg-muted/60 text-foreground">
                        {CHANGE_TYPE_LABELS[version.change_type]}
                      </Badge>
                    </div>
                    {version.change_summary ? (
                      <p className="mt-1 line-clamp-2 text-caption text-muted-foreground">
                        {version.change_summary}
                      </p>
                    ) : null}
                    <p className="mt-1 text-caption text-muted-foreground">
                      {formatDate(version.created_at)}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="min-h-0 overflow-y-auto">
            {selected ? (
              <VersionSnapshot version={selected} />
            ) : (
              <p className="text-body-sm text-muted-foreground">选择一个版本查看快照。</p>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t px-6 py-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          {selected ? (
            <Button
              disabled={restore.isPending}
              onClick={() => {
                if (confirmRestoreId !== selected.id) {
                  setConfirmRestoreId(selected.id)
                  return
                }
                restore.mutate(selected.id)
              }}
            >
              {confirmRestoreId === selected.id ? '确认恢复？' : '恢复此版本'}
            </Button>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function VersionSnapshot({ version }: { version: EntryVersionPayload }) {
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-body font-[650]">{version.title}</h3>
        <p className="mt-0.5 text-caption text-muted-foreground">
          {version.node_name} · {MAIN_TYPE_LABELS[version.main_type] ?? version.main_type}
          {version.info_nature ? ` · ${version.info_nature}` : ''}
        </p>
      </div>
      <p className="whitespace-pre-wrap text-body-sm leading-6">{version.content}</p>
      {version.applicable_condition ? (
        <p className="text-body-sm text-muted-foreground">
          适用条件：{version.applicable_condition}
        </p>
      ) : null}
      {version.note ? (
        <p className="text-body-sm text-muted-foreground">补充说明：{version.note}</p>
      ) : null}
    </div>
  )
}
