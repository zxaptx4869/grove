import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MindMapView } from './MindMapView'

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
  node_name: '房子装修',
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
  {
    ...baseEntry,
    id: 11,
  },
  {
    ...baseEntry,
    id: 12,
    node_id: 2,
    node_name: '空间规划',
    title: '动线规划',
    content: '先确定主要使用场景。',
  },
  {
    ...baseEntry,
    id: 13,
    node_id: 3,
    node_name: '客厅',
    title: '无主灯',
    content: '无主灯布局先确定使用场景。',
  },
]

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function mockMindMapApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/projects/1/tree')) {
        return ok(tree)
      }
      if (url.includes('/api/projects/1/entries')) {
        return ok(entries)
      }
      if (url.includes('/nodes/') && url.includes('/entries')) {
        const params = new URL(url, 'http://localhost').searchParams
        const scope = params.get('scope')
        const nodeId = Number(url.match(/\/nodes\/(\d+)\//)?.[1])
        return ok(
          scope === 'direct'
            ? entries.filter((entry) => entry.node_id === nodeId)
            : entries,
        )
      }
      if (url.includes('/api/entries/')) {
        const entryId = Number(url.split('/').pop())
        return ok(entries.find((entry) => entry.id === entryId) ?? null)
      }
      return ok([])
    }),
  )
}

function renderMindMap(path = '/projects/1?view=mindmap') {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <MindMapView projectId={1} projectName="房子装修" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('MindMapView', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('只展示目录节点并显示直接数 / 子树数', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    const root = await canvas.findByRole('button', { name: /^房子装修/ })
    expect(root).toHaveTextContent('0 / 3')
    expect(canvas.getByRole('button', { name: /^装修准备/ })).toHaveTextContent('1 / 3')
    expect(canvas.getByRole('button', { name: /^空间规划/ })).toHaveTextContent('1 / 2')
    expect(canvas.getByRole('button', { name: /^客厅/ })).toHaveTextContent('1 / 1')
    expect(screen.getByText('整体预算')).toBeInTheDocument()
  })

  it('首行节点不被画布顶部裁剪', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvasElement = await screen.findByTestId('mind-map-canvas')
    const items = canvasElement.querySelectorAll('[data-map-item]')
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) {
      const top = Number.parseFloat((item as HTMLElement).style.top)
      expect(top).toBeGreaterThanOrEqual(0)
    }
  })

  it('展开节点直接知识后知识小卡出现在画布', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))

    expect(await canvas.findByRole('button', { name: /动线规划/ })).toBeInTheDocument()
  })

  it('点击知识小卡后悬浮窗展示全文并可关闭', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    fireEvent.click(await canvas.findByRole('button', { name: /动线规划/ }))

    expect(await screen.findByText('先确定主要使用场景。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '关闭' })).toBeInTheDocument()
  })

  it('hover 知识小卡时预览悬浮窗，移开后消失', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    const card = await canvas.findByRole('button', { name: /动线规划/ })
    fireEvent.mouseEnter(card)
    expect(await screen.findByText('先确定主要使用场景。')).toBeInTheDocument()

    fireEvent.mouseLeave(card)
    expect(screen.queryByText('先确定主要使用场景。')).not.toBeInTheDocument()
  })

  it('再次点击收起后知识小卡消失', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    await canvas.findByRole('button', { name: /动线规划/ })
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))

    expect(canvas.queryByRole('button', { name: /动线规划/ })).not.toBeInTheDocument()
  })

  it('默认选中项目总根并在侧栏展示项目全部知识', async () => {
    mockMindMapApi()
    renderMindMap()

    expect(await screen.findByText(/全部正式知识/)).toHaveTextContent('共 3 条')
    expect(await screen.findByText('整体预算')).toBeInTheDocument()
    expect(screen.getByText('动线规划')).toBeInTheDocument()
    expect(screen.getByText('无主灯')).toBeInTheDocument()
    expect(
      screen.queryByRole('checkbox', { name: /包含子树/ }),
    ).not.toBeInTheDocument()
  })

  it('展开 / 收起全局控制可见节点', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    await canvas.findByRole('button', { name: /^客厅/ })
    fireEvent.click(screen.getByRole('button', { name: '收起' }))
    expect(canvas.queryByRole('button', { name: /^空间规划/ })).not.toBeInTheDocument()
    expect(canvas.queryByRole('button', { name: /^客厅/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '展开' }))
    expect(await canvas.findByRole('button', { name: /^客厅/ })).toBeInTheDocument()
  })

  it('聚焦子树以选中节点为临时根，面包屑可返回项目根', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    fireEvent.click(screen.getByRole('button', { name: /聚焦子树/ }))

    expect(canvas.queryByRole('button', { name: /^房子装修/ })).not.toBeInTheDocument()
    expect(canvas.getByRole('button', { name: /^空间规划/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '项目根' }))
    expect(await canvas.findByRole('button', { name: /^房子装修/ })).toBeInTheDocument()
  })

  it('搜索命中节点名称并高亮，无命中给出提示', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    const input = await screen.findByRole('textbox', { name: '搜索目录节点' })
    fireEvent.change(input, { target: { value: '客厅' } })
    expect(screen.getByText('匹配 1 个节点')).toBeInTheDocument()
    expect(canvas.getByRole('button', { name: /^客厅/ })).toHaveClass('ring-2')

    fireEvent.change(input, { target: { value: '不存在' } })
    expect(screen.getByText('没有匹配的目录节点')).toBeInTheDocument()
  })

  it('空目录显示真实空态并提供创建入口', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        ok(String(input).includes('/tree') ? [] : []),
      ),
    )
    renderMindMap()

    expect(await screen.findByRole('heading', { name: '目录还是空的' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '去知识空间创建目录' })).toHaveAttribute(
      'href',
      '/projects/1?view=directory',
    )
  })

  it('阅读侧栏默认勾选包含子树并随范围切换请求', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^客厅/ }))
    const checkbox = await screen.findByRole('checkbox', { name: /包含子树/ })
    expect(checkbox).toBeChecked()
    expect(await screen.findByText('整体预算')).toBeInTheDocument()
    expect(screen.getByText('动线规划')).toBeInTheDocument()
    expect(screen.getAllByText('无主灯').length).toBeGreaterThan(0)

    fireEvent.click(checkbox)
    expect(screen.getAllByText('无主灯').length).toBeGreaterThan(0)
    expect(screen.queryByText('整体预算')).not.toBeInTheDocument()
    expect(screen.queryByText('动线规划')).not.toBeInTheDocument()
  })

  it('点击列表条目后悬浮窗展示详情', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^客厅/ }))
    const aside = within(await screen.findByRole('complementary', { name: '阅读侧栏' }))
    fireEvent.click(await aside.findByRole('button', { name: /无主灯/ }))

    expect(await screen.findByText('无主灯布局先确定使用场景。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '无主灯' })).toBeInTheDocument()
  })

  it('提供「在知识空间中打开」并携带节点参数', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    const link = await screen.findByRole('link', { name: /在知识空间中打开/ })
    expect(link).toHaveAttribute('href', '/projects/1?view=directory&node=2')
  })

  it('画布与侧栏不出现任何目录管理入口', async () => {
    mockMindMapApi()
    renderMindMap()

    const canvas = within(await screen.findByTestId('mind-map-canvas'))
    fireEvent.click(await canvas.findByRole('button', { name: /^空间规划/ }))
    expect(screen.queryByRole('button', { name: /AI 拓展/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编辑节点/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删除节点/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /添加子节点/ })).not.toBeInTheDocument()
  })
})
