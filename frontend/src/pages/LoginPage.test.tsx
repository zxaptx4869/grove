import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('渲染登录表单且无报错', () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByRole('heading', { name: '登录' })).toBeInTheDocument()
    expect(screen.getByLabelText('账号')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      '让收藏的知识用得上，让想学的领域有方向。',
    )
  })

  it('登录失败时在表单附近显示接口错误', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: async () => ({ detail: '账号或密码错误' }),
      }),
    )
    const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await userEvent.type(screen.getByLabelText('账号'), 'wrong_user')
    await userEvent.type(screen.getByLabelText('密码'), 'wrong_password')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码错误')
  })

  it('成功提交真实凭据，等待时阻止重复提交，成功后进入工作台入口', async () => {
    let resolveResponse!: (response: Response) => void
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve
        }),
    )
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<h1>项目工作台</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('账号'), 'grove_user')
    await userEvent.type(screen.getByLabelText('密码'), 'test_password')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(screen.getByRole('button', { name: '登录中…' })).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/auth/login',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ username: 'grove_user', password: 'test_password' }),
      }),
    )
    await act(async () =>
      resolveResponse(
        new Response(JSON.stringify({ id: 1, username: 'grove_user' }), { status: 200 }),
      ),
    )
    expect(await screen.findByRole('heading', { name: '项目工作台' })).toBeInTheDocument()
  })

  it('切换 AI 能力仅展示说明，保持候选、目录草稿与回答的语义边界', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(
      within(screen.getByRole('tabpanel', { name: 'AI 提取与归属推荐' })).getByText(
        'AI 候选 · 待确认',
      ),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'AI 目录共创' }))
    const directory = screen.getByRole('tabpanel', { name: 'AI 目录共创' })
    expect(within(directory).getByText('AI 目录草稿 · 待确认')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'AI 目录共创' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await userEvent.click(screen.getByRole('tab', { name: '知识 Agent 协助' }))
    expect(screen.getByRole('tabpanel', { name: '知识 Agent 协助' })).toHaveTextContent('回答示例')
    expect(
      within(screen.getByRole('tabpanel', { name: '知识 Agent 协助' })).getByText('示例'),
    ).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('截图可用键盘切换、放大，关闭后焦点回到原入口', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const trigger = screen.getByRole('button', { name: '放大查看知识对话截图' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: '知识对话' })
    expect(within(dialog).getByRole('img')).toHaveAttribute(
      'alt',
      expect.stringContaining('App 知识 Agent'),
    )
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    await userEvent.click(screen.getByRole('tab', { name: '知识 Agent' }))
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: '确认台' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('button', { name: '放大查看确认台截图' })).toBeInTheDocument()
    await userEvent.keyboard('{Home}{ArrowRight}')
    expect(screen.getByRole('tab', { name: '收集箱' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('键盘切换标签时同步焦点、选中态和对应示例', async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.click(screen.getByRole('tab', { name: 'AI 提取与归属推荐' }))
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'AI 目录共创' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'AI 目录共创' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tabpanel', { name: 'AI 目录共创' })).toHaveTextContent('新房装修')
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: '知识 Agent 协助' })).toHaveFocus()
    expect(screen.getByRole('tabpanel', { name: '知识 Agent 协助' })).toHaveTextContent('回答示例')
    await userEvent.keyboard('{Home}')
    expect(screen.getByRole('tab', { name: 'AI 提取与归属推荐' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('tabpanel', { name: 'AI 提取与归属推荐' })).toHaveFocus()
  })
})
