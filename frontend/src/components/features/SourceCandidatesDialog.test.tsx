import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SourceCandidatesDialog } from './SourceCandidatesDialog'

function ok(data: unknown) {
  return Promise.resolve({ ok: true, json: async () => data })
}

function renderDialog() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <SourceCandidatesDialog
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

describe('SourceCandidatesDialog', () => {
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
})
