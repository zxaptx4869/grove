import { useQueryClient, type QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useGroveMutation } from '@/hooks/useGroveMutation'
import { ApiError, triggerProcessing } from '@/lib/api'
import { queryKeys } from '@/lib/queryKeys'

/**
 * 触发来源处理：失败重试与「处理未启动」重试共用一处实现。
 *
 * 409（来源正在处理或已处理完成）表示状态本身正常，只失效刷新，不弹失败提示；
 * 其余错误仍按失败提示，避免用户点不到反馈。
 */
export function useSourceProcessingTrigger(options?: { invalidates?: QueryKey[] }) {
  const queryClient = useQueryClient()
  const invalidates = options?.invalidates ?? []

  return useGroveMutation({
    mutationFn: (sourceId: number) => triggerProcessing(sourceId),
    invalidates: [queryKeys.sources, ...invalidates],
    onSuccess: () => {
      toast.success('已开始处理')
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        // 正在处理或已处理完成：刷新状态让界面反映真实进度，不当作失败
        queryClient.invalidateQueries({ queryKey: queryKeys.sources })
        return
      }
      toast.error(error instanceof Error ? error.message : '触发处理失败')
    },
  })
}
