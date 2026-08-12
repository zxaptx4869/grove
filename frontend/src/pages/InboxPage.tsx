import { EmptyState } from '@/components/features/EmptyState'

/** 采集箱占位：采集功能在下一个业务切片实现。 */
export function InboxPage() {
  return (
    <section className="space-y-6">
      <h1 className="text-heading font-bold">采集箱</h1>
      <EmptyState
        title="采集功能尚未上线"
        description="下一个切片将支持拖拽、粘贴、上传与链接正文采集。这里会展示待处理素材与任务状态。"
      />
    </section>
  )
}
