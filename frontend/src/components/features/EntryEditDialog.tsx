import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'

import { DirectoryTreeSelect } from '@/components/features/DirectoryTreeSelect'
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
  updateEntry,
  type EntryPayload,
  type EntryUpdatePayload,
  type TreeNodePayload,
} from '@/lib/api'

const MAIN_TYPE_LABELS = [
  { value: 'knowledge', label: '知识' },
  { value: 'method', label: '方法' },
  { value: 'parameter', label: '参数' },
  { value: 'reminder', label: '提醒' },
] as const

interface EntryFormState {
  title: string
  content: string
  main_type: EntryPayload['main_type']
  info_nature: string
  applicable_condition: string
  note: string
  node_id: number | null
}

/** Entry 编辑面板：字段编辑 + 目录移动。 */
export function EntryEditDialog({
  open,
  entry,
  nodes,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  entry: EntryPayload | null
  nodes: TreeNodePayload[]
  onOpenChange: (open: boolean) => void
  onSaved: (entry: EntryPayload) => void
}) {
  // 打开面板或切换 Entry 时重置表单（React 渲染期派生状态模式）
  const [previous, setPrevious] = useState<{
    open: boolean
    entryId: number | null
  }>({ open: false, entryId: null })
  const current = { open, entryId: entry?.id ?? null }
  const [form, setForm] = useState<EntryFormState | null>(null)
  if (current.open !== previous.open || current.entryId !== previous.entryId) {
    setPrevious(current)
    setForm(
      open && entry
        ? {
            title: entry.title,
            content: entry.content,
            main_type: entry.main_type,
            info_nature: entry.info_nature ?? '',
            applicable_condition: entry.applicable_condition ?? '',
            note: entry.note ?? '',
            node_id: entry.node_id,
          }
        : null,
    )
  }

  const save = useMutation({
    mutationFn: () => {
      const current = form!
      return updateEntry(entry!.id, {
        title: current.title.trim(),
        content: current.content.trim(),
        main_type: current.main_type,
        info_nature: (current.info_nature.trim() || null) as EntryUpdatePayload['info_nature'],
        applicable_condition: current.applicable_condition.trim() || null,
        note: current.note.trim() || null,
        node_id: current.node_id,
      })
    },
    onSuccess: (updated) => {
      toast.success('Entry 已更新')
      onSaved(updated)
    },
    onError: (error: Error) => {
      toast.error(`保存失败：${error.message}`)
    },
  })

  const canSave = Boolean(form && form.title.trim() && form.content.trim() && form.node_id != null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>编辑 Entry</DialogTitle>
          <DialogDescription>{entry ? `${entry.node_name} · 已确认` : ''}</DialogDescription>
        </DialogHeader>
        {form && entry ? (
          <div className="space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="entry-edit-title" className="text-body-sm font-medium">
                标题
              </label>
              <Input
                id="entry-edit-title"
                value={form.title}
                onChange={(event) => setForm({ ...form, title: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="entry-edit-content" className="text-body-sm font-medium">
                核心内容
              </label>
              <Textarea
                id="entry-edit-content"
                value={form.content}
                onChange={(event) => setForm({ ...form, content: event.target.value })}
                rows={6}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="entry-edit-type" className="text-body-sm font-medium">
                  主类型
                </label>
                <select
                  id="entry-edit-type"
                  className="h-9 w-full rounded-md border px-2 text-body-sm"
                  value={form.main_type}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      main_type: event.target.value as EntryPayload['main_type'],
                    })
                  }
                >
                  {MAIN_TYPE_LABELS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="entry-edit-nature" className="text-body-sm font-medium">
                  信息性质
                </label>
                <Input
                  id="entry-edit-nature"
                  value={form.info_nature}
                  onChange={(event) => setForm({ ...form, info_nature: event.target.value })}
                  placeholder="事实 / 经验 / 建议 / 推测 / 其他"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="entry-edit-condition" className="text-body-sm font-medium">
                适用条件
              </label>
              <Textarea
                id="entry-edit-condition"
                value={form.applicable_condition}
                onChange={(event) =>
                  setForm({ ...form, applicable_condition: event.target.value })
                }
                rows={2}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="entry-edit-note" className="text-body-sm font-medium">
                补充说明
              </label>
              <Textarea
                id="entry-edit-note"
                value={form.note}
                onChange={(event) => setForm({ ...form, note: event.target.value })}
                rows={2}
              />
            </div>
            <div className="space-y-1.5">
              <span className="text-body-sm font-medium">主目录节点</span>
              <DirectoryTreeSelect
                nodes={nodes}
                value={form.node_id}
                placeholder={nodes.length > 0 ? '选择目录节点' : '项目还没有目录节点'}
                ariaLabel="主目录节点"
                onSelect={(nodeId) => setForm({ ...form, node_id: nodeId })}
              />
            </div>
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={save.isPending}>
            取消
          </Button>
          <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
