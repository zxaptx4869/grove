import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SourceDetailDialog } from './SourceDetailDialog'

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function renderDialog() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <SourceDetailDialog
        sourceId={1}
        open
        onOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

const BASE = {
  id: 0,
  source_id: 1,
  candidate_kind: 'recommended',
  title: '闭水试验',
  content: '闭水试验至少 24 小时',
  main_type: 'knowledge',
  info_nature: 'fact',
  applicable_condition: null,
  note: null,
  evidence: [],
  reason: null,
  risk_flags: [],
  recommended_node_id: null,
  node_alternatives: [],
  node_reason: null,
  routing_status: 'pending',
  new_node_suggestion: null,
  relation_status: 'pending',
  relation_target_entry_id: null,
  relation_target_entry_title: null,
  relation_target_entry_node_name: null,
  relation_reason: null,
  revision_draft: null,
}

describe('SourceDetailDialog', () => {
  it('展示候选的决策状态徽标', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/candidates')) {
          return ok([
            { ...BASE, id: 1, status: 'pending' },
            { ...BASE, id: 2, status: 'confirmed' },
            { ...BASE, id: 3, status: 'rejected' },
          ])
        }
        if (url.endsWith('/api/sources/1')) {
          return ok({
            id: 1,
            title: '来源',
            note: null,
            project_id: 1,
            status: 'pending',
            recommended_project_id: null,
            project_recommendation_reason: null,
            created_at: '',
            updated_at: '',
            attachments: [],
            project_locked: false,
            evidence_entry_count: 0,
            pending_candidate_count: 3,
            candidate_count: 3,
          })
        }
        return ok({})
      }),
    )

    renderDialog()

    expect(await screen.findByText('待确认')).toBeInTheDocument()
    expect(screen.getByText('已确认')).toBeInTheDocument()
    expect(screen.getByText('已拒绝')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('创建时间按 UTC 解析服务端不带时区的时间串', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        // 元信息块只在有候选时渲染
        if (url.includes('/candidates')) return ok([{ ...BASE, id: 1, status: 'pending' }])
        if (url.endsWith('/api/sources/1')) {
          return ok({
            id: 1,
            title: '来源',
            note: null,
            project_id: null,
            status: 'done',
            recommended_project_id: null,
            project_recommendation_reason: null,
            created_at: '2026-09-29T07:23:51',
            updated_at: '2026-09-29T07:23:51',
            attachments: [],
            project_locked: false,
            evidence_entry_count: 0,
            pending_candidate_count: 0,
            candidate_count: 0,
          })
        }
        return ok({})
      }),
    )

    renderDialog()

    // 07:23:51Z 在东八区是 15:23:51：不补 Z 会按本地时间解析，整整差 8 小时
    const expected = new Date('2026-09-29T07:23:51Z').toLocaleString('zh-CN', { hour12: false })
    expect(await screen.findByText(expected)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('创建时间已带偏移时不二次偏移', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/candidates')) return ok([{ ...BASE, id: 1, status: 'pending' }])
        if (url.endsWith('/api/sources/1')) {
          return ok({
            id: 1,
            title: '来源',
            note: null,
            project_id: null,
            status: 'done',
            recommended_project_id: null,
            project_recommendation_reason: null,
            created_at: '2026-09-29T07:23:51Z',
            updated_at: '2026-09-29T07:23:51Z',
            attachments: [],
            project_locked: false,
            evidence_entry_count: 0,
            pending_candidate_count: 0,
            candidate_count: 0,
          })
        }
        return ok({})
      }),
    )

    renderDialog()

    const expected = new Date('2026-09-29T07:23:51Z').toLocaleString('zh-CN', { hour12: false })
    expect(await screen.findByText(expected)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('处理未启动的来源显示说明并可重试处理', async () => {
    const calls: Array<{ method: string; path: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        if (url.pathname === '/api/sources/1/candidates') return ok([])
        if (url.pathname === '/api/sources/1/process') {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: async () => ({ detail: '来源正在处理中' }),
          })
        }
        if (url.pathname === '/api/sources/1') {
          return ok({
            id: 1,
            title: '来源',
            note: null,
            project_id: null,
            status: 'waiting',
            recommended_project_id: null,
            project_recommendation_reason: null,
            created_at: '2026-09-29T07:23:51',
            updated_at: '2026-09-29T07:23:51',
            attachments: [],
            project_locked: false,
            evidence_entry_count: 0,
            pending_candidate_count: 0,
            candidate_count: 0,
            has_processing_task: false,
          })
        }
        return ok({})
      }),
    )

    renderDialog()

    expect(await screen.findByText('处理未启动')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重试处理' }))

    // 409 视为状态本身正常：只触发刷新，不把弹窗变成失败态
    await waitFor(() =>
      expect(
        calls.some((call) => call.method === 'POST' && call.path === '/api/sources/1/process'),
      ).toBe(true),
    )
    expect(screen.getByText('处理未启动')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('等待处理但有任务的来源不显示处理未启动', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/candidates')) return ok([])
        if (url.endsWith('/api/sources/1')) {
          return ok({
            id: 1,
            title: '来源',
            note: null,
            project_id: null,
            status: 'waiting',
            recommended_project_id: null,
            project_recommendation_reason: null,
            created_at: '2026-09-29T07:23:51',
            updated_at: '2026-09-29T07:23:51',
            attachments: [],
            project_locked: false,
            evidence_entry_count: 0,
            pending_candidate_count: 0,
            candidate_count: 0,
            has_processing_task: true,
          })
        }
        return ok({})
      }),
    )

    renderDialog()

    expect(await screen.findByText('还没有候选')).toBeInTheDocument()
    expect(screen.queryByText('处理未启动')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重试处理' })).not.toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
