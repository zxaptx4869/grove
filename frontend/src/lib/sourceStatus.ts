/**
 * 来源处理状态口径（Web 唯一实现）。
 *
 * 与移动端 `mobile/src/sources/state.ts` 同口径：等待处理但没有处理任务的来源，
 * 处理 Worker 永远不会轮到它，必须识别成「处理未启动」并给出重试入口；判定只看
 * `has_processing_task`，不用「等待超过 N 秒」这类时间阈值猜测。
 */

import type { SourcePayload } from '@/lib/api'

type ProcessingState = Pick<SourcePayload, 'status' | 'has_processing_task'>

/** 等待处理但没有处理任务：处理未启动。 */
export function isProcessingNotStarted(source: ProcessingState): boolean {
  return source.status === 'waiting' && !source.has_processing_task
}

/** 状态徽标文案：未启动与失败可区分。 */
export function sourceStatusLabel(source: ProcessingState): string {
  if (isProcessingNotStarted(source)) return '处理未启动'
  if (source.status === 'waiting') return '等待处理'
  if (source.status === 'processing') return '处理中'
  if (source.status === 'done') return '提取完成'
  if (source.status === 'failed') return '失败'
  return source.status
}

/** 状态徽标配色：未启动用与移动端 risk 同色的警告色。 */
export function sourceStatusClass(source: ProcessingState): string {
  if (isProcessingNotStarted(source)) return 'bg-warning-soft text-warning'
  if (source.status === 'done') return 'bg-confirmed-soft text-confirmed'
  if (source.status === 'failed') return 'bg-error-soft text-destructive'
  return 'bg-muted text-muted-foreground'
}

/** 只有失败与「处理未启动」提供触发处理入口。 */
export function needsProcessingRetry(source: ProcessingState): boolean {
  return source.status === 'failed' || isProcessingNotStarted(source)
}

/** 两个重试入口文案区分：失败是「重试」，未启动是「重试处理」。 */
export function processingRetryLabel(source: ProcessingState): string {
  return isProcessingNotStarted(source) ? '重试处理' : '重试'
}
