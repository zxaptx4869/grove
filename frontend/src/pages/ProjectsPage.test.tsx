import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProjectsPage } from './ProjectsPage'
import { TooltipProvider } from '@/components/ui/tooltip'

describe('ProjectsPage', () => {
  it('项目查询未完成时显示稳定加载行', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => undefined)))
    const queryClient = new QueryClient()

    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ProjectsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByLabelText('项目加载中')).toBeInTheDocument()
    view.unmount()
    vi.unstubAllGlobals()
  })

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
    expect(screen.getByRole('link', { name: '进入项目' })).toHaveAttribute('href', '/projects/1')
    expect(screen.getByText('梳理装修决策 · 3 个目录节点')).toBeInTheDocument()
    expect(screen.getByText(/3 个目录节点/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '装修计划 更多操作' })).toBeInTheDocument()
    expect(screen.queryByText(/正式知识|候选待确认|最近更新/)).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('项目查询失败时显示邻近错误与重试入口', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ detail: '服务暂不可用' }) }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ProjectsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('项目列表加载失败，请重试。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeEnabled()
    vi.unstubAllGlobals()
  })
})
