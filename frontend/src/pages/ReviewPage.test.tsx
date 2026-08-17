import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewPage } from './ReviewPage'

function renderPage() {
  const queryClient = new QueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/projects/1/review']}>
        <Routes>
          <Route path="/projects/:projectId/review" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewPage', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('展示待审来源与候选，并可采纳', async () => {
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
        if (url.pathname === '/api/projects/1/review/sources') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 5,
                title: '烘干使用体验',
                note: '关注默认设置',
                status: 'done',
                review_status: 'pending_review',
                pending_candidate_count: 1,
              },
            ],
          })
        }
        if (url.pathname === '/api/projects/1/tree') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 10, name: '施工', description: null, position: 0, children: [] },
            ],
          })
        }
        if (url.pathname === '/api/sources/5') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 5,
              title: '烘干使用体验',
              note: '关注默认设置',
              project_id: 1,
              status: 'done',
              review_status: 'pending_review',
              created_at: '',
              updated_at: '',
              attachments: [
                { id: 9, kind: 'text', position: 0, mime_type: null, file_name: null, text_content: '晶蕾烘干需要手动勾选' },
              ],
            }),
          })
        }
        if (url.pathname === '/api/sources/5/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 7,
                source_id: 5,
                candidate_kind: 'recommended',
                title: '晶蕾烘干需手动勾选',
                content: '晶蕾烘干需要手动勾选。',
                main_type: 'knowledge',
                info_nature: 'fact',
                applicable_condition: null,
                note: null,
                evidence: [{ attachment_id: 9, quote: '晶蕾烘干需要手动勾选' }],
                reason: '独立可用',
                risk_flags: [],
                status: 'pending',
              },
            ],
          })
        }
        if (url.pathname === '/api/candidates/7' && init?.method === 'PATCH') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 7,
              source_id: 5,
              candidate_kind: 'recommended',
              title: '晶蕾烘干需手动勾选',
              content: '晶蕾烘干需要手动勾选。',
              main_type: 'knowledge',
              info_nature: 'fact',
              applicable_condition: null,
              note: null,
              evidence: [],
              reason: null,
              risk_flags: [],
              status: 'pending',
            }),
          })
        }
        if (url.pathname === '/api/candidates/7/archive' && init?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 20,
              project_id: 1,
              node_id: 10,
              title: '晶蕾烘干需手动勾选',
              content: '晶蕾烘干需要手动勾选。',
              main_type: 'knowledge',
              info_nature: 'fact',
              applicable_condition: null,
              note: null,
              created_at: '',
              updated_at: '',
              evidences: [],
            }),
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderPage()

    expect(await screen.findByText('晶蕾烘干需手动勾选')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('归档目录'), '10')
    await userEvent.click(screen.getByRole('button', { name: '采纳' }))

    expect(
      calls.some(
        (call) =>
          call.method === 'POST' &&
          call.path === '/api/candidates/7/archive' &&
          call.body?.includes('10'),
      ),
    ).toBe(true)
  })

  it('有目录推荐时预填推荐节点', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects/1/review/sources') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 5,
                title: '烘干使用体验',
                note: null,
                status: 'done',
                review_status: 'pending_review',
                pending_candidate_count: 1,
              },
            ],
          })
        }
        if (url.pathname === '/api/projects/1/tree') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 10, name: '施工', description: null, position: 0, children: [] },
            ],
          })
        }
        if (url.pathname === '/api/sources/5') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 5,
              title: '烘干使用体验',
              note: null,
              project_id: 1,
              status: 'done',
              recommended_project_id: null,
              project_recommendation_reason: null,
              created_at: '',
              updated_at: '',
              attachments: [
                {
                  id: 9,
                  kind: 'text',
                  position: 0,
                  mime_type: null,
                  file_name: null,
                  text_content: '晶蕾烘干需要手动勾选',
                },
              ],
            }),
          })
        }
        if (url.pathname === '/api/sources/5/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 7,
                source_id: 5,
                candidate_kind: 'recommended',
                title: '晶蕾烘干需手动勾选',
                content: '晶蕾烘干需要手动勾选。',
                main_type: 'knowledge',
                info_nature: 'fact',
                applicable_condition: null,
                note: null,
                evidence: [],
                reason: '独立可用',
                risk_flags: [],
                status: 'pending',
                recommended_node_id: 10,
                node_alternatives: [],
                node_reason: '匹配施工节点',
                routing_status: 'recommended',
              },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderPage()

    expect(await screen.findByText('晶蕾烘干需手动勾选')).toBeInTheDocument()
    expect(screen.getByLabelText('归档目录')).toHaveValue('10')
    expect(screen.getByText(/AI 推荐：施工/)).toBeInTheDocument()
  })

  it('暂无合适位置时展示新增节点并归档并调用接口', async () => {
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
        if (url.pathname === '/api/projects/1/review/sources') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 5,
                title: 'BOSS直聘找工作',
                note: null,
                status: 'done',
                review_status: 'pending_review',
                pending_candidate_count: 1,
              },
            ],
          })
        }
        if (url.pathname === '/api/projects/1/tree') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/sources/5') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 5,
              title: 'BOSS直聘找工作',
              note: null,
              project_id: 1,
              status: 'done',
              recommended_project_id: null,
              project_recommendation_reason: null,
              created_at: '',
              updated_at: '',
              attachments: [
                {
                  id: 9,
                  kind: 'text',
                  position: 0,
                  mime_type: null,
                  file_name: null,
                  text_content: '识别不靠谱公司与如何寻找靠谱工作',
                },
              ],
            }),
          })
        }
        if (url.pathname === '/api/sources/5/candidates') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 7,
                source_id: 5,
                candidate_kind: 'recommended',
                title: '识别不靠谱公司',
                content: '识别不靠谱公司。',
                main_type: 'knowledge',
                info_nature: 'fact',
                applicable_condition: null,
                note: null,
                evidence: [],
                reason: null,
                risk_flags: [],
                status: 'pending',
                recommended_node_id: null,
                node_alternatives: [],
                node_reason: null,
                routing_status: 'no_suitable',
                new_node_suggestion: {
                  name: '求职经验',
                  parent_id: null,
                  reason: '没有匹配目录',
                },
              },
            ],
          })
        }
        if (url.pathname === '/api/candidates/7' && init?.method === 'PATCH') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 7,
              source_id: 5,
              candidate_kind: 'recommended',
              title: '识别不靠谱公司',
              content: '识别不靠谱公司。',
              main_type: 'knowledge',
              info_nature: 'fact',
              applicable_condition: null,
              note: null,
              evidence: [],
              reason: null,
              risk_flags: [],
              status: 'pending',
              recommended_node_id: null,
              node_alternatives: [],
              node_reason: null,
              routing_status: 'no_suitable',
              new_node_suggestion: {
                name: '求职经验',
                parent_id: null,
                reason: '没有匹配目录',
              },
            }),
          })
        }
        if (url.pathname === '/api/candidates/7/archive-with-new-node' && init?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 20,
              project_id: 1,
              node_id: 30,
              node_name: '求职经验',
              title: '识别不靠谱公司',
              content: '识别不靠谱公司。',
              main_type: 'knowledge',
              info_nature: 'fact',
              applicable_condition: null,
              note: null,
              created_at: '',
              updated_at: '',
              evidences: [],
            }),
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderPage()

    expect(await screen.findByText('识别不靠谱公司')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '新增「求职经验」并归档' }))

    await waitFor(() => {
      expect(
        calls.some(
          (call) =>
            call.method === 'POST' &&
            call.path === '/api/candidates/7/archive-with-new-node' &&
            call.body?.includes('求职经验'),
        ),
      ).toBe(true)
    })
  })

  it('同一来源聚合同路径新节点建议', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = new URL(String(input), 'http://localhost')
        if (url.pathname === '/api/projects/1/review/sources') {
          return Promise.resolve({
            ok: true,
            json: async () => [
              {
                id: 5,
                title: 'BOSS直聘找工作',
                note: null,
                status: 'done',
                review_status: 'pending_review',
                pending_candidate_count: 2,
              },
            ],
          })
        }
        if (url.pathname === '/api/projects/1/tree') {
          return Promise.resolve({ ok: true, json: async () => [] })
        }
        if (url.pathname === '/api/sources/5') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 5,
              title: 'BOSS直聘找工作',
              note: null,
              project_id: 1,
              status: 'done',
              created_at: '',
              updated_at: '',
              attachments: [
                {
                  id: 9,
                  kind: 'text',
                  position: 0,
                  mime_type: null,
                  file_name: null,
                  text_content: '找工作',
                },
              ],
            }),
          })
        }
        if (url.pathname === '/api/sources/5/candidates') {
          const base = {
            candidate_kind: 'recommended',
            content: '内容',
            main_type: 'knowledge',
            info_nature: 'fact',
            applicable_condition: null,
            note: null,
            evidence: [],
            reason: null,
            risk_flags: [],
            status: 'pending',
            recommended_node_id: null,
            node_alternatives: [],
            node_reason: null,
            routing_status: 'no_suitable',
            new_node_suggestion: {
              name: '求职经验',
              parent_id: null,
              reason: '没有匹配目录',
            },
          }
          return Promise.resolve({
            ok: true,
            json: async () => [
              { id: 7, source_id: 5, title: '识别不靠谱公司', ...base },
              { id: 8, source_id: 5, title: '寻找靠谱工作', ...base },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderPage()

    expect(await screen.findByText('建议新增「求职经验」 · 2 条')).toBeInTheDocument()
  })
})
