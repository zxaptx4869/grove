import { Badge } from '@/components/ui/badge'

export type TaskStatusValue = 'pending' | 'running' | 'failed' | 'success'

const STATUS_CONFIG: Record<TaskStatusValue, { label: string; className: string }> = {
  pending: { label: '待处理', className: 'bg-muted text-muted-foreground' },
  running: { label: '处理中', className: 'bg-ai-candidate-soft text-ai-candidate' },
  failed: { label: '失败', className: 'bg-error-soft text-error' },
  success: { label: '成功', className: 'bg-success-soft text-success' },
}

export interface TaskStatusProps {
  status: TaskStatusValue
}

/**
 * 任务状态徽标：数据驱动（status 枚举 → 徽标样式）。
 * 业务状态机由后续 change 定义，本组件只做展示映射。
 */
export function TaskStatus({ status }: TaskStatusProps) {
  const config = STATUS_CONFIG[status]
  return (
    <Badge variant="outline" className={config.className}>
      {config.label}
    </Badge>
  )
}
