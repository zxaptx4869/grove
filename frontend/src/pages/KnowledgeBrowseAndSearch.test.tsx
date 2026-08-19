import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectPage } from './ProjectPage'
import { SearchPage } from './SearchPage'

const tree = [
  {
    id: 1,
    name: '装修准备',
    description: null,
    position: 0,
    entry_count: 1,
    children: [
      {
        id: 2,
        name: '需求确认',
        description: null,
        position: 0,
        entry_count: 1,
        children: [],
      },
    ],
  },
]

const entry11 = {
  id: 11,
  project_id: 1,
  node_id: 1,
  node_name: '装修准备',
  title: '闭水试验',
  content: '闭水试验至少持续 24 小时',
  main_type: 'knowledge',
  info_nature: 'fact',
  applicable_condition: null,
  note: null,
  created_at: '2026-08-14T00:00:00Z',
  updated_at: '2026-08-14T00:00:00Z',
  evidences: [
    {
      id: 101,
      source_id: 5,
      attachment_id: null,
      quote: '闭水试验',
      source_title: '闭水试验来源',
    },
  ],
}

const entry12 = {
  ...entry11,
  id: 12,
  node_id: 2,
  node_name: '需求确认',
  title: '水电改造',
  content: '水电改造要在封槽前完成',
}

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function mockProjectApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/projects/1/context')) {
        return ok({
          project_id: 1,
          user_description: '完成新家装修',
          project_summary: '围绕「完成新家装修」进行知识整理。',
          current_focus: '继续建立正式目录。',
          directory_topics: ['装修准备'],
          lifecycle_status: 'active',
          generated_at: '2026-08-13T00:00:00Z',
          status: 'ready',
          error: null,
          corrections: { project_summary: null, current_focus: null },
        })
      }
      if (url.includes('/api/projects/1/tree')) {
        return ok(tree)
      }
      if (url.includes('/nodes/')) {
        const scope = new URL(url, 'http://localhost').searchParams.get('scope')
        return ok(scope === 'descendants' ? [entry12] : [entry11])
      }
      if (url.includes('/api/search')) {
        return ok([{ ...entry11, project_name: '房子装修' }])
      }
      const status = new URL(url, 'http://localhost').searchParams.get('status_filter')
      return ok(
        status === 'active'
          ? [
              {
                id: 1,
                name: '房子装修',
                description: '完成新家装修',
                status: 'active',
                template: 'empty',
                node_count: 2,
                created_at: '',
              },
            ]
          : [],
      )
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

describe('知识空间浏览与项目内搜索', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it('默认卡片视图，可切换列表并记住项目内偏好', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('heading', { name: '闭水试验' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: '标题' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '列表视图' }))

    expect(screen.getByRole('columnheader', { name: '标题' })).toBeInTheDocument()
    expect(window.localStorage.getItem('grove.view-mode.1')).toBe('list')
  })

  it('按项目记住的列表偏好会在进入知识空间时生效', async () => {
    window.localStorage.setItem('grove.view-mode.1', 'list')
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('columnheader', { name: '标题' })).toBeInTheDocument()
  })

  it('仅本节点与仅后代范围切换展示对应知识', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('heading', { name: '闭水试验' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '水电改造' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '仅后代（1）' }))

    expect(await screen.findByRole('heading', { name: '水电改造' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '闭水试验' })).not.toBeInTheDocument()
  })

  it('项目内搜索展示结果并隐藏范围切换', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    const input = await screen.findByRole('textbox', { name: '搜索本项目知识' })
    fireEvent.change(input, { target: { value: '闭水' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByRole('heading', { name: '搜索结果' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '闭水试验' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '仅本节点（1）' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '列表视图' })).toBeInTheDocument()
  })
})

describe('全局搜索', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('展示所属项目并在点击后跳转项目知识空间', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/search')) {
          return ok([{ ...entry11, project_name: '房子装修' }])
        }
        return ok([])
      }),
    )

    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/search']}>
          <Routes>
            <Route path="/search" element={<SearchPage />} />
            <Route path="/projects/:projectId" element={<div>项目知识空间页</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const input = screen.getByRole('textbox', { name: '全局搜索' })
    fireEvent.change(input, { target: { value: '闭水' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(await screen.findByText('房子装修')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /闭水试验/ }))

    expect(await screen.findByText('项目知识空间页')).toBeInTheDocument()
  })
})
