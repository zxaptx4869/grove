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
  it('被正式知识引用的来源禁用改归属', () => {
    renderList(baseSource({ project_locked: true }))

    expect(screen.getByLabelText('测试来源 所属项目')).toBeDisabled()
  })

  it('有证据引用的来源删除需二次确认', async () => {
    const onDelete = vi.fn()
    renderList(baseSource({ evidence_entry_count: 2 }), onDelete)

    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))

    expect(await screen.findByText('删除来源？')).toBeInTheDocument()
    expect(screen.getByText(/被 2 条正式知识引用/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('无证据引用直接删除', async () => {
    const onDelete = vi.fn()
    renderList(baseSource({}), onDelete)

    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))

    expect(onDelete).toHaveBeenCalledWith(1)
  })
})
