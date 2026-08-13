import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ProjectPage } from './ProjectPage'

describe('ProjectPage', () => {
  it('渲染目录树且无报错', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/projects/1/tree')) {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 1,
                name: '装修准备',
                description: null,
                position: 0,
                children: [{ id: 2, name: '需求确认', description: null, position: 0, children: [] }],
              },
            ],
          })
        }
        const status = new URL(url, 'http://localhost').searchParams.get('status_filter')
        return Promise.resolve({
          ok: true,
          json: async () => status === 'active' ? [{ id: 1, name: '房子装修', description: '完成新家装修', status: 'active', template: 'blank', node_count: 2, created_at: '' }] : [],
        })
      }),
    )
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/projects/1']}>
          <Routes>
            <Route path="/projects/:projectId" element={<ProjectPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByText('房子装修')).toBeInTheDocument()
    expect(await screen.findByText('装修准备')).toBeInTheDocument()
    expect(screen.getByText('需求确认')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '根节点' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '与 AI 共创目录' })).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
