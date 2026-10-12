import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSourceProcessingTrigger } from './useSourceProcessingTrigger'

const toastError = vi.fn()
const toastSuccess = vi.fn()
vi.mock('sonner', () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
  },
}))

function wrapper(queryClient: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

function respond(status: number) {
  return Promise.resolve({
    ok: status < 400,
    status,
    json: async () => (status < 400 ? {} : { detail: '来源正在处理中' }),
    text: async () => '来源正在处理中',
  })
}

describe('useSourceProcessingTrigger', () => {
  afterEach(() => vi.clearAllMocks())

  it('成功时提示已开始处理', async () => {
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    vi.stubGlobal('fetch', vi.fn(() => respond(200)))
    const { result } = renderHook(() => useSourceProcessingTrigger(), {
      wrapper: wrapper(queryClient),
    })

    result.current.mutate(1)

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('已开始处理'))
    expect(invalidate).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('409 视为状态本身正常：不提示失败，只刷新', async () => {
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    vi.stubGlobal('fetch', vi.fn(() => respond(409)))
    const { result } = renderHook(() => useSourceProcessingTrigger(), {
      wrapper: wrapper(queryClient),
    })

    result.current.mutate(1)

    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(1))
    expect(toastError).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('其他错误仍提示失败', async () => {
    const queryClient = new QueryClient()
    vi.stubGlobal('fetch', vi.fn(() => respond(500)))
    const { result } = renderHook(() => useSourceProcessingTrigger(), {
      wrapper: wrapper(queryClient),
    })

    result.current.mutate(1)

    await waitFor(() => expect(toastError).toHaveBeenCalled())
    vi.unstubAllGlobals()
  })
})
