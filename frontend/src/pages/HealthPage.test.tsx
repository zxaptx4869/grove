import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { HealthPage } from './HealthPage'

describe('HealthPage', () => {
  it('调用后端健康检查并展示状态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'ok', version: '0.1.0' }),
      }),
    )

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HealthPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('ok')).toBeInTheDocument()
    expect(screen.getByText(/版本 0.1.0/)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
