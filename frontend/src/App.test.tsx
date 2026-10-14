import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const initialWidth = window.innerWidth

function resize(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true })
  window.dispatchEvent(new Event('resize'))
}

function HistoryControls() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  return (
    <>
      <output aria-label="测试当前地址">{pathname}</output>
      <button onClick={() => navigate(-1)}>测试后退</button>
      <button onClick={() => navigate(1)}>测试前进</button>
    </>
  )
}

function open(path: string, history = false) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
        {history ? <HistoryControls /> : null}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('公开介绍与桌面业务边界', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    act(() => resize(initialWidth))
  })

  it.each([
    [390, '/login'],
    [1023, '/login'],
    [390, '/login/'],
    [390, '/register'],
    [1023, '/register/'],
    [390, '/'],
  ])('%ipx 访问 %s 只读介绍，不挂载表单或查询业务数据', async (width, path) => {
    resize(width)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    open(path)
    const introduction = await screen.findByRole('main')
    expect(within(introduction).getByRole('heading', { level: 1 })).toBeInTheDocument()
    expect(within(introduction).getAllByRole('heading', { level: 2 }).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('账号')).not.toBeInTheDocument()
    expect(screen.getByText('在电脑端登录，开始整理')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each(['/projects', '/projects/1', '/agent'])('1023px 下 %s 继续阻断业务工作台', (path) => {
    resize(1023)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    open(path)
    expect(screen.getByRole('heading', { name: '请在电脑端打开 Grove' })).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('1024px 展示表单，缩窄后移除，再扩大时恢复', async () => {
    resize(1024)
    vi.stubGlobal('fetch', vi.fn())
    open('/login')
    expect(await screen.findByLabelText('账号')).toBeInTheDocument()
    act(() => resize(1023))
    expect(screen.queryByLabelText('账号')).not.toBeInTheDocument()
    act(() => resize(1280))
    expect(screen.getByLabelText('账号')).toBeInTheDocument()
  })

  it('1024px 未登录业务入口执行真实认证守卫，再进入公开介绍', async () => {
    resize(1024)
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ detail: '未登录' }), { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    open('/projects')
    expect(await screen.findByLabelText('账号')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/me',
      expect.objectContaining({ credentials: 'include' }),
    )
  })

  it('登录注册在同一介绍页切换，并保留当前 AI 示例', async () => {
    resize(1440)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    open('/login')
    await screen.findByLabelText('账号')
    await userEvent.click(screen.getByRole('tab', { name: 'AI 目录共创' }))
    await userEvent.click(screen.getByRole('link', { name: '去注册' }))
    expect(screen.getByLabelText('确认密码')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'AI 目录共创' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await userEvent.click(screen.getByRole('link', { name: '去登录' }))
    expect(screen.queryByLabelText('确认密码')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'AI 目录共创' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('认证底部链接与浏览器历史同步，支持键盘激活', async () => {
    resize(1440)
    vi.stubGlobal('fetch', vi.fn())
    open('/login', true)
    await screen.findByRole('heading', { name: '登录' })
    await userEvent.click(screen.getByRole('link', { name: '去注册' }))
    expect(screen.getByLabelText('测试当前地址')).toHaveTextContent('/register')
    await userEvent.click(screen.getByRole('button', { name: '测试后退' }))
    expect(screen.getByLabelText('测试当前地址')).toHaveTextContent('/login')
    expect(screen.getByRole('heading', { name: '登录' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '测试前进' }))
    expect(screen.getByLabelText('测试当前地址')).toHaveTextContent('/register')
    screen.getByRole('link', { name: '去登录' }).focus()
    await userEvent.keyboard('{Enter}')
    expect(screen.getByLabelText('测试当前地址')).toHaveTextContent('/login')
    expect(screen.queryByLabelText('确认密码')).not.toBeInTheDocument()
  })
})
