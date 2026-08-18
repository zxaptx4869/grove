import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectPage } from './ProjectPage'

function mockProjectApi({ emptyTree = false }: { emptyTree?: boolean } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/projects/1/context')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            project_id: 1,
            user_description: '完成新家装修',
            project_summary: '围绕「完成新家装修」进行知识整理。',
            current_focus: '继续建立正式目录。',
            directory_topics: emptyTree ? [] : ['装修准备'],
            lifecycle_status: 'active',
            generated_at: '2026-08-13T00:00:00Z',
            status: 'ready',
            error: null,
            corrections: { project_summary: null, current_focus: null },
          }),
        })
      }
      if (url.includes('/api/projects/1/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () =>
            emptyTree
              ? []
              : [
                  {
                    id: 1,
                    name: '装修准备',
                    description: null,
                    position: 0,
                    children: [
                      { id: 2, name: '需求确认', description: null, position: 0, children: [] },
                    ],
                  },
                ],
        })
      }
      if (url.endsWith('/api/projects/1/directory-draft')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 10,
            project_id: 1,
            status: 'awaiting_input',
            next_action: 'clarify',
            clarify_batches: 0,
            clarify: [
              {
                id: 'dimension',
                text: '目录按什么维度组织？',
                options: ['按阶段', '按空间', '按主题'],
                multiple: false,
              },
            ],
            nodes: [],
            provider: 'offline',
            model: null,
            is_fallback: true,
            last_error: null,
            created_at: '',
            updated_at: '',
          }),
        })
      }
      const status = new URL(url, 'http://localhost').searchParams.get('status_filter')
      return Promise.resolve({
        ok: true,
        json: async () =>
          status === 'active'
            ? [
                {
                  id: 1,
                  name: '房子装修',
                  description: '完成新家装修',
                  status: 'active',
                  template: 'blank',
                  node_count: emptyTree ? 0 : 2,
                  created_at: '',
                },
              ]
            : [],
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
    expect(screen.getByRole('link', { name: /进入知识空间/ })).toHaveAttribute(
      'href',
      '/projects/1?view=directory',
    )
    expect(screen.getByRole('group', { name: '项目状态' })).toBeInTheDocument()
  })

  it('通过兼容 URL 渲染知识空间并默认选择第一个根节点', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('heading', { name: '知识空间' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '装修准备' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '需求确认' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '根节点' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '创建根节点' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '与 AI 共创目录' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '这里还没有正式知识' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '装修准备' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.queryByText('思维导图')).not.toBeInTheDocument()
    expect(screen.queryByText('正式知识', { exact: true })).not.toBeInTheDocument()
  })

  it('切换目录节点后同步更新当前范围', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    await userEvent.click(await screen.findByRole('button', { name: '需求确认' }))

    expect(screen.getByRole('button', { name: '需求确认' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByText('装修准备 / 需求确认')).toBeInTheDocument()
  })

  it('空知识空间保留两个平等的目录起点', async () => {
    mockProjectApi({ emptyTree: true })
    renderProject('/projects/1?view=directory')

    expect(await screen.findByRole('heading', { name: '从空目录开始' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '手动创建' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '与 AI 共创目录' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '这里还没有正式知识' })).not.toBeInTheDocument()
  })

  it('AI 共创入口发起目录起草并展示澄清问卷', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    await userEvent.click(await screen.findByRole('button', { name: '与 AI 共创目录' }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByText('目录按什么维度组织？')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '提交并生成' })).toBeInTheDocument()
  })

  it('目录节点删除仍要求二次确认并说明子树影响', async () => {
    mockProjectApi()
    renderProject('/projects/1?view=directory')

    await userEvent.click(await screen.findByRole('button', { name: '装修准备 更多操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除节点' }))

    expect(screen.getByRole('dialog')).toHaveTextContent('将删除「装修准备」及其全部子节点')
    expect(screen.getByRole('button', { name: '确认删除' })).toBeEnabled()
  })
})
