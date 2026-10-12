import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  KnowledgeAgentPage,
} from './KnowledgeAgentPage'
import type {
  KnowledgeAnswerBlock,
  KnowledgeConversationPayload,
  KnowledgeMessagePayload,
  KnowledgeRunPayload,
} from '@/lib/api'

const conversation: KnowledgeConversationPayload = {
  id: 1,
  title: '知识库问题',
  scope_type: 'workspace',
  project_id: null,
  project_name: null,
  recent_run_id: 10,
  recent_run_status: 'completed',
  recent_run_current_step: null,
  recent_run_updated_at: '2026-09-15T10:00:00Z',
  last_activity_at: '2026-09-15T10:00:00Z',
  created_at: '2026-09-15T09:00:00Z',
}

const userMessage: KnowledgeMessagePayload = {
  id: 1,
  conversation_id: 1,
  role: 'user',
  message_type: 'user',
  content: '知识库中有哪些结果？',
  client_message_id: 'client-1',
  run_id: 10,
  scope_type: 'workspace',
  project_id: null,
  project_name: null,
  created_at: '2026-09-15T10:00:00Z',
}

const assistantMessage: KnowledgeMessagePayload = {
  ...userMessage,
  id: 2,
  role: 'assistant',
  message_type: 'assistant',
  content: '',
  client_message_id: null,
}

function makeRun(overrides: Partial<KnowledgeRunPayload> = {}): KnowledgeRunPayload {
  return {
    id: 10,
    conversation_id: 1,
    status: 'completed',
    current_step: null,
    dialogue_stage: null,
    user_message_id: 1,
    assistant_message_id: 2,
    error: null,
    dialogue_loop_status: 'completed',
    dialogue_blocks: [],
    can_continue: false,
    continuation: null,
    answer: null,
    created_at: '2026-09-15T10:00:00Z',
    updated_at: '2026-09-15T10:00:00Z',
    ...overrides,
  }
}

function setupFetch(
  initialRun: KnowledgeRunPayload = makeRun(),
  initialItems = [userMessage, assistantMessage],
  options: { renameStatus?: number; deleteStatus?: number } = {},
) {
  let currentRun = initialRun
  let conversations = [conversation]
  let items = initialItems
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    if (url === '/api/knowledge-agent/conversations' && !init?.method) {
      return Promise.resolve({ ok: true, json: async () => conversations })
    }
    if (url === '/api/knowledge-agent/conversations' && init?.method === 'POST') {
      const created = { ...conversation, id: 2, title: '新对话', recent_run_id: null, recent_run_status: null }
      conversations = [created, ...conversations]
      items = []
      currentRun = makeRun({ id: 11, conversation_id: 2, dialogue_loop_status: null, status: 'waiting' })
      return Promise.resolve({ ok: true, json: async () => created })
    }
    if (/^\/api\/knowledge-agent\/conversations\/\d+$/.test(url)) {
      const targetId = Number(url.split('/').pop())
      if (init?.method === 'PATCH') {
        if (options.renameStatus && options.renameStatus !== 200) {
          if (options.renameStatus === 404) {
            conversations = conversations.filter((item) => item.id !== targetId)
          }
          return Promise.resolve({ ok: false, status: options.renameStatus, json: async () => ({ detail: '重命名被拒绝' }) })
        }
        const title = (JSON.parse(String(init.body)) as { title: string }).title
        conversations = conversations.map((item) => (item.id === targetId ? { ...item, title } : item))
        return Promise.resolve({ ok: true, json: async () => conversations.find((item) => item.id === targetId) })
      }
      if (init?.method === 'DELETE') {
        if (options.deleteStatus && options.deleteStatus !== 200) {
          if (options.deleteStatus !== 409) {
            // 404 表示服务端已不存在该对话，列表同样不再返回它
            conversations = conversations.filter((item) => item.id !== targetId)
          }
          return Promise.resolve({ ok: false, status: options.deleteStatus, json: async () => ({ detail: '删除被拒绝' }) })
        }
        conversations = conversations.filter((item) => item.id !== targetId)
        return Promise.resolve({ ok: true, json: async () => ({ ok: true }) })
      }
    }
    if (url.includes('/observability')) {
      return Promise.resolve({ ok: true, json: async () => ({ run_id: currentRun.id, tool_calls: [], model_invocations: [] }) })
    }
    if (url.includes('/cancel')) {
      currentRun = makeRun({ status: 'cancelled', dialogue_loop_status: 'cancelled' })
      return Promise.resolve({ ok: true, json: async () => currentRun })
    }
    if (url.includes('/messages') && init?.method === 'POST') {
      currentRun = makeRun({ status: 'processing', dialogue_loop_status: null })
      return Promise.resolve({ ok: true, json: async () => ({ user_message: userMessage, run: currentRun }) })
    }
    if (url.includes('/messages')) {
      return Promise.resolve({ ok: true, json: async () => ({ items, next_cursor: null, runs: items.length ? [currentRun] : [] }) })
    }
    return Promise.resolve({ ok: true, json: async () => ({}) })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock, setRun: (run: KnowledgeRunPayload) => { currentRun = run } }
}

function renderPage() {
  return render(<KnowledgeAgentPage />)
}

describe('KnowledgeAgentPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('显示 Agent 入口内容、消息各一次，并按真实 block 类型渲染', async () => {
    const blocks: KnowledgeAnswerBlock[] = [
      { kind: 'text', text: '结果说明' },
      { kind: 'list', result_type: 'projects', items: [{ name: '装修项目' }] },
      { kind: 'statistic', label: '正式记录统计', value: 3 },
      { kind: 'entry', title: '甲醛等级', content: '正文内容' },
      { kind: 'evidence', entry_id: 1, source_id: 2, text: '核验原文' },
      { kind: 'candidate', text: '候选修改稿' },
      { kind: 'insufficient', text: '资料不足' },
    ]
    setupFetch(makeRun({ dialogue_blocks: blocks }))
    renderPage()

    expect(await screen.findByTestId('knowledge-agent-page')).toBeInTheDocument()
    expect(screen.getAllByText('知识 Agent').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByTestId('agent-user-message')).toHaveLength(1)
    expect(screen.getAllByTestId('agent-assistant-message')).toHaveLength(1)
    expect(screen.getByTestId('agent-block-list')).toHaveTextContent('当前 Workspace 可访问项目')
    expect(screen.getByTestId('agent-block-statistic')).toHaveTextContent('3')
    expect(screen.getByTestId('agent-block-entry')).toHaveTextContent('甲醛等级')
    expect(screen.getByTestId('agent-block-evidence')).toBeInTheDocument()
    expect(screen.getByTestId('agent-block-candidate')).toHaveTextContent('AI 候选稿')
    expect(screen.getByTestId('agent-block-insufficient')).toHaveTextContent('资料不足')
    expect(screen.queryByText('运行状态')).not.toBeInTheDocument()
    expect(screen.queryByTestId('diagnostic-rail')).not.toBeInTheDocument()
  })

  it('处理中显示停止，停止后可以新建会话', async () => {
    setupFetch(makeRun({ status: 'processing', dialogue_loop_status: null, current_step: 'dialogue_loop' }))
    renderPage()

    const stop = await screen.findByTestId('agent-stop')
    expect(screen.getByTestId('agent-active-stage')).toHaveTextContent('正在准备本轮回答')
    await userEvent.click(stop)
    await waitFor(() => expect(screen.queryByTestId('agent-stop')).not.toBeInTheDocument())
    await userEvent.click(screen.getByTestId('agent-new-conversation'))
    expect(await screen.findAllByTestId('agent-conversation-item')).toHaveLength(2)
  })

  it('按服务端真实阶段展示提示并支持减少动画', async () => {
    setupFetch(makeRun({
      status: 'processing',
      dialogue_loop_status: 'processing',
      current_step: 'dialogue_loop',
      dialogue_stage: 'reading_entries',
    }))
    renderPage()

    const stage = await screen.findByTestId('agent-active-stage')
    expect(stage).toHaveTextContent('读取记录中')
    expect(stage).toHaveAttribute('aria-live', 'polite')
    expect(stage.querySelector('svg')).toHaveClass('motion-reduce:animate-none')
  })

  it('终态即使收到旧阶段字段也不残留动效', async () => {
    setupFetch(makeRun({
      status: 'completed',
      dialogue_loop_status: 'completed',
      dialogue_stage: 'finalizing',
      dialogue_blocks: [{ kind: 'text', text: '回答完成' }],
    }))
    renderPage()

    expect(await screen.findByText('回答完成')).toBeInTheDocument()
    expect(screen.queryByTestId('agent-active-stage')).not.toBeInTheDocument()
    expect(screen.queryByText('整理回答中')).not.toBeInTheDocument()
  })

  it('未知阶段回退为稳定处理中提示', async () => {
    setupFetch(makeRun({
      status: 'processing',
      dialogue_loop_status: 'processing',
      dialogue_stage: 'future_stage',
    }))
    renderPage()

    expect(await screen.findByTestId('agent-active-stage')).toHaveTextContent(
      '正在准备本轮回答',
    )
  })

  it('partial completed 提供继续操作并使用正式消息提交', async () => {
    const { calls } = setupFetch(makeRun({
      status: 'partial',
      dialogue_loop_status: 'partial_completed',
      can_continue: true,
      continuation: { task_type: 'finalize_answer' },
      dialogue_blocks: [{ kind: 'text', text: '已完成查询，等待继续。' }],
    }))
    renderPage()

    const continueButton = await screen.findByTestId('agent-continue')
    expect(screen.getAllByText('部分完成').length).toBeGreaterThanOrEqual(1)
    await userEvent.click(continueButton)
    await waitFor(() => {
      const submit = calls.find(({ url, init }) => url.endsWith('/messages') && init?.method === 'POST')
      expect(submit).toBeDefined()
      expect(JSON.parse(String(submit?.init?.body)).message).toBe('继续')
    })
  })

  it('空结果和失败结果保持准确状态', async () => {
    setupFetch(makeRun({
      dialogue_blocks: [{ kind: 'list', result_type: 'list', items: [], semantics: { total_count: 0, returned_count: 0 } }],
    }))
    renderPage()
    expect(await screen.findByTestId('agent-block-list')).toHaveTextContent('总数 0')
  })

  it('失败 Run 显示失败状态和服务端错误', async () => {
    setupFetch(makeRun({ status: 'failed', dialogue_loop_status: 'failed', error: '服务暂时不可用' }))
    renderPage()
    expect(await screen.findByText('未完成')).toBeInTheDocument()
    expect(screen.getByText('服务暂时不可用')).toBeInTheDocument()
  })
})

describe('KnowledgeAgentPage 会话重命名与删除', () => {
  it('重命名后就地更新轨道与标题，不重载整份列表', async () => {
    const { calls } = setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    const listCallsBefore = calls.filter((call) => call.url === '/api/knowledge-agent/conversations' && !call.init?.method).length
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    const input = await screen.findByTestId('agent-rename-input')
    await userEvent.clear(input)
    await userEvent.type(input, '施工验收笔记')
    await userEvent.click(screen.getByTestId('agent-rename-submit'))

    await waitFor(() => expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('施工验收笔记'))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('施工验收笔记')
    const listCalls = calls.filter((call) => call.url === '/api/knowledge-agent/conversations' && !call.init?.method)
    expect(listCalls).toHaveLength(listCallsBefore)
  })

  it('重命名非法输入就地提示且不发请求', async () => {
    const { calls } = setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    const input = await screen.findByTestId('agent-rename-input')
    await userEvent.clear(input)
    await userEvent.type(input, '   ')
    await userEvent.click(screen.getByTestId('agent-rename-submit'))

    expect(await screen.findByRole('alert')).toHaveTextContent('标题不能为空')
    expect(calls.some((call) => call.init?.method === 'PATCH')).toBe(false)
  })

  it('已命名对话在发送首条消息后仍保留用户标题', async () => {
    setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    const input = await screen.findByTestId('agent-rename-input')
    await userEvent.clear(input)
    await userEvent.type(input, '我的命名')
    await userEvent.click(screen.getByTestId('agent-rename-submit'))
    await waitFor(() => expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('我的命名'))

    await userEvent.type(screen.getByTestId('agent-composer'), '闭水试验持续多久？')
    await userEvent.click(screen.getByTestId('agent-send'))

    await waitFor(() => expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('我的命名'))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('我的命名')
  })

  it('删除需二次确认并说明内容保留，取消不发请求', async () => {
    const { calls } = setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除对话' }))

    expect(await screen.findByText(/将从列表移除，对话内容保留/)).toBeInTheDocument()
    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.queryByText(/将从列表移除，对话内容保留/)).not.toBeInTheDocument())
    expect(calls.some((call) => call.init?.method === 'DELETE')).toBe(false)
  })

  it('删除当前对话后落到新建，且不产生多余空对话', async () => {
    const { calls } = setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除对话' }))
    await userEvent.click(await screen.findByTestId('agent-delete-submit'))

    await waitFor(() => expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(1))
    expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('新对话')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('新对话')
    const creates = calls.filter(
      (call) => call.url === '/api/knowledge-agent/conversations' && call.init?.method === 'POST',
    )
    expect(creates).toHaveLength(1)
  })

  it('删除非当前对话只移除该行，不新建', async () => {
    const { calls } = setupFetch()
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByTestId('agent-new-conversation'))
    await waitFor(() => expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(2))

    const createsBefore = calls.filter(
      (call) => call.url === '/api/knowledge-agent/conversations' && call.init?.method === 'POST',
    ).length
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除对话' }))
    await userEvent.click(await screen.findByTestId('agent-delete-submit'))

    await waitFor(() => expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(1))
    expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('新对话')
    const createsAfter = calls.filter(
      (call) => call.url === '/api/knowledge-agent/conversations' && call.init?.method === 'POST',
    ).length
    expect(createsAfter).toBe(createsBefore)
  })

  it('删除冲突时就地提示并保留该行', async () => {
    setupFetch(makeRun(), [userMessage, assistantMessage], { deleteStatus: 409 })
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除对话' }))
    await userEvent.click(await screen.findByTestId('agent-delete-submit'))

    expect(await screen.findByRole('alert')).toHaveTextContent('正在进行的问答')
    expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(1)
  })

  it('删除返回 404 时按已删除处理并落到新建', async () => {
    setupFetch(makeRun(), [userMessage, assistantMessage], { deleteStatus: 404 })
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '删除对话' }))
    await userEvent.click(await screen.findByTestId('agent-delete-submit'))

    await waitFor(() => expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(1))
    expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('新对话')
  })

  it('重命名返回 404 时移除该行并落到新建', async () => {
    setupFetch(makeRun(), [userMessage, assistantMessage], { renameStatus: 404 })
    renderPage()

    await screen.findByTestId('agent-conversation-item')
    await userEvent.click(screen.getByRole('button', { name: '知识库问题 会话操作' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: '重命名' }))
    const input = await screen.findByTestId('agent-rename-input')
    await userEvent.clear(input)
    await userEvent.type(input, '已被删除的对话')
    await userEvent.click(screen.getByTestId('agent-rename-submit'))

    await waitFor(() => expect(screen.getAllByTestId('agent-conversation-item')).toHaveLength(1))
    expect(screen.getByTestId('agent-conversation-item')).toHaveTextContent('新对话')
  })
})

describe('KnowledgeAgentPage 时间口径', () => {
  it('对话更新时间按 UTC 解析服务端不带时区的时间串', async () => {
    setupFetch(makeRun({ updated_at: '2026-09-29T07:23:51' }))

    render(<KnowledgeAgentPage />)

    const expected = new Intl.DateTimeFormat('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date('2026-09-29T07:23:51Z'))
    expect(await screen.findByText(expected)).toBeInTheDocument()
  })
})
