import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectContextPanel } from './ProjectContextPanel'
import type { TreeNodePayload } from '@/lib/api'

function renderPanel(nodes: TreeNodePayload[] = []) {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ProjectContextPanel projectId={7} nodes={nodes} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProjectContextPanel', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('展示项目概要、当前关注、目录主题与状态', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        expect(url.pathname).toBe('/api/projects/7/context')
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '完成新家装修',
            project_summary: '围绕装修目标整理知识',
            current_focus: '优先确认预算',
            directory_topics: ['装修准备', '预算'],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            version: 3,
            last_update_reason: 'entry_archived',
            entries_summary: {
              total: 5,
              by_type: { knowledge: 3, method: 2 },
              by_top_node: [
                { node_id: 1, name: '装修准备', count: 3 },
                { node_id: 2, name: '预算', count: 2 },
              ],
              recent: [],
              truncated_count: 0,
            },
            recent_themes: ['预算框架', '材料信息'],
            provider: 'llm',
            model: 'deepseek-chat',
            is_fallback: false,
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel([
      { id: 1, name: '装修准备', description: null, position: 0, entry_count: 0, children: [] },
      { id: 2, name: '预算', description: null, position: 0, entry_count: 0, children: [] },
    ])

    expect(await screen.findByText('围绕装修目标整理知识')).toBeInTheDocument()
    expect(screen.getByText('优先确认预算')).toBeInTheDocument()
    expect(screen.getByText('装修准备')).toBeInTheDocument()
    expect(screen.getByText('预算框架')).toBeInTheDocument()
    expect(screen.getByText('已确认 5 条正式知识')).toBeInTheDocument()
    expect(screen.getByText(/版本 v3/)).toBeInTheDocument()
    expect(screen.getByText(/更新原因 entry_archived/)).toBeInTheDocument()
    expect(screen.getByText('真实模型')).toBeInTheDocument()
    expect(screen.getByText(/模型 deepseek-chat/)).toBeInTheDocument()
    expect(screen.getByText('已生成')).toBeInTheDocument()
  })

  it('保存纠正会调用 PATCH 接口', async () => {
    const calls: Array<{ method: string; path: string; body?: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({
          method: init?.method ?? 'GET',
          path: url.pathname,
          body: typeof init?.body === 'string' ? init.body : undefined,
        })
        if (init?.method === 'PATCH') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              project_id: 7,
              user_description: null,
              project_summary: '我的纠正概要',
              current_focus: '只看预算',
              directory_topics: [],
              lifecycle_status: 'active',
              generated_at: null,
              version: 0,
              last_update_reason: null,
              entries_summary: null,
              recent_themes: [],
              provider: 'offline',
              model: null,
              is_fallback: true,
              status: 'pending',
              error: null,
              corrections: { project_summary: '我的纠正概要', current_focus: '只看预算' },
            }),
          })
        }
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '装修',
            project_summary: '旧概要',
            current_focus: '旧关注',
            directory_topics: [],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            version: 1,
            last_update_reason: 'user_correction',
            entries_summary: null,
            recent_themes: [],
            provider: 'offline',
            model: null,
            is_fallback: true,
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: '纠正' }))
    await userEvent.clear(screen.getByLabelText('项目概要'))
    await userEvent.type(screen.getByLabelText('项目概要'), '我的纠正概要')
    await userEvent.clear(screen.getByLabelText('当前关注方向'))
    await userEvent.type(screen.getByLabelText('当前关注方向'), '只看预算')
    await userEvent.click(screen.getByRole('button', { name: '保存纠正' }))

    expect(
      calls.some(
        (call) =>
          call.method === 'PATCH' &&
          call.path === '/api/projects/7/context' &&
          call.body?.includes('我的纠正概要'),
      ),
    ).toBe(true)
  })

  it('重新生成会调用 refresh 接口', async () => {
    const calls: Array<{ method: string; path: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '装修',
            project_summary: '概要',
            current_focus: '关注',
            directory_topics: [],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            version: 2,
            last_update_reason: 'manual_refresh',
            entries_summary: null,
            recent_themes: [],
            provider: 'offline',
            model: null,
            is_fallback: true,
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel()
    await userEvent.click(await screen.findByRole('button', { name: '重新生成' }))

    expect(
      calls.some(
        (call) => call.method === 'POST' && call.path === '/api/projects/7/context/refresh',
      ),
    ).toBe(true)
  })

  it('目录主题过多时折叠展示并提示剩余数量', async () => {
    const nodes = Array.from({ length: 10 }, (_, index) => ({
      id: index + 1,
      name: `主题${index + 1}`,
      description: null,
      position: index,
      entry_count: 0,
      children: [],
    }))
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        expect(url.pathname).toBe('/api/projects/7/context')
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 7,
            user_description: '装修',
            project_summary: '概要',
            current_focus: '关注',
            directory_topics: [],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            version: 1,
            last_update_reason: null,
            entries_summary: null,
            recent_themes: [],
            provider: 'offline',
            model: null,
            is_fallback: true,
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }),
    )

    renderPanel(nodes)

    expect(await screen.findByText('+2')).toBeInTheDocument()
    expect(screen.getByText('主题8')).toBeInTheDocument()
    expect(screen.queryByText('主题9')).not.toBeInTheDocument()
  })
})
