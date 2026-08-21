import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { EntryPayload } from '@/lib/api'

/** Entry 详情弹窗：展示标题、目录、内容与来源证据。 */
export function EntryPreviewDialog({
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
