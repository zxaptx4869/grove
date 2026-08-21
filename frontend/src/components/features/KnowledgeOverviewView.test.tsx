import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { KnowledgeOverviewView } from './KnowledgeOverviewView'

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
        name: '空间规划',
        description: null,
        position: 0,
        entry_count: 1,
        children: [
          {
            id: 3,
            name: '客厅',
            description: null,
            position: 0,
            entry_count: 1,
            children: [],
          },
        ],
      },
    ],
  },
]

const entries = [
  { id: 11, project_id: 1, node_id: 1, node_name: '装修准备', title: '整体预算', content: '先定总预算再分项。', main_type: 'method', info_nature: 'advice', applicable_condition: null, note: null, created_at: '2026-08-14T00:00:00Z', updated_at: '2026-08-14T00:00:00Z', evidences: [] },
  { id: 12, project_id: 1, node_id: 2, node_name: '空间规划', title: '动线规划', content: '先确定主要使用场景。', main_type: 'method', info_nature: 'advice', applicable_condition: null, note: null, created_at: '2026-08-14T00:00:00Z', updated_at: '2026-08-14T00:00:00Z', evidences: [] },
  { id: 13, project_id: 1, node_id: 3, node_name: '客厅', title: '无主灯', content: '无主灯布局先确定使用场景。', main_type: 'method', info_nature: 'advice', applicable_condition: null, note: null, created_at: '2026-08-14T00:00:00Z', updated_at: '2026-08-14T00:00:00Z', evidences: [] },
]

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function mockApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/projects/1/tree')) return ok(tree)
      if (url.includes('/api/projects/1/entries')) return ok(entries)
      if (url.includes('/nodes/') && url.includes('/entries')) {
        const scope = new URL(url, 'http://localhost').searchParams.get('scope')
        const nodeId = Number(url.match(/\/nodes\/(\d+)\//)?.[1])
        return ok(scope === 'direct' ? entries.filter((entry) => entry.node_id === nodeId) : entries)
      }
      return ok([])
    }),
  )
}

function renderView(path: string) {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/projects/:projectId"
            element={<KnowledgeOverviewView projectId={1} projectName="房子装修" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('KnowledgeOverviewView', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('默认展示旭日图模式', async () => {
    mockApi()
    renderView('/projects/1?view=overview')

    const group = screen.getByRole('group', { name: '模式切换' })
    expect(within(group).getByRole('button', { name: '旭日图' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(group).getByRole('button', { name: '思维导图' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(await screen.findByRole('button', { name: '放大' })).toBeInTheDocument()
  })

  it('点击「思维导图」切换模式并保留思维导图内容', async () => {
    mockApi()
    renderView('/projects/1?view=overview')

    fireEvent.click(screen.getByRole('button', { name: '思维导图' }))
    expect(screen.getByRole('button', { name: '旭日图' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(await screen.findByTestId('mind-map-canvas')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /展开/ })).toBeInTheDocument()
  })

  it('深链 mode=mindmap 直接进入思维导图并定位节点', async () => {
    mockApi()
    renderView('/projects/1?view=overview&mode=mindmap&node=2')

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    expect(await canvas.findByRole('button', { name: /^空间规划/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('旭日图「在思维导图中查看」跨模式联动并聚焦节点', async () => {
    mockApi()
    renderView('/projects/1?view=overview')

    const aside = within(await screen.findByRole('complementary', { name: '全景侧栏' }))
    fireEvent.click(aside.getByRole('button', { name: /空间规划/ }))
    fireEvent.click(await screen.findByRole('button', { name: /在思维导图中查看/ }))

    expect(screen.getByRole('button', { name: '思维导图' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    expect(await canvas.findByRole('button', { name: /^空间规划/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})
