import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX, KeyRound, Loader2, PlugZap, Save, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useGroveMutation } from '@/hooks/useGroveMutation'
import {
  clearTextAISettings,
  clearVisionAISettings,
  fetchAISettings,
  saveTextAISettings,
  saveVisionAISettings,
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

  const canSave = apiKey.trim().length > 0

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
        </div>
        <KeyRound className="size-5 text-muted-foreground" />
      </div>

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
            placeholder={configured ? `已配置（尾号 ${keyTail}），留空则不修改` : '粘贴你的 API Key'}
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
          onClick={() =>
            onSave({
              api_key: apiKey.trim(),
              model: modelValue.trim() || null,
            })
          }
        >
          <Save />
          保存
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
    </section>
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
