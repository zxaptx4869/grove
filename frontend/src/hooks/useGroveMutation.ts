import {
  useMutation,
  useQueryClient,
  type QueryKey,
  type UseMutationOptions,
  type UseMutationResult,
} from '@tanstack/react-query'

interface GroveMutationOptions<TData, TError, TVariables, TContext>
  extends UseMutationOptions<TData, TError, TVariables, TContext> {
  /** 成功后需要失效的查询键（使用顶层前缀以覆盖子键）。 */
  invalidates?: QueryKey[]
}

/**
 * Grove 统一 mutation 封装：声明式失效。
 * 每个会改变服务端状态的 mutation 都必须显式声明 invalidates，成功后自动失效相关查询。
 */
export function useGroveMutation<
  TData = unknown,
  TError = Error,
  TVariables = void,
  TContext = unknown,
>(
  options: GroveMutationOptions<TData, TError, TVariables, TContext>,
): UseMutationResult<TData, TError, TVariables, TContext> {
  const queryClient = useQueryClient()
  const { invalidates = [], ...rest } = options
  const originalOnSuccess = rest.onSuccess

  return useMutation<TData, TError, TVariables, TContext>({
    ...rest,
    onSuccess: (...args: Parameters<NonNullable<typeof originalOnSuccess>>) => {
      for (const key of invalidates) {
        queryClient.invalidateQueries({ queryKey: key })
      }
      originalOnSuccess?.(...args)
    },
  })
}
