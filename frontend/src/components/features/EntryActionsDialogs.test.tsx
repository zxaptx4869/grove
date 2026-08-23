import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { EntryEditDialog } from '@/components/features/EntryEditDialog'
import { EntryVersionHistoryDialog } from '@/components/features/EntryVersionHistoryDialog'
import { RevisionSuggestionDialog } from '@/components/features/RevisionSuggestionDialog'
import type { EntryPayload } from '@/lib/api'

const ENTRY: EntryPayload = {
  id: 1,
  project_id: 10,
  node_id: 20,
  node_name: '施工',
  title: '闭水试验时长',
  content: '闭水试验至少持续 24 小时',
  main_type: 'knowledge',
  info_nature: 'fact',
  applicable_condition: null,
  note: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-02T00:00:00Z',
  evidences: [],
}

function renderWithClient(ui: React.ReactNode) {
  const queryClient = new QueryClient()
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

function jsonResponse(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

describe('EntryEditDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('编辑字段并保存', async () => {
    const user = userEvent.setup()
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
        return jsonResponse({
          ...ENTRY,
          title: '闭水试验时长（修订）',
        })
      }),
    )
    const onSaved = vi.fn()
    renderWithClient(
      <EntryEditDialog
        open
        entry={ENTRY}
        nodes={[{ id: 20, name: '施工', description: null, position: 0, entry_count: 1, children: [] }]}
        onOpenChange={vi.fn()}
        onSaved={onSaved}
      />,
    )

    const titleInput = screen.getByLabelText('标题')
    await user.clear(titleInput)
    await user.type(titleInput, '闭水试验时长（修订）')
    await user.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const patchCall = calls.find((call) => call.method === 'PATCH')
    expect(patchCall?.path).toBe('/api/entries/1')
    expect(JSON.parse(patchCall!.body!).title).toBe('闭水试验时长（修订）')
  })
})

describe('EntryVersionHistoryDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('列出版本、查看快照并两步确认恢复', async () => {
    const user = userEvent.setup()
    const calls: Array<{ method: string; path: string }> = []
    const versions = [
      {
        id: 11,
        version_number: 2,
        title: '闭水试验时长（修订）',
        content: '闭水试验至少持续 24 小时，观察渗漏',
        main_type: 'knowledge',
        info_nature: 'fact',
        applicable_condition: null,
        note: null,
        node_id: 20,
        node_name: '施工',
        change_type: 'edited',
        change_summary: '补充观察要点',
        created_at: '2026-08-03T00:00:00Z',
      },
      {
        id: 10,
        version_number: 1,
        title: '闭水试验时长',
        content: '闭水试验至少持续 24 小时',
        main_type: 'knowledge',
        info_nature: 'fact',
        applicable_condition: null,
        note: null,
        node_id: 20,
        node_name: '施工',
        change_type: 'created',
        change_summary: null,
        created_at: '2026-08-01T00:00:00Z',
      },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({ method: init?.method ?? 'GET', path: url.pathname })
        if (url.pathname === '/api/entries/1/versions') return jsonResponse(versions)
        return jsonResponse(ENTRY)
      }),
    )
    const onRestored = vi.fn()
    renderWithClient(
      <EntryVersionHistoryDialog
        open
        entry={ENTRY}
        onOpenChange={vi.fn()}
        onRestored={onRestored}
      />,
    )

    await screen.findByText('v2')
    await user.click(screen.getByText('v1'))
    await waitFor(() => expect(screen.getByText('闭水试验时长')).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: '恢复此版本' }))
    await user.click(screen.getByRole('button', { name: '确认恢复？' }))

    await waitFor(() => expect(onRestored).toHaveBeenCalled())
    expect(calls.some((call) => call.path === '/api/entries/1/restore')).toBe(true)
  })
})

describe('RevisionSuggestionDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('生成草稿后对话继续调整并可应用', async () => {
    const user = userEvent.setup()
    const calls: Array<{ method: string; path: string; body?: string }> = []
    const draft = {
      title: null,
      content: '闭水试验至少持续 24 小时，蓄水深度不低于 20mm',
      main_type: null,
      info_nature: null,
      applicable_condition: null,
      note: null,
      change_summary: '补充验收标准',
      reason: '现有内容缺少验收细节',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        calls.push({
          method: init?.method ?? 'GET',
          path: url.pathname,
          body: typeof init?.body === 'string' ? init.body : undefined,
        })
        if (url.pathname.endsWith('/revision-suggestion')) {
          return jsonResponse({
            reply_text: '我建议补充验收标准。',
            draft,
            provider: 'llm',
            model: 'test',
            is_fallback: false,
            error: null,
          })
        }
        if (url.pathname.endsWith('/revision-suggestion/refine')) {
          return jsonResponse({
            reply_text: '这个更多是营销噱头，建议保持现状。',
            draft: null,
            provider: 'llm',
            model: 'test',
            is_fallback: false,
            error: null,
          })
        }
        if (url.pathname.endsWith('/revision-suggestion/apply')) {
          return jsonResponse(ENTRY)
        }
        return jsonResponse(ENTRY)
      }),
    )
    const onApplied = vi.fn()
    renderWithClient(
      <RevisionSuggestionDialog
        open
        entry={ENTRY}
        onOpenChange={vi.fn()}
        onApplied={onApplied}
      />,
    )

    await user.type(screen.getByLabelText('修订指令'), '补充验收标准')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    await screen.findByText('我建议补充验收标准。')
    await waitFor(() =>
      expect(screen.getByDisplayValue('闭水试验至少持续 24 小时，蓄水深度不低于 20mm')).toBeInTheDocument(),
    )

    await user.type(screen.getByLabelText('修订指令'), '缝隙消失术真的是噱头吗')
    await user.click(screen.getByRole('button', { name: /发送/ }))

    await screen.findByText('这个更多是营销噱头，建议保持现状。')
    expect(
      screen.getByDisplayValue('闭水试验至少持续 24 小时，蓄水深度不低于 20mm'),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '应用' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const applyCall = calls.find(
      (call) => call.method === 'POST' && call.path.endsWith('/revision-suggestion/apply'),
    )
    expect(applyCall).toBeDefined()
    expect(JSON.parse(applyCall!.body!).change_summary).toBe('补充验收标准')
  })
})
