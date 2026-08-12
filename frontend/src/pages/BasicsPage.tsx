import { useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { useDropzone } from 'react-dropzone'
import ReactMarkdown from 'react-markdown'
import { toast } from 'sonner'
import { z } from 'zod'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { ConversationPanel } from '@/components/features/ConversationPanel'
import { EmptyState } from '@/components/features/EmptyState'
import { TaskStatus } from '@/components/features/TaskStatus'

/** 表单示例：仅演示 react-hook-form + zod 基座，不含业务逻辑。 */
const demoFormSchema = z.object({
  note: z.string().min(2, '至少输入 2 个字符'),
})

type DemoFormValues = z.infer<typeof demoFormSchema>

const TOKEN_ROWS = [
  { token: 'ai-candidate', usage: 'AI 候选 / 建议 / 未确认内容' },
  { token: 'confirmed', usage: '正式记录（Entry）' },
  { token: 'risk', usage: '风险提示（置信度低、字段缺失）' },
  { token: 'success / warning / error', usage: '成功 / 警告 / 错误反馈' },
]

const MARKDOWN_SAMPLE = [
  '## react-markdown 示例',
  '',
  '**加粗**、`行内代码` 与列表：',
  '- 采集入口',
  '- 候选确认',
  '',
].join('\n')

/**
 * 组件基座示例页：集中展示第一批基础组件与设计令牌。
 * 仅做基座接入演示，不实现任何业务流程。
 */
export function BasicsPage() {
  const [droppedFiles, setDroppedFiles] = useState<readonly string[]>([])

  const form = useForm<DemoFormValues>({
    resolver: zodResolver(demoFormSchema),
    defaultValues: { note: '' },
  })

  const dropzone = useDropzone({
    // 仅示例：展示文件选择能力，不做上传
    accept: { 'text/*': [], 'image/*': [] },
    onDrop: (files) => setDroppedFiles(files.map((file) => file.name)),
  })

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-heading font-bold">组件基座示例</h1>
        <p className="text-body text-muted-foreground">
          第一批基础组件的接入演示（sonner / dropzone / form / table / command / markdown / dialog /
          badge / separator / textarea）。仅演示基座，不包含业务流程。
        </p>
      </section>

      <Separator />

      {/* 设计令牌与语义色 */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">设计令牌</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>语义令牌</TableHead>
              <TableHead>用途</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {TOKEN_ROWS.map((row) => (
              <TableRow key={row.token}>
                <TableCell className="font-medium">{row.token}</TableCell>
                <TableCell>{row.usage}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline" className="bg-ai-candidate-soft text-ai-candidate">
            AI 候选
          </Badge>
          <Badge variant="outline" className="bg-confirmed-soft text-confirmed">
            正式记录
          </Badge>
          <Badge variant="outline" className="bg-risk-soft text-risk">
            风险
          </Badge>
          <Badge variant="outline" className="bg-success-soft text-success">
            成功
          </Badge>
          <Badge variant="outline" className="bg-warning-soft text-warning">
            警告
          </Badge>
          <Badge variant="outline" className="bg-error-soft text-error">
            错误
          </Badge>
          <TaskStatus status="pending" />
          <TaskStatus status="running" />
          <TaskStatus status="failed" />
          <TaskStatus status="success" />
        </div>
      </section>

      <Separator />

      {/* sonner 提示 */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">Sonner 提示</h2>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => toast.success('成功提示')}>成功提示</Button>
          <Button variant="outline" onClick={() => toast.error('错误提示')}>
            错误提示
          </Button>
          <Button variant="outline" onClick={() => toast.info('信息提示')}>
            信息提示
          </Button>
        </div>
      </section>

      <Separator />

      {/* react-dropzone 采集入口示例 */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">DropZone（采集入口基座）</h2>
        <div
          {...dropzone.getRootProps()}
          className="cursor-pointer rounded-lg border border-dashed p-6 text-center text-body-sm text-muted-foreground"
        >
          <input {...dropzone.getInputProps()} />
          {dropzone.isDragActive ? '拖放中…' : '拖拽文件到此处，或点击选择（仅示例）'}
        </div>
        {droppedFiles.length > 0 ? (
          <ul className="list-inside list-disc space-y-1 text-body-sm">
            {droppedFiles.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <Separator />

      {/* react-hook-form + zod */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">Form（react-hook-form + zod）</h2>
        <Form {...form}>
          <form
            className="max-w-sm space-y-4"
            onSubmit={form.handleSubmit((values) => toast.success(`示例已提交：${values.note}`))}
          >
            <FormField
              control={form.control}
              name="note"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>备注</FormLabel>
                  <FormControl>
                    <Textarea placeholder="输入至少 2 个字符…" {...field} />
                  </FormControl>
                  <FormDescription>基座示例表单，不包含业务字段。</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit">提交示例</Button>
          </form>
        </Form>
      </section>

      <Separator />

      {/* cmdk 命令面板 */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">Command（cmdk）</h2>
        <Dialog>
          <DialogTrigger asChild>
            <Button variant="outline">打开命令面板</Button>
          </DialogTrigger>
          <DialogContent className="p-0">
            <DialogHeader className="sr-only">
              <DialogTitle>命令面板</DialogTitle>
              <DialogDescription>选择示例页面。</DialogDescription>
            </DialogHeader>
            <Command>
              <CommandInput placeholder="搜索示例…" />
              <CommandList>
                <CommandEmpty>无匹配项</CommandEmpty>
                <CommandGroup heading="页面">
                  <CommandItem onSelect={() => toast.info('选择了「首页」')}>首页</CommandItem>
                  <CommandItem onSelect={() => toast.info('选择了「健康检查」')}>
                    健康检查
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </DialogContent>
        </Dialog>
      </section>

      <Separator />

      {/* react-markdown */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">Markdown（react-markdown）</h2>
        <div className="rounded-lg border p-4 text-body-sm">
          <ReactMarkdown>{MARKDOWN_SAMPLE}</ReactMarkdown>
        </div>
      </section>

      <Separator />

      {/* 产品组件占位 */}
      <section className="space-y-3">
        <h2 className="text-title font-semibold">产品组件占位（features/）</h2>
        <EmptyState
          title="采集箱为空"
          description="拖拽截图、文字或链接到采集入口，开始整理知识。"
          action={<Button>浏览示例</Button>}
        />
        <ConversationPanel />
      </section>
    </div>
  )
}
