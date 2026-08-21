import type { EntryPayload } from '@/lib/api'

/** Entry 详情悬浮小窗：hover 预览、点击固定；优先出现在条目左侧避免遮挡列表。 */
export function EntryPopover({
  entry,
  position,
  pinned,
  onClose,
}: {
  entry: EntryPayload | null
  position: { x: number; y: number }
  pinned: boolean
  onClose: () => void
}) {
  if (!entry) return null
  const left =
    position.x - 14 - 320 >= 0
      ? position.x - 14 - 320
      : Math.min(position.x + 14, window.innerWidth - 340)
  const top = Math.min(position.y, window.innerHeight - 300)
  return (
    <div
      className={`fixed z-50 max-h-[45vh] w-[320px] overflow-y-auto rounded-md border bg-card px-3 py-2.5 shadow-lg ${
        pinned ? '' : 'pointer-events-none'
      }`}
      style={{ left, top }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-body font-[650]">{entry.title}</h3>
          <p className="mt-0.5 truncate text-caption text-muted-foreground">
            {entry.node_name}
          </p>
        </div>
        {pinned ? (
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded px-1 text-caption text-muted-foreground hover:text-foreground"
          >
            关闭
          </button>
        ) : null}
      </div>
      <p className="mt-1 text-caption font-semibold text-brand">{entry.main_type}</p>
      <p className="mt-2 whitespace-pre-wrap text-body-sm leading-6">{entry.content}</p>
      {entry.applicable_condition ? (
        <p className="mt-2 text-body-sm text-muted-foreground">
          适用条件：{entry.applicable_condition}
        </p>
      ) : null}
      {entry.note ? (
        <p className="mt-1 text-body-sm text-muted-foreground">补充说明：{entry.note}</p>
      ) : null}
      {entry.evidences.length > 0 ? (
        <div className="mt-3 space-y-1 border-t pt-2">
          {entry.evidences.map((evidence) => (
            <p key={evidence.id} className="border-l-2 pl-2 text-caption text-muted-foreground">
              来源：{evidence.source_title}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  )
}
