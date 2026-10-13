import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RegisterPage } from './RegisterPage'

describe('RegisterPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('渲染注册表单且无报错', () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByRole('heading', { name: '欢迎来到 Grove' })).toBeInTheDocument()
    expect(screen.getByLabelText('账号')).toBeInTheDocument()
    expect(screen.getByLabelText('密码')).toBeInTheDocument()
    expect(screen.getByLabelText('确认密码')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '注册' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: '注册' })).toBeInTheDocument()
  })

  it('密码不一致时保留注册校验，不提交请求', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/register']}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('账号'), 'grove_user')
    await userEvent.type(screen.getByLabelText('密码'), 'test_password')
    await userEvent.type(screen.getByLabelText('确认密码'), 'different_password')
    await userEvent.click(screen.getByRole('button', { name: '注册' }))
    expect(await screen.findByText('两次输入的密码不一致')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('重复账号错误保留表单并恢复切换，切回登录不带入注册错误', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({ detail: '账号已存在' }), { status: 409 })),
    )
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
      >
        <MemoryRouter initialEntries={['/register']}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('账号'), 'existing_user')
    await userEvent.type(screen.getByLabelText('密码'), 'test_password')
    await userEvent.type(screen.getByLabelText('确认密码'), 'test_password')
    await userEvent.click(screen.getByRole('button', { name: '注册' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('账号已存在')
    expect(screen.getByLabelText('账号')).toHaveValue('existing_user')
    expect(screen.getByRole('tab', { name: '登录' })).toBeEnabled()
    await userEvent.click(screen.getByRole('tab', { name: '登录' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('确认密码')).not.toBeInTheDocument()
  })

  it('注册只发送账号密码，等待时禁止切换，成功后自动进入工作台', async () => {
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
        <MemoryRouter initialEntries={['/register']}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/" element={<h1>项目工作台</h1>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await userEvent.type(screen.getByLabelText('账号'), 'new_user')
    await userEvent.type(screen.getByLabelText('密码'), 'test_password')
    await userEvent.type(screen.getByLabelText('确认密码'), 'test_password')
    await userEvent.click(screen.getByRole('button', { name: '注册' }))
    expect(screen.getByRole('button', { name: '注册中…' })).toBeDisabled()
    expect(screen.getByRole('tab', { name: '登录' })).toBeDisabled()
    expect(screen.getByRole('tab', { name: '注册' })).toBeDisabled()
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith(
      '/api/auth/register',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ username: 'new_user', password: 'test_password' }),
      }),
    )
    await act(async () =>
      resolveResponse(
        new Response(JSON.stringify({ id: 2, username: 'new_user' }), { status: 201 }),
      ),
    )
    expect(await screen.findByRole('heading', { name: '项目工作台' })).toBeInTheDocument()
  })
})
