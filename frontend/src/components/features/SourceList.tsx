import { useState } from 'react'
import { FileText, ImageIcon, RotateCw, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { SourcePayload, SourceStatus } from '@/lib/api'
import { SourceCandidatesDialog } from '@/components/features/SourceCandidatesDialog'

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
  done: '已完成',
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

/** Source 列表：展示类型、标题、说明、项目归属与操作。 */
export function SourceList({
  sources,
  projects,
  onAssign,
  onTrigger,
  onDelete,
}: SourceListProps) {
  const [candidateSourceId, setCandidateSourceId] = useState<number | null>(null)

  if (sources.length === 0) {
    return <p className="px-1 py-6 text-center text-body-sm text-muted-foreground">还没有来源</p>
  }

  return (
    <>
      <ul className="divide-y border-t" aria-label="来源列表">
      {sources.map((source) => {
        const firstKind = source.attachments[0]?.kind ?? 'text'
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
              <p className="truncate text-body font-medium">{source.title}</p>
              <p className="mt-[3px] truncate text-caption text-muted-foreground">
                {source.note || '无采集说明'}
                {attachmentSummary(source)}
              </p>
            </div>
            {source.status !== 'done' ? (
              <select
                aria-label={`${source.title} 所属项目`}
                value={source.project_id != null ? String(source.project_id) : ''}
                disabled={source.project_locked}
                title={
                  source.project_locked
                    ? '该来源已被正式知识引用，不能修改归属'
                    : undefined
                }
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
              <Button
                size="sm"
                variant="outline"
                onClick={() => setCandidateSourceId(source.id)}
              >
                <FileText className="size-3.5" />
                候选
              </Button>
            ) : null}
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
            {source.status !== 'done' ? (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={`删除 ${source.title}`}
                onClick={() => onDelete(source.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            ) : null}
          </li>
        )
        })}
      </ul>
      <SourceCandidatesDialog
        sourceId={candidateSourceId}
        open={candidateSourceId !== null}
        onOpenChange={(open) => {
          if (!open) setCandidateSourceId(null)
        }}
      />
    </>
  )
}
