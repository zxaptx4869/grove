import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { InboxPage } from './InboxPage'

function renderInbox() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('InboxPage', () => {
  it('渲染收集箱标题与未归属来源列表', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/sources') {
          expect(url.searchParams.get('unassigned')).toBe('true')
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 1,
                title: '洗烘使用体验.png',
                note: '关注烘干默认设置',
                project_id: null,
                status: 'waiting',
                created_at: '',
                updated_at: '',
                attachments: [
                  {
                    id: 1,
                    kind: 'image',
                    position: 0,
                    mime_type: 'image/png',
                    file_name: '洗烘使用体验.png',
                    text_content: null,
                  },
                ],
              },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderInbox()

    expect(await screen.findByRole('heading', { name: '收集箱' })).toBeInTheDocument()
    expect(await screen.findByText('洗烘使用体验.png')).toBeInTheDocument()
    expect(screen.getByLabelText('来源列表')).toBeInTheDocument()
    expect(screen.getByText('等待处理')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('来源为空时显示空状态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        return Promise.resolve({ ok: true, json: async () => (url.pathname === '/api/sources' ? [] : []) })
      }),
    )

    renderInbox()

    expect(await screen.findByText('还没有来源')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('失败来源显示重试并可触发处理接口', async () => {
    const calls: Array<{ method: string; path: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        if (url.pathname === '/api/projects') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/sources') {
          if (init?.method === 'POST') {
            return Promise.resolve({
              ok: true,
              json: async () => ({
                id: 1,
                title: 'x',
                note: null,
                project_id: null,
                status: 'failed',
                created_at: '',
                updated_at: '',
                attachments: [],
              }),
            })
          }
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 1,
                title: 'x',
                note: null,
                project_id: null,
                status: 'failed',
                created_at: '',
                updated_at: '',
                attachments: [],
              },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderInbox()
    await screen.findByText('x')
    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(calls.some((call) => call.method === 'POST' && call.path === '/api/sources/1/process')).toBe(true)
    vi.unstubAllGlobals()
  })
})
