import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BatchReviewView } from './BatchReviewView'

function renderView(onReviewCandidate = vi.fn()) {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <BatchReviewView projectId={7} onReviewCandidate={onReviewCandidate} />
    </QueryClientProvider>,
  )
  return onReviewCandidate
}

function candidatePayload(id: number, sourceId: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    source_id: sourceId,
    candidate_kind: 'recommended',
    title: `候选 ${id}`,
    content: '候选内容',
    main_type: 'knowledge',
    info_nature: 'fact',
    applicable_condition: null,
    note: null,
    evidence: [{ attachment_id: 9, quote: '证据片段' }],
    reason: null,
    risk_flags: [],
    status: 'pending',
    recommended_node_id: 10,
    node_alternatives: [],
    node_reason: null,
    routing_status: 'recommended',
    new_node_suggestion: null,
    relation_status: 'new',
    relation_target_entry_id: null,
    relation_target_entry_title: null,
    relation_target_entry_node_name: null,
    relation_reason: null,
    revision_draft: null,
    source_title: '来源标题',
    source_note: '来源说明',
    review_band: 'quick',
    user_node_id: null,
    ...overrides,
  }
}

describe('BatchReviewView', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('按推荐目录分组并展示精审分流', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects/7/tree') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 10,
                name: '求职',
                description: null,
                position: 0,
                children: [
                  {
                    id: 11,
                    name: '经验',
                    description: null,
                    position: 0,
                    children: [],
                  },
                ],
              },
            ],
          })
        }
        if (url.pathname === '/api/projects/7/review/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              candidatePayload(1, 5, { recommended_node_id: 11 }),
              candidatePayload(2, 6, { recommended_node_id: 11, title: '候选 2' }),
              candidatePayload(3, 7, {
                risk_flags: ['高风险'],
                review_band: 'detailed',
                routing_status: 'recommended',
              }),
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderView()

    expect(await screen.findByText('求职 / 经验')).toBeInTheDocument()
    expect(screen.getByText('推荐明确 · 2')).toBeInTheDocument()
    expect(screen.getByText('已分流精审')).toBeInTheDocument()
    expect(screen.getByText('1 条不参与快审')).toBeInTheDocument()
    expect(screen.getByText('高风险 · 来自：来源标题')).toBeInTheDocument()
  })

  it('批量确认调用项目级批量决策接口', async () => {
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
        if (url.pathname === '/api/projects/7/tree') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 10, name: '求职', description: null, position: 0, children: [] },
            ],
          })
        }
        if (url.pathname === '/api/projects/7/review/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [candidatePayload(1, 5), candidatePayload(2, 6)],
          })
        }
        if (
          url.pathname === '/api/projects/7/review/candidates/batch-decision' &&
          init?.method === 'POST'
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { candidate_id: 1, status: 'confirmed', error: null },
              { candidate_id: 2, status: 'confirmed', error: null },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderView()

    expect(await screen.findByText('推荐明确 · 2')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('选择「候选 1」'))
    await userEvent.click(screen.getByLabelText('选择「候选 2」'))
    await userEvent.click(screen.getByRole('button', { name: '批量采纳' }))

    await waitFor(() => {
      expect(
        calls.some(
          (call) =>
            call.method === 'POST' &&
            call.path === '/api/projects/7/review/candidates/batch-decision' &&
            call.body?.includes('confirm'),
        ),
      ).toBe(true)
    })
  })

  it('精审按钮触发逐条审阅回调', async () => {
    const onReviewCandidate = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects/7/tree') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/projects/7/review/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              candidatePayload(3, 7, {
                risk_flags: ['高风险'],
                review_band: 'detailed',
              }),
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )
    renderView(onReviewCandidate)

    expect(await screen.findByText('已分流精审')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '精审' }))

    expect(onReviewCandidate).toHaveBeenCalledWith(3, 7)
  })

  it('关系建议进入精审并展示原因', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects/7/tree') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/projects/7/review/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              candidatePayload(3, 7, {
                review_band: 'detailed',
                relation_status: 'supplement',
                relation_target_entry_id: 20,
                relation_target_entry_title: '闭水试验规范',
                relation_reason: '补充参数',
              }),
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )
    renderView()

    expect(await screen.findByText('可以补充 · 补充参数 · 来自：来源标题')).toBeInTheDocument()
  })

  it('修改目录确认后持久化并清空勾选', async () => {
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
        if (url.pathname === '/api/projects/7/tree') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 10, name: '施工', description: null, position: 0, entry_count: 0, children: [] },
            ],
          })
        }
        if (url.pathname === '/api/projects/7/review/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [candidatePayload(1, 5)],
          })
        }
        if (
          url.pathname === '/api/projects/7/review/candidates/batch-decision' &&
          init?.method === 'POST'
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => [{ candidate_id: 1, status: 'confirmed', error: null }],
          })
        }
        if (
          url.pathname === '/api/projects/7/review/candidates/batch-update-directory' &&
          init?.method === 'POST'
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({ updated: 1 }),
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderView()

    expect(await screen.findByText('推荐明确 · 1')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('选择「候选 1」'))
    await userEvent.click(screen.getByRole('button', { name: '修改目录' }))
    await userEvent.click(await screen.findByRole('button', { name: '统一归档目录' }))
    await userEvent.click(await screen.findByRole('option', { name: /施工/ }))
    await userEvent.click(screen.getByRole('button', { name: '确认' }))

    await waitFor(() => {
      expect(
        calls.some(
          (item) =>
            item.method === 'POST' &&
            item.path === '/api/projects/7/review/candidates/batch-update-directory' &&
            item.body?.includes('"node_id":10'),
        ),
      ).toBe(true)
    })
    expect(
      screen.getByRole('button', { name: '修改目录' }),
    ).toBeDisabled()
  })
})
