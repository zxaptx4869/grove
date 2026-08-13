import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectContextPanel } from './ProjectContextPanel'

function renderPanel() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ProjectContextPanel projectId={7} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectContextPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('展示项目概要、当前关注、目录主题与状态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        expect(url.pathname).toBe('/api/projects/7/context')
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '完成新家装修',
            project_summary: '围绕装修目标整理知识',
            current_focus: '优先确认预算',
            directory_topics: ['装修准备', '预算'],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel()

    expect(await screen.findByText('围绕装修目标整理知识')).toBeInTheDocument()
    expect(screen.getByText('优先确认预算')).toBeInTheDocument()
    expect(screen.getByText('装修准备')).toBeInTheDocument()
    expect(screen.getByText('已生成')).toBeInTheDocument()
  })

  it('保存纠正会调用 PATCH 接口', async () => {
    const calls: Array<{ method: string; path: string; body?: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({
          method: init?.method ?? 'GET',
          path: url.pathname,
          body: typeof init?.body === 'string' ? init.body : undefined,
        })
        if (init?.method === 'PATCH') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              project_id: 7,
              user_description: null,
              project_summary: '我的纠正概要',
              current_focus: '只看预算',
              directory_topics: [],
              lifecycle_status: 'active',
              generated_at: null,
              status: 'pending',
              error: null,
              corrections: { project_summary: '我的纠正概要', current_focus: '只看预算' },
            }),
          })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '装修',
            project_summary: '旧概要',
            current_focus: '旧关注',
            directory_topics: [],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: '纠正' }))
    await userEvent.clear(screen.getByLabelText('项目概要'))
    await userEvent.type(screen.getByLabelText('项目概要'), '我的纠正概要')
    await userEvent.clear(screen.getByLabelText('当前关注方向'))
    await userEvent.type(screen.getByLabelText('当前关注方向'), '只看预算')
    await userEvent.click(screen.getByRole('button', { name: '保存纠正' }))

    expect(
      calls.some(
        (call) =>
          call.method === 'PATCH' &&
          call.path === '/api/projects/7/context' &&
          call.body?.includes('我的纠正概要'),
      ),
    ).toBe(true)
  })

  it('重新生成会调用 refresh 接口', async () => {
    const calls: Array<{ method: string; path: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '装修',
            project_summary: '概要',
            current_focus: '关注',
            directory_topics: [],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: '重新生成' }))

    expect(
      calls.some(
        (call) => call.method === 'POST' && call.path === '/api/projects/7/context/refresh',
      ),
    ).toBe(true)
  })
})
