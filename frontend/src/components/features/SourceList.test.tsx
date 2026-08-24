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
    pending_candidate_count: 0,
    candidate_count: 0,
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
  it('提取完成且有待确认候选：显示副徽标，删除需确认', async () => {
    const onDelete = vi.fn()
    renderList(
      baseSource({ status: 'done', pending_candidate_count: 2, candidate_count: 2 }),
      onDelete,
    )

    expect(screen.getByText('提取完成')).toBeInTheDocument()
    expect(screen.getByText('待确认 2 条')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '候选' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))

    expect(await screen.findByText('删除来源？')).toBeInTheDocument()
    expect(screen.getByText(/有 2 条待确认候选/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))
    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('已产生正式知识的来源：显示正式知识副徽标且不展示操作', () => {
    renderList(
      baseSource({
        status: 'done',
        project_locked: true,
        evidence_entry_count: 1,
        pending_candidate_count: 0,
        candidate_count: 1,
      }),
    )

    expect(screen.getByText('1 条正式知识')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '候选' })).toBeInTheDocument()
    expect(screen.queryByLabelText('测试来源 所属项目')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 测试来源' })).not.toBeInTheDocument()
  })

  it('部分确认的来源显示部分确认并锁定', () => {
    renderList(
      baseSource({
        status: 'done',
        project_locked: true,
        evidence_entry_count: 1,
        pending_candidate_count: 1,
        candidate_count: 2,
      }),
    )

    expect(screen.getByText('部分确认')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '候选' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 测试来源' })).not.toBeInTheDocument()
  })

  it('全部拒绝已处理的来源可操作', async () => {
    const onDelete = vi.fn()
    renderList(
      baseSource({
        status: 'done',
        pending_candidate_count: 0,
        evidence_entry_count: 0,
        candidate_count: 1,
      }),
      onDelete,
    )

    expect(screen.getByText('已处理')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '候选' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))
    expect(onDelete).toHaveBeenCalledWith(1)
  })

  it('无候选的虚拟来源（如 AI 修订）不显示候选按钮', () => {
    renderList(
      baseSource({
        status: 'done',
        project_locked: true,
        evidence_entry_count: 1,
        pending_candidate_count: 0,
        candidate_count: 0,
      }),
    )

    expect(screen.getByText('1 条正式知识')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '候选' })).not.toBeInTheDocument()
  })

  it('处理中的来源不展示改归属与删除', () => {
    renderList(baseSource({ status: 'processing' }))

    expect(screen.queryByLabelText('测试来源 所属项目')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除 测试来源' })).not.toBeInTheDocument()
  })

  it('未处理来源可改归属并直接删除', async () => {
    const onDelete = vi.fn()
    renderList(baseSource({}), onDelete)

    expect(screen.getByLabelText('测试来源 所属项目')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '删除 测试来源' }))
    expect(onDelete).toHaveBeenCalledWith(1)
  })
})
