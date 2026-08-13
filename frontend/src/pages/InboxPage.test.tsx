import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
})
