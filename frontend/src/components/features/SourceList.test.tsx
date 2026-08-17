import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SourceList } from './SourceList'
import type { SourcePayload } from '@/lib/api'

const source: SourcePayload = {
  id: 1,
  title: '闭水试验',
  note: null,
  project_id: null,
  status: 'done',
  recommended_project_id: 2,
  project_recommendation_reason: '内容与装修项目相关',
  created_at: '',
  updated_at: '',
  attachments: [
    {
      id: 1,
      kind: 'text',
      position: 0,
      mime_type: null,
      file_name: null,
      text_content: '闭水试验至少持续 24 小时',
    },
  ],
}

describe('SourceList', () => {
  it('展示 AI 项目推荐并支持采用', async () => {
    const onAssign = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SourceList
          sources={[source]}
          projects={[{ id: 2, name: '房子装修' }]}
          onAssign={onAssign}
          onTrigger={vi.fn()}
          onDelete={vi.fn()}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByText(/AI 推荐项目：房子装修/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '采用' }))
    expect(onAssign).toHaveBeenCalledWith(1, 2)
  })
})
