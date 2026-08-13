import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectPage } from './ProjectPage'

function mockProjectApi() {
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
}

function renderProject(path: string) {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('默认渲染项目首页与真实目录概览', async () => {
    mockProjectApi()
    renderProject('/projects/1')

    expect(await screen.findByRole('heading', { name: '房子装修' })).toBeInTheDocument()
    expect(screen.getByText('当前共有 2 个目录节点')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /管理目录/ })).toHaveAttribute('href', '/projects/1?view=directory')
    expect(screen.getByRole('group', { name: '项目状态' })).toBeInTheDocument()
  })

  it('通过 URL 渲染目录树和已有操作入口', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('heading', { name: '目录管理' })).toBeInTheDocument()
    expect(await screen.findByText('装修准备')).toBeInTheDocument()
    expect(screen.getByText('需求确认')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '根节点' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建根节点' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '与 AI 共创目录' })).toBeInTheDocument()
  })
})
