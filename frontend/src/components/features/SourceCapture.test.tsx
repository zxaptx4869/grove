import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SourceCapture } from './SourceCapture'

function makeFile(name: string) {
  return new File(['fake-image'], name, { type: 'image/png' })
}

function renderCapture() {
  const queryClient = new QueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <SourceCapture projects={[]} onCreated={vi.fn()} />
    </QueryClientProvider>,
  )
}

describe('SourceCapture 缩略图', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('选择图片后显示缩略图并可逐张移除', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
    URL.revokeObjectURL = vi.fn()
    const { container } = renderCapture()
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    await userEvent.upload(input, [makeFile('a.png'), makeFile('b.png')])

    expect(screen.getByText('已选择 2 张图片（最多 5 张）')).toBeInTheDocument()
    expect(screen.getByAltText('a.png')).toBeInTheDocument()
    expect(screen.getByAltText('b.png')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '移除第 1 张图片' }))

    expect(screen.queryByAltText('a.png')).not.toBeInTheDocument()
    expect(screen.getByAltText('b.png')).toBeInTheDocument()
    expect(screen.getByText('已选择 1 张图片（最多 5 张）')).toBeInTheDocument()
  })

  it('图片与附加文字可同时提交', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
    URL.revokeObjectURL = vi.fn()
    let body: FormData | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/sources' && init?.method === 'POST') {
          body = init.body as FormData
        }
        return Promise.resolve({ ok: true, json: async () => ({ id: 1 }) })
      }),
    )
    const { container } = renderCapture()
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    await userEvent.upload(input, [makeFile('a.png')])
    await userEvent.type(screen.getByLabelText('附加文字内容（可选）'), '说明文字')
    await userEvent.click(screen.getByRole('button', { name: '采集并处理' }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body!.getAll('files')).toHaveLength(1)
    expect(body!.get('text')).toBe('说明文字')
    vi.unstubAllGlobals()
  })
})
