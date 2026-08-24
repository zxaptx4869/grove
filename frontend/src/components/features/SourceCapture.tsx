import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { ClipboardPaste, Images, Upload, X } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { createSource, triggerProcessing } from '@/lib/api'

interface ProjectOption {
  id: number
  name: string
}

interface SourceCaptureProps {
  projects: ProjectOption[]
  fixedProjectId?: number
  onCreated: () => void
}

/** 已选图片的缩略图条：本地预览 + 逐张移除。 */
function ImageThumbnails({
  files,
  onRemove,
}: {
  files: File[]
  onRemove: (index: number) => void
}) {
  const [urls, setUrls] = useState<string[]>([])
  const [urlFiles, setUrlFiles] = useState<readonly File[]>([])
  // files 变化时重建预览并释放旧 URL（渲染期派生状态模式）
  if (urlFiles !== files) {
    setUrlFiles(files)
    urls.forEach((url) => URL.revokeObjectURL(url))
    setUrls(files.map((file) => URL.createObjectURL(file)))
  }
  // 说明：不在这里做卸载时 revoke——StrictMode 开发环境会先卸载再重挂，
  // effect 清理会提前释放 blob 导致缩略图加载失败；blob 随页面卸载自动释放。

  if (files.length === 0) return null
  return (
    <div className="mt-3 grid grid-cols-5 gap-2">
      {files.map((file, index) => (
        <div
          key={`${file.name}-${index}`}
          className="group relative aspect-square overflow-hidden rounded-md border"
        >
          <img src={urls[index]} alt={file.name} className="size-full object-cover" />
          <span className="absolute inset-x-0 bottom-0 truncate bg-black/40 px-1 text-[10px] text-white">
            {file.name}
          </span>
          <button
            type="button"
            aria-label={`移除第 ${index + 1} 张图片`}
            onClick={() => onRemove(index)}
            className="absolute right-0.5 top-0.5 flex size-5 items-center justify-center rounded-full bg-black/60 text-white opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          >
            <X className="size-3" />
          </button>
        </div>
      ))}
    </div>
  )
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

  useEffect(() => {
    function onWindowPaste(event: ClipboardEvent) {
      const files = Array.from(event.clipboardData?.items ?? [])
        .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null)
      if (files.length === 0) return
      event.preventDefault()
      setFiles((prev) => {
        const combined = [...prev, ...files]
        if (combined.length > 5) {
          setError('一次最多 5 张图片，超出部分未加入')
        }
        return combined.slice(0, 5)
      })
      setMode('image')
    }
    window.addEventListener('paste', onWindowPaste)
    return () => window.removeEventListener('paste', onWindowPaste)
  }, [])

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

  async function handleSubmit() {
    if (files.length === 0 && text.trim() === '') {
      setError('请先选择图片或粘贴内容')
      return
    }

    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    if (text.trim()) form.append('text', text)
    if (projectId) form.append('project_id', projectId)
    if (note.trim()) form.append('note', note.trim())

    setPending(true)
    setError('')
    try {
      const created = await createSource(form)
      try {
        await triggerProcessing(created.id)
      } catch {
        toast.warning('来源已保存，但处理启动失败')
      }
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
              <>
                <p className="mt-2 text-caption text-muted-foreground">
                  已选择 {files.length} 张图片（最多 5 张）
                </p>
                <ImageThumbnails
                  files={files}
                  onRemove={(index) =>
                    setFiles((prev) => prev.filter((_, itemIndex) => itemIndex !== index))
                  }
                />
              </>
            ) : null}
          </div>
        ) : (
          <div>
            <Textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
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

        {mode === 'image' ? (
          <div className="space-y-1.5">
            <label htmlFor="capture-text" className="text-body-sm font-medium">
              附加文字内容（可选）
            </label>
            <Textarea
              id="capture-text"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="可粘贴一段与截图相关的文字，将作为材料正文一起处理…"
              rows={3}
            />
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
            {pending ? '采集中…' : '采集并处理'}
          </Button>
        </div>
      </div>
    </section>
  )
}
