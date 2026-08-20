import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { fetchSimilarEntries, type EntryPayload } from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

/** 右侧抽屉：展示某条正式知识在同一项目内的相似知识推荐。 */
export function SimilarEntriesDrawer({
  entry,
  open,
  onOpenChange,
}: {
  entry: EntryPayload | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const similar = useQuery({
    queryKey: queryKeys.similarEntries(entry?.id ?? 0),
    queryFn: () => fetchSimilarEntries(entry!.id),
    enabled: open && entry != null,
  })

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>相关知识</SheetTitle>
          <SheetDescription>{entry?.title ?? ''}</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {similar.isLoading ? (
            <p className="text-body-sm text-muted-foreground">加载中…</p>
          ) : (similar.data?.length ?? 0) === 0 ? (
            <p className="text-body-sm text-muted-foreground">暂无相关正式知识。</p>
          ) : (
            <div className="space-y-2">
              {similar.data?.map((item) => (
                <div key={item.id} className="rounded-md border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-body-sm font-[650]">{item.title}</span>
                    {item.is_fallback ? (
                      <Badge variant="outline" className="shrink-0">
                        {item.error ? '模型调用失败 · 已降级' : '已降级'}
                      </Badge>
                    ) : null}
                  </div>
                  {item.reason ? (
                    <p className="mt-1 text-caption text-muted-foreground">{item.reason}</p>
                  ) : null}
                  <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-body-sm leading-6 text-muted-foreground">
                    {item.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
