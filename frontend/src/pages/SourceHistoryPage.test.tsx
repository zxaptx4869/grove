import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { SourceHistoryPage } from './SourceHistoryPage'

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function renderPage(initialEntry = '/sources') {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <SourceHistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const SOURCE = {
  id: 1,
  title: '闭水试验 24 小时',
  note: null,
  project_id: 10,
  status: 'done',
  recommended_project_id: null,
  project_recommendation_reason: null,
  created_at: '',
  updated_at: '',
  project_locked: true,
  evidence_entry_count: 1,
  pending_candidate_count: 0,
  attachments: [],
}

describe('SourceHistoryPage', () => {
  it('按项目预筛并展示分页结果', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push(url.href)
        if (url.pathname === '/api/projects') return ok([])
        if (url.pathname === '/api/sources/query') {
          return ok({ items: [SOURCE], total: 1, limit: 20, offset: 0 })
        }
        return ok([])
      }),
    )

    renderPage('/sources?project=10')

    expect(await screen.findByText('全部来源')).toBeInTheDocument()
    expect(await screen.findByText('闭水试验 24 小时')).toBeInTheDocument()
    expect(calls.some((href) => href.includes('/api/sources/query') && href.includes('project_id=10'))).toBe(true)
    expect(screen.getByText('第 1 / 1 页 · 共 1 条')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('搜索触发关键词查询', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push(url.href)
        if (url.pathname === '/api/projects') return ok([])
        if (url.pathname === '/api/sources/query') {
          return ok({ items: [], total: 0, limit: 20, offset: 0 })
        }
        return ok([])
      }),
    )

    renderPage()

    await userEvent.type(screen.getByLabelText('搜索来源'), '闭水')
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))

    await screen.findByText('还没有来源')
    expect(calls.some((href) => href.includes('/api/sources/query') && href.includes('q=%E9%97%AD%E6%B0%B4'))).toBe(true)
    vi.unstubAllGlobals()
  })

  it('清空搜索后回到全部数据', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push(url.href)
        if (url.pathname === '/api/projects') return ok([])
        if (url.pathname === '/api/sources/query') {
          return ok({ items: [], total: 0, limit: 20, offset: 0 })
        }
        return ok([])
      }),
    )

    renderPage()

    await userEvent.type(screen.getByLabelText('搜索来源'), '闭水')
    await userEvent.click(screen.getByRole('button', { name: '搜索' }))
    await screen.findByText('还没有来源')
    await userEvent.click(screen.getByRole('button', { name: '清空搜索' }))

    await screen.findByText('还没有来源')
    expect(
      calls.some(
        (href) =>
          href.includes('/api/sources/query') && !href.includes('q='),
      ),
    ).toBe(true)
    vi.unstubAllGlobals()
  })
})
