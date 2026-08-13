import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProjectSources } from './ProjectSources'

describe('ProjectSources', () => {
  it('按项目 id 请求并渲染来源', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/sources') {
          expect(url.searchParams.get('project_id')).toBe('7')
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 2,
                title: '窗帘盒预留笔记',
                note: null,
                project_id: 7,
                created_at: '',
                updated_at: '',
                attachments: [
                  {
                    id: 2,
                    kind: 'text',
                    position: 0,
                    mime_type: null,
                    file_name: null,
                    text_content: '窗帘盒预留 20cm',
                  },
                ],
              },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ProjectSources projectId={7} />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('窗帘盒预留笔记')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
