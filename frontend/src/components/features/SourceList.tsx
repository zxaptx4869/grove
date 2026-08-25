import { useState } from 'react'
import { Eye, FileText, ImageIcon, RotateCw, Trash2 } from 'lucide-react'

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
import type { SourcePayload, SourceStatus } from '@/lib/api'
import { SourceDetailDialog } from '@/components/features/SourceDetailDialog'

interface ProjectOption {
  id: number
  name: string
}

interface SourceListProps {
  sources: SourcePayload[]
  projects: ProjectOption[]
  onAssign: (sourceId: number, projectId: number | null) => void
  onTrigger: (sourceId: number) => void
  onDelete: (sourceId: number) => void
}

const STATUS_LABELS: Record<SourceStatus, string> = {
  waiting: '等待处理',
  processing: '处理中',
  done: '提取完成',
  failed: '失败',
}

function statusClass(status: SourceStatus) {
  if (status === 'done') return 'bg-confirmed-soft text-confirmed'
  if (status === 'failed') return 'bg-error-soft text-destructive'
  return 'bg-muted text-muted-foreground'
}

function attachmentSummary(source: SourcePayload) {
  const images = source.attachments.filter((item) => item.kind === 'image').length
  const texts = source.attachments.filter((item) => item.kind === 'text').length
  const parts: string[] = []
  if (images > 0) parts.push(`${images} 张图片`)
  if (texts > 0) parts.push('文字')
  return parts.length > 0 ? ` · ${parts.join('、')}` : ''
}

/** 提取完成后的候选确认副状态，用于说明锁定原因。 */
function reviewLabel(source: SourcePayload): string {
  const pending = source.pending_candidate_count
  const evidence = source.evidence_entry_count
  if (pending > 0 && evidence === 0) return `待确认 ${pending} 条`
  if (pending > 0 && evidence > 0) return '部分确认'
  if (evidence > 0) return `${evidence} 条正式知识`
  return '已处理'
}

/** Source 列表：展示类型、标题、说明、项目归属与操作。 */
export function SourceList({
  sources,
  projects,
  onAssign,
  onTrigger,
  onDelete,
}: SourceListProps) {
  const [detailSourceId, setDetailSourceId] = useState<number | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<SourcePayload | null>(null)

  if (sources.length === 0) {
    return <p className="px-1 py-6 text-center text-body-sm text-muted-foreground">还没有来源</p>
  }

  return (
    <>
      <ul className="divide-y border-t" aria-label="来源列表">
      {sources.map((source) => {
        const firstKind = source.attachments[0]?.kind ?? 'text'
        const showOperations = !source.project_locked && source.status !== 'processing'
        return (
          <li key={source.id} className="flex min-h-[64px] items-center gap-3 px-1 py-2.5">
            <span className="flex size-[34px] shrink-0 items-center justify-center rounded-md bg-muted">
              {firstKind === 'image' ? (
                <ImageIcon className="size-4 text-brand" />
              ) : (
                <FileText className="size-4 text-brand" />
              )}
            </span>
            <div className="min-w-0 flex-1">
              <button
                type="button"
                className="block w-full truncate text-left text-body font-medium hover:text-brand"
                onClick={() => setDetailSourceId(source.id)}
              >
                {source.title}
              </button>
              <p className="mt-[3px] truncate text-caption text-muted-foreground">
                {source.note || '无采集说明'}
                {attachmentSummary(source)}
              </p>
            </div>
            {showOperations ? (
              <select
                aria-label={`${source.title} 所属项目`}
                value={source.project_id != null ? String(source.project_id) : ''}
                onChange={(event) =>
                  onAssign(source.id, event.target.value ? Number(event.target.value) : null)
                }
                className="h-8 w-40 shrink-0 rounded-md border border-input bg-white px-2 text-caption"
              >
                <option value="">未归属</option>
                {projects.map((project) => (
                  <option key={project.id} value={String(project.id)}>
                    {project.name}
                  </option>
                ))}
              </select>
            ) : null}
            <Badge
              className={`min-h-[22px] shrink-0 rounded px-[7px] py-0.5 text-[11px] font-semibold ${statusClass(source.status)}`}
            >
              {STATUS_LABELS[source.status]}
            </Badge>
            {source.status === 'done' ? (
              <Badge variant="outline" className="shrink-0 bg-muted/60 text-muted-foreground">
                {reviewLabel(source)}
              </Badge>
            ) : null}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDetailSourceId(source.id)}
            >
              <Eye className="size-3.5" />
              查看
            </Button>
            {source.status === 'failed' ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onTrigger(source.id)}
              >
                <RotateCw className="size-3.5" />
                重试
              </Button>
            ) : null}
            {showOperations ? (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`删除 ${source.title}`}
                onClick={() => {
                  if (source.pending_candidate_count > 0) {
                    setDeleteTarget(source)
                  } else {
                    onDelete(source.id)
                  }
                }}
              >
                <Trash2 className="size-4" />
              </Button>
            ) : null}
          </li>
        )
        })}
      </ul>
      <SourceDetailDialog
        sourceId={detailSourceId}
        open={detailSourceId !== null}
        projects={projects}
        onOpenChange={(open) => {
          if (!open) setDetailSourceId(null)
        }}
      />
      <Dialog
        open={deleteTarget != null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除来源？</DialogTitle>
            <DialogDescription>
              {deleteTarget
                ? `「${deleteTarget.title}」有 ${deleteTarget.pending_candidate_count} 条待确认候选，删除将一并移除这些候选。确认删除？`
                : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (deleteTarget) onDelete(deleteTarget.id)
                setDeleteTarget(null)
              }}
            >
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
