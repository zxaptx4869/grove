import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { fetchSimilarEntries, type EntryPayload } from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

const TYPE_LABELS: Record<string, string> = {
  knowledge: '知识',
  method: '方法',
  parameter: '参数',
  reminder: '提醒',
}

/** Entry 详情对话框：展示正式知识详情与同一项目内的相似知识推荐。 */
export function EntryDetailDialog({
  entry,
  open,
  onOpenChange,
  onSelectEntry,
}: {
  entry: EntryPayload | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectEntry?: (entry: EntryPayload) => void
}) {
  const similar = useQuery({
    queryKey: queryKeys.similarEntries(entry?.id ?? 0),
    queryFn: () => fetchSimilarEntries(entry!.id),
    enabled: open && entry != null,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        {entry ? (
          <>
            <DialogHeader>
              <DialogTitle>{entry.title}</DialogTitle>
              <DialogDescription>
                {entry.node_name} · {TYPE_LABELS[entry.main_type] ?? entry.main_type}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <p className="whitespace-pre-wrap text-body-sm leading-6">{entry.content}</p>
              {entry.applicable_condition ? (
                <p className="text-body-sm text-muted-foreground">
                  适用条件：{entry.applicable_condition}
                </p>
              ) : null}
              {entry.note ? (
                <p className="text-body-sm text-muted-foreground">补充说明：{entry.note}</p>
              ) : null}
            </div>

            <div>
              <h4 className="mb-2 text-body font-[650]">相关知识</h4>
              {similar.isLoading ? (
                <p className="text-body-sm text-muted-foreground">加载中…</p>
              ) : (similar.data?.length ?? 0) === 0 ? (
                <p className="text-body-sm text-muted-foreground">暂无相关正式知识。</p>
              ) : (
                <div className="space-y-2">
                  {similar.data?.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => onSelectEntry?.(item)}
                      className="block w-full rounded-md border p-2 text-left transition-colors hover:bg-muted/40"
                    >
                      <span className="block text-body-sm font-medium">{item.title}</span>
                      {item.reason ? (
                        <span className="mt-0.5 block text-caption text-muted-foreground">
                          {item.reason}
                        </span>
                      ) : null}
                      {item.is_fallback ? (
                        <Badge variant="outline" className="mt-1.5">
                          已降级
                        </Badge>
                      ) : null}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
