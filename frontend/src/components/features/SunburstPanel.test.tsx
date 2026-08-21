import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SunburstPanel } from './SunburstPanel'

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

const baseEntry = {
  project_id: 1,
  node_id: 1,
  node_name: '装修准备',
  title: '整体预算',
  content: '先定总预算再分项。',
  main_type: 'method',
  info_nature: 'advice',
  applicable_condition: null,
  note: null,
  created_at: '2026-08-14T00:00:00Z',
  updated_at: '2026-08-14T00:00:00Z',
  evidences: [],
}

const entries = [
  { ...baseEntry, id: 11 },
  { ...baseEntry, id: 12, node_id: 2, node_name: '空间规划', title: '动线规划', content: '先确定主要使用场景。' },
  { ...baseEntry, id: 13, node_id: 3, node_name: '客厅', title: '无主灯', content: '无主灯布局先确定使用场景。' },
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
        const params = new URL(url, 'http://localhost').searchParams
        const scope = params.get('scope')
        const nodeId = Number(url.match(/\/nodes\/(\d+)\//)?.[1])
        return ok(
          scope === 'direct' ? entries.filter((entry) => entry.node_id === nodeId) : entries,
        )
      }
      return ok([])
    }),
  )
}

function renderPanel(initialNodeId: number | null = null) {
  const queryClient = new QueryClient()
  const onOpenInMindMap = vi.fn(() => undefined)
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/projects/1?view=overview']}>
        <SunburstPanel
          projectId={1}
          projectName="房子装修"
          initialNodeId={initialNodeId}
          sideOpen
          onOpenInMindMap={onOpenInMindMap}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return onOpenInMindMap
}

describe('SunburstPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('渲染旭日图扇区，hover 显示直接/后代/合计', async () => {
    mockApi()
    renderPanel()

    await screen.findByRole('button', { name: '放大' })
    const path = document.querySelector('svg path')
    expect(path).not.toBeNull()

    fireEvent.mouseMove(path as Element, { clientX: 120, clientY: 120 })
    expect(await screen.findByText(/直接 \d+ · 后代 \d+ · 合计 \d+/)).toBeInTheDocument()
  })

  it('大纲点击联动钻取，并可发起「在思维导图中查看」', async () => {
    mockApi()
    const onOpenInMindMap = renderPanel()

    const aside = within(await screen.findByRole('complementary', { name: '全景侧栏' }))
    fireEvent.click(aside.getByRole('button', { name: /空间规划/ }))

    expect(await screen.findByText('在思维导图中查看')).toBeInTheDocument()
    const bridge = screen.getByRole('button', { name: /在思维导图中查看/ })
    fireEvent.click(bridge)
    expect(onOpenInMindMap).toHaveBeenCalledWith(2)
  })

  it('缩放按钮改变 viewBox，适应窗口恢复完整圆', async () => {
    mockApi()
    renderPanel()

    await screen.findByRole('button', { name: '放大' })
    const svg = document.querySelector('svg')
    expect(svg?.getAttribute('viewBox')).toBe('0 0 720 720')
    fireEvent.click(screen.getByRole('button', { name: '缩小' }))
    expect(svg?.getAttribute('viewBox')).not.toBe('0 0 720 720')
    fireEvent.click(screen.getByRole('button', { name: '适应窗口' }))
    expect(svg?.getAttribute('viewBox')).toBe('0 0 720 720')
  })

  it('空目录显示真实空态', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => ok(String(input).includes('/tree') ? [] : [])))
    renderPanel()

    expect(await screen.findByRole('heading', { name: '目录还是空的' })).toBeInTheDocument()
  })

  it('点击知识条目固定悬浮详情', async () => {
    mockApi()
    renderPanel()

    const aside = within(await screen.findByRole('complementary', { name: '全景侧栏' }))
    fireEvent.click(aside.getByRole('button', { name: /空间规划/ }))
    fireEvent.click(await aside.findByRole('button', { name: /动线规划/ }))

    expect(await screen.findByText('先确定主要使用场景。')).toBeInTheDocument()
  })
})
