import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { useGroveMutation } from './useGroveMutation'
import { queryKeys } from '@/lib/queryKeys'

describe('useGroveMutation', () => {
  it('成功后在 invalidates 中声明的查询会重新拉取', async () => {
    const fetcher = vi.fn(async () => [])
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    function Harness() {
      useQuery({ queryKey: queryKeys.sources, queryFn: fetcher })
      const mutation = useGroveMutation({
        mutationFn: async () => ({ ok: true }),
        invalidates: [queryKeys.sources],
      })
      return <button onClick={() => mutation.mutate()}>执行变更</button>
    }

    render(
      <QueryClientProvider client={queryClient}>
        <Harness />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
    await userEvent.click(screen.getByRole('button', { name: '执行变更' }))
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2))
  })
})
