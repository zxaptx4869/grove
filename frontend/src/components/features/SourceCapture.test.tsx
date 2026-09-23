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

describe('SourceCapture 采集幂等键', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  function stubCaptureApi(keys: string[]) {
    let failFirst = true
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/sources' && init?.method === 'POST') {
          keys.push(String((init.body as FormData).get('capture_key')))
          if (failFirst) {
            failFirst = false
            return Promise.resolve({
              ok: false,
              status: 500,
              json: async () => ({ detail: '网络错误' }),
            })
          }
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 1 }) })
      }),
    )
  }

  it('失败重试复用同一个键，成功后的新采集使用新键', async () => {
    URL.createObjectURL = vi.fn(() => 'blob:mock')
    URL.revokeObjectURL = vi.fn()
    const keys: string[] = []
    stubCaptureApi(keys)
    const { container } = renderCapture()
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    await userEvent.upload(input, [makeFile('a.png')])
    await userEvent.click(screen.getByRole('button', { name: '采集并处理' }))
    await waitFor(() => expect(screen.getByText('网络错误')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: '采集并处理' }))
    await waitFor(() => expect(keys).toHaveLength(2))

    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])

    // 成功后重新选择图片属于新的一次采集，必须换新键
    await userEvent.upload(input, [makeFile('b.png')])
    await userEvent.click(screen.getByRole('button', { name: '采集并处理' }))
    await waitFor(() => expect(keys).toHaveLength(3))

    expect(keys[2]).not.toBe(keys[1])
  })
})
