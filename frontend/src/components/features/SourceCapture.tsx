import { useRef, useState, type ChangeEvent, type ClipboardEvent } from 'react'
import { ClipboardPaste, Images, Upload } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { createSource } from '@/lib/api'

interface ProjectOption {
  id: number
  name: string
}

interface SourceCaptureProps {
  projects: ProjectOption[]
  fixedProjectId?: number
  onCreated: () => void
}

/** 采集框：图片批量上传或粘贴内容，可选项目与说明。 */
export function SourceCapture({ projects, fixedProjectId, onCreated }: SourceCaptureProps) {
  const [mode, setMode] = useState<'image' | 'paste'>('image')
  const [files, setFiles] = useState<File[]>([])
  const [text, setText] = useState('')
  const [projectId, setProjectId] = useState(
    fixedProjectId != null ? String(fixedProjectId) : '',
  )
  const [note, setNote] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  function reset() {
    setFiles([])
    setText('')
    setNote('')
    setError('')
  }

  function onPickFiles(event: ChangeEvent<HTMLInputElement>) {
    const picked = Array.from(event.target.files ?? [])
    if (picked.length > 5) {
      setError('一次最多上传 5 张图片')
      return
    }
    setFiles(picked)
    setError('')
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const images = Array.from(event.clipboardData?.files ?? []).filter((file) =>
      file.type.startsWith('image/'),
    )
    if (images.length === 0) return
    event.preventDefault()
    setFiles((prev) => [...prev, ...images].slice(0, 5))
    setText('')
  }

  async function handleSubmit() {
    if (files.length === 0 && text.trim() === '') {
      setError('请先选择图片或粘贴内容')
      return
    }

    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    if (files.length === 0 && text.trim()) form.append('text', text)
    if (projectId) form.append('project_id', projectId)
    if (note.trim()) form.append('note', note.trim())

    setPending(true)
    setError('')
    try {
      await createSource(form)
      reset()
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : '采集失败，请重试')
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="rounded-lg border bg-card">
      <div className="flex border-b">
        <button
          type="button"
          onClick={() => setMode('image')}
          className={`flex h-[42px] flex-1 items-center justify-center gap-2 text-body-sm ${mode === 'image' ? 'border-b-2 border-brand font-medium text-brand' : 'text-muted-foreground hover:text-foreground'}`}
        >
          <Images className="size-4" />
          图片 / 截图
        </button>
        <button
          type="button"
          onClick={() => setMode('paste')}
          className={`flex h-[42px] flex-1 items-center justify-center gap-2 text-body-sm ${mode === 'paste' ? 'border-b-2 border-brand font-medium text-brand' : 'text-muted-foreground hover:text-foreground'}`}
        >
          <ClipboardPaste className="size-4" />
          粘贴内容
        </button>
      </div>

      <div className="space-y-4 p-5">
        {mode === 'image' ? (
          <div className="flex min-h-[116px] flex-col items-center justify-center rounded-md border border-dashed px-4 py-5 text-center">
            <Upload className="size-5 text-muted-foreground" />
            <p className="mt-2 text-body-sm font-medium">批量放入截图</p>
            <p className="mt-1 text-caption text-muted-foreground">
              可选择或直接粘贴多张图片，一次最多 5 张。
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={onPickFiles}
            />
            <Button
              type="button"
              variant="outline"
              className="mt-3"
              onClick={() => fileInputRef.current?.click()}
            >
              选择图片
            </Button>
            {files.length > 0 ? (
              <p className="mt-2 text-caption text-muted-foreground">
                已选择 {files.length} 张图片
              </p>
            ) : null}
          </div>
        ) : (
          <div>
            <Textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              onPaste={onPaste}
              aria-label="粘贴图片或文字"
              placeholder="在这里粘贴图片或文字…"
              rows={5}
            />
            <p className="mt-1.5 text-caption text-muted-foreground">
              检测到图片时会按图片处理，纯文字直接保存为一条来源。
            </p>
          </div>
        )}

        {fixedProjectId == null ? (
          <div className="space-y-1.5">
            <label htmlFor="capture-project" className="text-body-sm font-medium">
              所属项目（可选）
            </label>
            <select
              id="capture-project"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              className="flex h-9 w-full rounded-md border border-input bg-white px-3 py-1 text-sm"
            >
              <option value="">暂不归属项目</option>
              {projects.map((project) => (
                <option key={project.id} value={String(project.id)}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <div className="space-y-1.5">
          <label htmlFor="capture-note" className="text-body-sm font-medium">
            补充说明（可选）
          </label>
          <Input
            id="capture-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="例如：重点看看烘干程序是不是默认开启"
          />
        </div>

        {error ? (
          <div role="alert" className="rounded-md bg-error-soft px-3 py-2 text-body-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="flex justify-end">
          <Button onClick={handleSubmit} disabled={pending}>
            {pending ? '采集中…' : '采集'}
          </Button>
        </div>
      </div>
    </section>
  )
}
