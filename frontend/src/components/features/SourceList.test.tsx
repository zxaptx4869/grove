import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SourceList } from './SourceList'
import type { SourcePayload } from '@/lib/api'

function baseSource(overrides: Partial<SourcePayload>): SourcePayload {
  return {
    id: 1,
    title: '测试来源',
    note: null,
    project_id: null,
    status: 'waiting',
    recommended_project_id: null,
    project_recommendation_reason: null,
    created_at: '',
    updated_at: '',
    project_locked: false,
    evidence_entry_count: 0,
    attachments: [],
    ...overrides,
  }
}

function renderList(source: SourcePayload, onDelete = vi.fn()) {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <SourceList
        sources={[source]}
        projects={[]}
        onAssign={vi.fn()}
        onTrigger={vi.fn()}
        onDelete={onDelete}
      />
    </QueryClientProvider>,
  )
}

describe('SourceList', () => {
  it('已处理完成的来源不展示改归属与删除', () => {
    renderList(baseSource({ status: 'done', project_locked: true, evidence_entry_count: 1 }))

    expect(screen.queryByLabelText('测试来源 所属项目')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 测试来源' })).not.toBeInTheDocument()
  })

  it('未处理来源可改归属并直接删除', async () => {
    const onDelete = vi.fn()
    renderList(baseSource({}), onDelete)

    expect(screen.getByLabelText('测试来源 所属项目')).not.toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))

    expect(onDelete).toHaveBeenCalledWith(1)
  })
})
