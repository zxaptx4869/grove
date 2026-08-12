import { EmptyState } from '@/components/features/EmptyState'

/** 搜索占位：搜索与来源追溯在后续切片实现。 */
export function SearchPage() {
  return (
    <section className="space-y-6">
      <h1 className="text-heading font-bold">搜索</h1>
      <EmptyState
        title="搜索尚未上线"
        description="后续切片将支持按项目、目录节点过滤的全文搜索，并展示每条记录的来源追溯。"
      />
    </section>
  )
}
