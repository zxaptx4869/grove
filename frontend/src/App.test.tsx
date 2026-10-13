import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const initialWidth = window.innerWidth

function resize(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true })
  window.dispatchEvent(new Event('resize'))
}

function open(path: string) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('公开介绍与桌面业务边界', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    resize(initialWidth)
  })

  it.each([
    [390, '/login'],
    [1023, '/login'],
    [390, '/login/'],
    [390, '/'],
  ])('%ipx 访问 %s 只读介绍，不挂载表单或查询业务数据', async (width, path) => {
    resize(width)
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    open(path)
    expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('让零散知识找得到')
    expect(screen.queryByLabelText('账号')).not.toBeInTheDocument()
    expect(screen.getByText('在电脑端登录，开始整理')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each(['/projects', '/projects/1', '/agent', '/register'])(
    '1023px 下 %s 继续阻断业务与认证',
    (path) => {
      resize(1023)
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      open(path)
      expect(screen.getByRole('heading', { name: '请在电脑端打开 Grove' })).toBeInTheDocument()
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )

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
})
