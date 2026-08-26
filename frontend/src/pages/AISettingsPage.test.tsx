import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AISettingsPage } from './AISettingsPage'

function renderPage() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AISettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function settingsPayload() {
  return {
    text_provider: 'deepseek',
    text_model: 'deepseek-chat',
    text_configured: false,
    text_key_tail: null,
    text_available: false,
    vision_provider: 'doubao',
    vision_model: 'doubao-seed-2-0-lite-260428',
    vision_configured: false,
    vision_key_tail: null,
    vision_available: false,
    embedding_provider: 'doubao',
    embedding_model: 'doubao-embedding-vision-251215',
    embedding_configured: false,
    embedding_key_tail: null,
    embedding_available: false,
  }
}

describe('AISettingsPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('展示文本与视觉模型配置卡片', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({ ok: true, json: async () => settingsPayload() }),
      ),
    )

    renderPage()

    expect(await screen.findByRole('heading', { name: '模型设置' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '文本模型' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '视觉模型' })).toBeInTheDocument()
    expect(screen.getByText('deepseek-chat', { exact: false })).toBeInTheDocument()
    expect(
      screen.getByText('doubao-seed-2-0-lite-260428', { exact: false }),
    ).toBeInTheDocument()
  })

  it('展示语义模型卡片并复用视觉密钥', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({ ok: true, json: async () => settingsPayload() }),
      ),
    )

    renderPage()

    expect(
      await screen.findByRole('heading', { name: '语义模型（Embedding）' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('doubao-embedding-vision-251215', { exact: false }),
    ).toBeInTheDocument()
    expect(screen.getByText(/无需单独填写 API Key/)).toBeInTheDocument()
  })

  it('保存语义模型会调用 PUT /embedding', async () => {
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
        return Promise.resolve({ ok: true, json: async () => settingsPayload() })
      }),
    )

    renderPage()
    await screen.findByRole('heading', { name: '模型设置' })
    const modelInputs = await screen.findAllByLabelText('模型名（可选）')
    await userEvent.clear(modelInputs[2])
    await userEvent.type(modelInputs[2], 'doubao-embedding-vision-251215')
    await userEvent.click(screen.getAllByRole('button', { name: '保存' })[2])

    expect(
      calls.some(
        (call) =>
          call.method === 'PUT' && call.path === '/api/settings/ai/embedding',
      ),
    ).toBe(true)
  })

  it('保存文本密钥会调用 PUT 接口', async () => {
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
        return Promise.resolve({ ok: true, json: async () => settingsPayload() })
      }),
    )

    renderPage()
    await screen.findByRole('heading', { name: '模型设置' })
    const keyInputs = await screen.findAllByLabelText('API Key')
    await userEvent.type(keyInputs[0], 'sk-abcdefgh')
    await userEvent.click(screen.getAllByRole('button', { name: '保存' })[0])

    expect(
      calls.some(
        (call) =>
          call.method === 'PUT' &&
          call.path === '/api/settings/ai/text' &&
          call.body?.includes('sk-abcdefgh'),
      ),
    ).toBe(true)
  })

  it('测试文本连接会调用 test 接口', async () => {
    const calls: Array<{ method: string; path: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        return Promise.resolve({
          ok: true,
          json: async () =>
            url.pathname.endsWith('/test') ? { ok: true, message: 'ok' } : settingsPayload(),
        })
      }),
    )

    renderPage()
    await screen.findByRole('heading', { name: '模型设置' })
    const testButtons = await screen.findAllByRole('button', { name: '测试连接' })
    await userEvent.click(testButtons[0])

    expect(
      calls.some(
        (call) => call.method === 'POST' && call.path === '/api/settings/ai/text/test',
      ),
    ).toBe(true)
  })
})
