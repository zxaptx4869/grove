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
                relation_status: 'new',
                relation_target_entry_id: null,
                relation_target_entry_title: null,
                relation_target_entry_node_name: null,
                relation_reason: null,
                revision_draft: null,
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
    await userEvent.click(screen.getByRole('button', { name: '归档目录' }))
    await userEvent.click(await screen.findByRole('option', { name: /施工/ }))
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
                relation_status: 'new',
                relation_target_entry_id: null,
                relation_target_entry_title: null,
                relation_target_entry_node_name: null,
                relation_reason: null,
                revision_draft: null,
              },
            ],
          })
        }
        return Promise.resolve({ ok: true, json: async () => [] })
      }),
    )

    renderPage()

    expect(await screen.findByText('晶蕾烘干需手动勾选')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '归档目录' })).toHaveTextContent('施工')
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
                relation_status: 'new',
                relation_target_entry_id: null,
                relation_target_entry_title: null,
                relation_target_entry_node_name: null,
                relation_reason: null,
                revision_draft: null,
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
            relation_status: 'new',
            relation_target_entry_id: null,
            relation_target_entry_title: null,
            relation_target_entry_node_name: null,
            relation_reason: null,
            revision_draft: null,
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

  it('疑似重复候选可补充来源证据', async () => {
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
                title: '闭水试验',
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
              title: '闭水试验',
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
                  text_content: '闭水试验通常持续 24 小时',
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
                title: '闭水试验通常持续 24 小时',
                content: '闭水试验通常持续 24 小时。',
                main_type: 'knowledge',
                info_nature: 'fact',
                applicable_condition: null,
                note: null,
                evidence: [{ attachment_id: 9, quote: '闭水试验通常持续 24 小时' }],
                reason: null,
                risk_flags: [],
                status: 'pending',
                recommended_node_id: null,
                node_alternatives: [],
                node_reason: null,
                routing_status: 'no_suitable',
                new_node_suggestion: null,
                relation_status: 'duplicate',
                relation_target_entry_id: 20,
                relation_target_entry_title: '闭水试验规范',
                relation_target_entry_node_name: '施工',
                relation_reason: '内容相同',
                revision_draft: null,
              },
            ],
          })
        }
        if (url.pathname === '/api/candidates/7/add-evidence' && init?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 20,
              project_id: 1,
              node_id: 10,
              node_name: '施工',
              title: '闭水试验规范',
              content: '闭水试验通常持续 24 小时。',
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

    expect(
      await screen.findByRole('heading', { name: '闭水试验通常持续 24 小时' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '补充来源证据' }))

    await waitFor(() => {
      expect(
        calls.some(
          (call) =>
            call.method === 'POST' &&
            call.path === '/api/candidates/7/add-evidence' &&
            call.body?.includes('20'),
        ),
      ).toBe(true)
    })
  })

  it('应用修订草稿时回传变更说明', async () => {
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
                title: '闭水试验',
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
              title: '闭水试验',
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
                  text_content: '闭水试验通常持续 24 小时',
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
                title: '闭水试验通常持续 24 小时',
                content: '闭水试验通常持续 24 小时。',
                main_type: 'knowledge',
                info_nature: 'fact',
                applicable_condition: null,
                note: null,
                evidence: [{ attachment_id: 9, quote: '闭水试验通常持续 24 小时' }],
                reason: null,
                risk_flags: [],
                status: 'pending',
                recommended_node_id: null,
                node_alternatives: [],
                node_reason: null,
                routing_status: 'no_suitable',
                new_node_suggestion: null,
                relation_status: 'supplement',
                relation_target_entry_id: 20,
                relation_target_entry_title: '闭水试验规范',
                relation_target_entry_node_name: '施工',
                relation_reason: '可补充验收标准',
                revision_draft: {
                  title: null,
                  content: '闭水试验通常持续 24 小时，观察渗漏。',
                  main_type: null,
                  info_nature: null,
                  applicable_condition: null,
                  note: null,
                  change_summary: '补充观察要点',
                  reason: '现有内容缺少验收细节',
                  external_supplemented: false,
                },
              },
            ],
          })
        }
        if (
          url.pathname === '/api/candidates/7/apply-revision' &&
          init?.method === 'POST'
        ) {
          return Promise.resolve({
            ok: true,
            json: async () => ({
              id: 20,
              project_id: 1,
              node_id: 10,
              node_name: '施工',
              title: '闭水试验规范',
              content: '闭水试验通常持续 24 小时，观察渗漏。',
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

    expect(
      await screen.findByRole('heading', { name: '闭水试验通常持续 24 小时' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '应用修订草稿' }))

    await waitFor(() => {
      const applyCall = calls.find(
        (call) =>
          call.method === 'POST' && call.path === '/api/candidates/7/apply-revision',
      )
      expect(applyCall).toBeDefined()
      expect(JSON.parse(applyCall!.body!).change_summary).toBe('补充观察要点')
    })
  })

  it('切换到批量处理显示批量视图', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
    )

    renderPage()

    await userEvent.click(screen.getByRole('button', { name: '批量处理' }))

    expect(await screen.findByText('已选 0 条低风险候选')).toBeInTheDocument()
  })
})
