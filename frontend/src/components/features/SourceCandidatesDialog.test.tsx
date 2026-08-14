import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SourceCandidatesDialog } from './SourceCandidatesDialog'

function renderDialog() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <SourceCandidatesDialog sourceId={7} open onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

describe('SourceCandidatesDialog', () => {
  it('展示 AI 候选与证据', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        expect(url.pathname).toBe('/api/sources/7/candidates')
        return Promise.resolve({
          ok: true,
          json: async () => [
            {
              id: 1,
              source_id: 7,
              candidate_kind: 'recommended',
              title: '闭水试验时长',
              content: '闭水试验至少持续 24 小时。',
              main_type: 'knowledge',
              info_nature: 'fact',
              applicable_condition: null,
              note: null,
              evidence: [{ attachment_id: 3, quote: '闭水试验至少 24 小时' }],
              reason: '独立可用',
              risk_flags: [],
              status: 'pending',
            },
          ],
        })
      }),
    )

    renderDialog()

    expect(await screen.findByText('闭水试验时长')).toBeInTheDocument()
    expect(screen.getByText('闭水试验至少持续 24 小时。')).toBeInTheDocument()
    expect(screen.getAllByText('AI 候选').length).toBeGreaterThan(0)
    expect(screen.getByText(/附件 3/)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
