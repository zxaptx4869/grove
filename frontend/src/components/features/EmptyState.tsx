import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  description?: string
  action?: ReactNode
}

/**
 * 空状态占位：数据驱动（纯 props），用于列表/页面为空时的引导。
 * 不承载任何业务逻辑。
 */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center">
      <p className="text-title font-medium">{title}</p>
      {description ? (
        <p className="max-w-sm text-body-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  )
}
