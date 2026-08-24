import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
})
