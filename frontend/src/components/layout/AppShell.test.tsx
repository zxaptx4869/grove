import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'

const PROJECTS = [
  { id: 1, name: '装修计划', description: null, status: 'active' as const, template: 'empty', node_count: 0, created_at: '' },
  { id: 2, name: '找工作', description: null, status: 'paused' as const, template: 'empty', node_count: 0, created_at: '' },
  { id: 3, name: '旧归档', description: null, status: 'archived' as const, template: 'empty', node_count: 0, created_at: '' },
]

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/me') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ user: { username: 'demo' }, workspace: { name: '默认工作区' } }),
        })
      }
      if (url.startsWith('/api/projects')) {
        const status = new URL(url, 'http://localhost').searchParams.get('status_filter')
        const items = status ? PROJECTS.filter((project) => project.status === status) : PROJECTS
        return Promise.resolve({ ok: true, json: async () => items })
      }
      return Promise.resolve({ ok: true, json: async () => ({}) })
    }),
  )
}

/** 占位页面：展示当前 pathname 与查询参数，便于断言切换结果 */
function ProjectStub() {
  const location = useLocation()
  return <div data-testid="project-stub">{`${location.pathname}${location.search}`}</div>
}

function renderShell(initialPath: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/projects" element={<div>项目列表</div>} />
            <Route path="/projects/:projectId" element={<ProjectStub />} />
            <Route path="/projects/:projectId/review" element={<ProjectStub />} />
            <Route path="/inbox" element={<div>收集箱</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell 项目切换下拉', () => {
  it('项目工作台项目名可展开下拉，按状态分组展示全部非归档项目', async () => {
    stubFetch()
    renderShell('/projects/1')

    const trigger = await screen.findByRole('button', { name: /装修计划/ })
    expect(screen.getByText('进行中')).toBeInTheDocument()
    await userEvent.click(trigger)

    // 分组标签：进行中 / 暂停；已归档不进入常规分组
    expect(await screen.findByText('找工作')).toBeInTheDocument()
    expect(screen.getAllByText('进行中').length).toBeGreaterThan(0)
    expect(screen.getByText('暂停')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: '全部项目' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: /旧归档/ })).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('切换项目保留当前视图类型', async () => {
    stubFetch()
    renderShell('/projects/1?view=directory')

    const trigger = await screen.findByRole('button', { name: /装修计划/ })
    await userEvent.click(trigger)
    await userEvent.click(await screen.findByRole('menuitem', { name: '找工作' }))

    await waitFor(() => {
      expect(screen.getByTestId('project-stub')).toHaveTextContent('/projects/2?view=directory')
    })
    vi.unstubAllGlobals()
  })

  it('确认台视图切换同样保留路由段', async () => {
    stubFetch()
    renderShell('/projects/1/review')

    const trigger = await screen.findByRole('button', { name: /装修计划/ })
    await userEvent.click(trigger)
    await userEvent.click(await screen.findByRole('menuitem', { name: '找工作' }))

    await waitFor(() => {
      expect(screen.getByTestId('project-stub')).toHaveTextContent('/projects/2/review')
    })
    vi.unstubAllGlobals()
  })

  it('当前项目为已归档时在下拉顶部单列展示', async () => {
    stubFetch()
    renderShell('/projects/3')

    const trigger = await screen.findByRole('button', { name: /旧归档/ })
    await userEvent.click(trigger)

    const archivedItem = await screen.findByRole('menuitem', { name: /旧归档/ })
    expect(archivedItem).toHaveTextContent('已归档')
    expect(archivedItem).toHaveAttribute('aria-disabled', 'true')
    vi.unstubAllGlobals()
  })

  it('非项目页不显示切换按钮，保留最近项目区块', async () => {
    stubFetch()
    renderShell('/projects')

    expect(await screen.findByText('最近项目')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /装修计划/ })).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
