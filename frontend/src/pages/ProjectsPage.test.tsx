import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProjectsPage } from './ProjectsPage'
import { TooltipProvider } from '@/components/ui/tooltip'

describe('ProjectsPage', () => {
  it('渲染项目列表空状态且无报错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [],
      }),
    )
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ProjectsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: '项目' })).toBeInTheDocument()
    expect(await screen.findByText('没有进行中项目')).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(4)
    expect(screen.getByRole('button', { name: '新建项目' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('使用真实项目字段渲染紧凑项目行', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const status = new URL(String(input), 'http://localhost').searchParams.get('status_filter')
        return Promise.resolve({
          ok: true,
          json: async () => status === 'active' ? [{ id: 1, name: '装修计划', description: '梳理装修决策', status: 'active', template: 'empty', node_count: 3, created_at: '' }] : [],
        })
      }),
    )
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter><TooltipProvider><ProjectsPage /></TooltipProvider></MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('link', { name: '装修计划' })).toBeInTheDocument()
    expect(screen.getByText(/3 个目录节点/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '装修计划 更多操作' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
