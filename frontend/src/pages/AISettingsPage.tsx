import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CircleCheck,
  CircleX,
  KeyRound,
  Loader2,
  Pencil,
  PlugZap,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

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
import { Input } from '@/components/ui/input'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import { useEmbeddingIndexStatus } from '@/hooks/useEmbeddingIndexStatus'
import {
  clearTextAISettings,
  clearVisionAISettings,
  clearEmbeddingAISettings,
  fetchAISettings,
  rebuildEmbedding,
  saveEmbeddingAISettings,
  saveTextAISettings,
  saveVisionAISettings,
  testEmbeddingAISettings,
  testTextAISettings,
  testVisionAISettings,
  type AIProviderSettingsPayload,
} from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

function availableBadge(configured: boolean, available: boolean) {
  if (!configured) return <Badge className="bg-muted text-muted-foreground">未配置</Badge>
  if (available)
    return <Badge className="bg-confirmed-soft text-confirmed">连接正常</Badge>
  return <Badge className="bg-error-soft text-destructive">未测试或连接失败</Badge>
}

function embeddingBadge(configured: boolean, available: boolean, tested: boolean) {
  if (!configured) return <Badge className="bg-muted text-muted-foreground">未配置</Badge>
  if (available) return <Badge className="bg-confirmed-soft text-confirmed">连接正常</Badge>
  if (tested) return <Badge className="bg-error-soft text-destructive">连接失败</Badge>
  return <Badge className="bg-warning-soft text-warning">未测试</Badge>
}

function ProviderForm({
  kind,
  data,
  onSave,
  onTest,
  onClear,
}: {
  kind: 'text' | 'vision'
  data: AIProviderSettingsPayload
  onSave: (payload: { api_key: string; model: string | null }) => void
  onTest: () => void
  onClear: () => void
}) {
  const isText = kind === 'text'
  const provider = isText ? data.text_provider : data.vision_provider
  const model = isText ? data.text_model : data.vision_model
  const configured = isText ? data.text_configured : data.vision_configured
  const available = isText ? data.text_available : data.vision_available
  const keyTail = isText ? data.text_key_tail : data.vision_key_tail

  const [apiKey, setApiKey] = useState('')
  const [modelValue, setModelValue] = useState(model)
  const [editing, setEditing] = useState(false)

  const canSave = apiKey.trim().length > 0

  function cancelEdit() {
    setEditing(false)
    setApiKey('')
    setModelValue(model)
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[16px] font-[650] leading-6">{isText ? '文本模型' : '视觉模型'}</h2>
            {availableBadge(configured, available)}
          </div>
          <p className="mt-1 text-body-sm text-muted-foreground">
            {provider} · {model}
          </p>
          {configured ? (
            <p className="mt-1 text-caption text-confirmed">
              已配置 · 尾号 ••••{keyTail}
            </p>
          ) : null}
        </div>
        <KeyRound className="size-5 text-muted-foreground" />
      </div>

      {editing ? (
        <>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <label htmlFor={`${kind}-api-key`} className="text-body-sm font-medium">
                API Key
              </label>
              <Input
                id={`${kind}-api-key`}
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={
                  configured ? '留空则不修改，粘贴新 key 可更换' : '粘贴你的 API Key'
                }
                autoComplete="off"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor={`${kind}-model`} className="text-body-sm font-medium">
                模型名（可选）
              </label>
              <Input
                id={`${kind}-model`}
                value={modelValue}
                onChange={(event) => setModelValue(event.target.value)}
                placeholder={model}
              />
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={!canSave}
              onClick={() => {
                onSave({
                  api_key: apiKey.trim(),
                  model: modelValue.trim() || null,
                })
                setEditing(false)
              }}
            >
              <Save />
              保存
            </Button>
            <Button size="sm" variant="ghost" onClick={cancelEdit}>
              <X />
              取消
            </Button>
          </div>
        </>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Pencil />
            编辑
          </Button>
          <Button size="sm" variant="outline" onClick={onTest}>
            <PlugZap />
            测试连接
          </Button>
          {configured ? (
            <Button size="sm" variant="ghost" onClick={onClear}>
              <Trash2 />
              清除
            </Button>
          ) : null}
        </div>
      )}
    </section>
  )
}

function EmbeddingForm({
  data,
  onSave,
  onTest,
  onClear,
}: {
  data: AIProviderSettingsPayload
  onSave: (payload: { model: string | null }) => void
  onTest: () => void
  onClear: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [modelValue, setModelValue] = useState(data.embedding_model)
  const [pendingModel, setPendingModel] = useState<string | null>(null)
  const status = useEmbeddingIndexStatus()
  const total =
    status.data && typeof status.data.total === 'number' ? status.data.total : null

  function requestSave() {
    const next = modelValue.trim() || data.embedding_model
    if (next !== data.embedding_model) {
      setPendingModel(next)
      return
    }
    onSave({ model: next })
    setEditing(false)
  }

  function confirmSave() {
    if (pendingModel) {
      onSave({ model: pendingModel })
    }
    setPendingModel(null)
    setEditing(false)
  }

  function cancelEdit() {
    setEditing(false)
    setModelValue(data.embedding_model)
  }

  return (
    <section className="rounded-lg border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[16px] font-[650] leading-6">语义模型（Embedding）</h2>
            {embeddingBadge(
              data.embedding_configured,
              data.embedding_available,
              data.embedding_tested,
            )}
          </div>
          <p className="mt-1 text-body-sm text-muted-foreground">
            {data.embedding_provider} · {data.embedding_model}
          </p>
          {data.embedding_configured ? (
            <p className="mt-1 text-caption text-confirmed">
              已配置 · 复用视觉模型密钥（尾号 ••••{data.embedding_key_tail}）
            </p>
          ) : (
            <p className="mt-1 text-caption text-muted-foreground">
              配置视觉模型密钥后即可复用，无需单独填写 API Key
            </p>
          )}
        </div>
        <Sparkles className="size-5 text-muted-foreground" />
      </div>

      {editing ? (
        <>
          <div className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <label htmlFor="embedding-model" className="text-body-sm font-medium">
                模型名（可选）
              </label>
              <Input
                id="embedding-model"
                value={modelValue}
                onChange={(event) => setModelValue(event.target.value)}
                placeholder={data.embedding_model}
              />
              <p className="text-caption text-muted-foreground">
                密钥复用视觉模型（豆包方舟）同一把 API Key；停用后语义功能退回确定性检索。
              </p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={requestSave}>
              <Save />
              保存
            </Button>
            <Button size="sm" variant="ghost" onClick={cancelEdit}>
              <X />
              取消
            </Button>
          </div>
        </>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            <Pencil />
            编辑
          </Button>
          <Button size="sm" variant="outline" onClick={onTest}>
            <PlugZap />
            测试连接
          </Button>
          {data.embedding_configured ? (
            <Button size="sm" variant="ghost" onClick={onClear}>
              <Trash2 />
              停用
            </Button>
          ) : null}
        </div>
      )}
      <EmbeddingIndexStatusBlock />
      <Dialog
        open={pendingModel !== null}
        onOpenChange={(open) => !open && setPendingModel(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>切换语义模型将全量重建</DialogTitle>
            <DialogDescription>
              不同模型生成的向量无法混用。保存后系统会删除现有向量，并按新模型重新编码
              {total !== null
                ? `当前工作区全部 ${total} 条知识`
                : '当前工作区全部知识'}
              ，期间语义搜索与相关知识会短暂降级，关键词搜索不受影响。确定继续吗？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPendingModel(null)}>
              取消
            </Button>
            <Button onClick={confirmSave}>确认保存并重建</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function EmbeddingIndexStatusBlock() {
  const status = useEmbeddingIndexStatus()
  const retryFailed = useGroveMutation({
    mutationFn: () => rebuildEmbedding({ mode: 'failed' }),
    invalidates: [queryKeys.embeddingIndexStatus()],
    onSuccess: () => toast.success('已重新提交失败项的语义索引'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '重试失败，请稍后再试'),
  })
  const rebuildAll = useGroveMutation({
    mutationFn: () => rebuildEmbedding({ mode: 'all' }),
    invalidates: [queryKeys.embeddingIndexStatus()],
    onSuccess: () => toast.success('已发起全量重建'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '重建失败，请稍后再试'),
  })

  const data = status.data
  if (!data || typeof data.total !== 'number' || data.total === 0) return null
  const pendingCount = data.pending + data.missing
  const indexing = pendingCount > 0
  const progress = data.total > 0 ? Math.round((data.ready / data.total) * 100) : 0

  return (
    <div className="mt-4 space-y-2 rounded-md border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2 text-body-sm">
        <span className="inline-flex items-center gap-1.5">
          {indexing ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {indexing ? '正在索引…' : '语义索引'}
        </span>
        {!indexing ? <span>：已索引 {data.ready}/{data.total}</span> : null}
        {indexing ? (
          <span>
            ：已索引 {data.ready}/{data.total}（{progress}%）
          </span>
        ) : null}
        {pendingCount > 0 ? <span>· 待索引 {pendingCount}</span> : null}
        {data.failed > 0 ? <span className="text-destructive">· 失败 {data.failed}</span> : null}
      </div>
      {indexing ? (
        <div className="h-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-brand transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {data.failed > 0 ? (
          <Button
            size="sm"
            variant="outline"
            disabled={retryFailed.isPending}
            onClick={() => retryFailed.mutate()}
          >
            <RefreshCw />
            重试失败项
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          disabled={rebuildAll.isPending}
          onClick={() => rebuildAll.mutate()}
        >
          <RefreshCw />
          全部重建
        </Button>
      </div>
      {data.failed_items.length > 0 ? (
        <ul className="max-h-32 space-y-1 overflow-auto text-caption text-muted-foreground">
          {data.failed_items.map((item) => (
            <li key={item.entry_id}>
              「{item.title}」：{item.error}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

/** 模型设置页：用户自带密钥（BYOK），产品不提供模型。 */
export function AISettingsPage() {
  const settings = useQuery({
    queryKey: queryKeys.aiSettings,
    queryFn: fetchAISettings,
  })

  const saveText = useGroveMutation({
    mutationFn: saveTextAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('文本模型密钥已保存'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '保存失败，请重试'),
  })
  const saveVision = useGroveMutation({
    mutationFn: saveVisionAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('视觉模型密钥已保存'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '保存失败，请重试'),
  })
  const saveEmbedding = useGroveMutation({
    mutationFn: saveEmbeddingAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('语义模型配置已保存'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '保存失败，请重试'),
  })
  const clearText = useGroveMutation({
    mutationFn: clearTextAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('文本模型密钥已清除'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '清除失败，请重试'),
  })
  const clearVision = useGroveMutation({
    mutationFn: clearVisionAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('视觉模型密钥已清除'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '清除失败，请重试'),
  })
  const clearEmbedding = useGroveMutation({
    mutationFn: clearEmbeddingAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: () => toast.success('语义模型已停用'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '停用失败，请重试'),
  })
  const testText = useGroveMutation({
    mutationFn: testTextAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: (result) =>
      result.ok
        ? toast.success('文本模型连接正常')
        : toast.error(result.message || '文本模型连接失败'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '测试连接失败'),
  })
  const testVision = useGroveMutation({
    mutationFn: testVisionAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: (result) =>
      result.ok
        ? toast.success('视觉模型连接正常')
        : toast.error(result.message || '视觉模型连接失败'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '测试连接失败'),
  })
  const testEmbedding = useGroveMutation({
    mutationFn: testEmbeddingAISettings,
    invalidates: [queryKeys.aiSettings],
    onSuccess: (result) =>
      result.ok
        ? toast.success('语义模型连接正常')
        : toast.error(result.message || '语义模型连接失败'),
    onError: (error) =>
      toast.error(error instanceof Error ? error.message : '测试连接失败'),
  })

  return (
    <section className="w-full px-6 pb-[30px] pt-[22px]">
      <header className="mb-5">
        <h1 className="text-[22px] font-[650] leading-[30px]">模型设置</h1>
        <p className="mt-0.5 max-w-2xl text-body text-muted-foreground">
          Grove 不提供模型密钥，你可以配置自己的文本模型与视觉模型密钥。密钥只会存入系统钥匙串，界面不会回显完整内容。
        </p>
      </header>

      {settings.isLoading ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2" aria-label="模型设置加载中">
          <div className="h-64 animate-pulse rounded-lg bg-muted/40" />
          <div className="h-64 animate-pulse rounded-lg bg-muted/40" />
        </div>
      ) : settings.isError || !settings.data ? (
        <div className="rounded-lg border-l-2 border-destructive bg-error-soft px-4 py-3">
          <p className="text-body-sm">模型设置加载失败，请重试。</p>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => settings.refetch()}>
            <Loader2 className="size-3.5" />
            重试
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ProviderForm
            key={`text-${settings.data.text_configured}-${settings.data.text_model}`}
            kind="text"
            data={settings.data}
            onSave={(payload) => saveText.mutate(payload)}
            onTest={() => testText.mutate()}
            onClear={() => clearText.mutate()}
          />
          <ProviderForm
            key={`vision-${settings.data.vision_configured}-${settings.data.vision_model}`}
            kind="vision"
            data={settings.data}
            onSave={(payload) => saveVision.mutate(payload)}
            onTest={() => testVision.mutate()}
            onClear={() => clearVision.mutate()}
          />
          <EmbeddingForm
            key={`embedding-${settings.data.embedding_configured}-${settings.data.embedding_model}`}
            data={settings.data}
            onSave={(payload) => saveEmbedding.mutate(payload)}
            onTest={() => testEmbedding.mutate()}
            onClear={() => clearEmbedding.mutate()}
          />
        </div>
      )}

      <div className="mt-5 flex items-center gap-2 text-body-sm text-muted-foreground">
        <CircleCheck className="size-4 text-confirmed" />
        保存后可用「测试连接」验证；未配置时 Agent 会回退到离线演示逻辑。
        <CircleX className="ml-2 size-4 text-destructive" />
        密钥不明文入库。
      </div>
    </section>
  )
}
