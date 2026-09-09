import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkbenchApp } from './WorkbenchApp'
import * as api from './api'
import type { WorkbenchState } from './types'

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return {
    ...actual,
    bootstrap: vi.fn(),
    fetchState: vi.fn(),
    createConversation: vi.fn(),
    submitTurn: vi.fn(),
    cancelTurn: vi.fn(),
    saveFeedback: vi.fn(),
    downloadExport: vi.fn(),
  }
})

const state: WorkbenchState = {
  metadata: {
    experiment_version: 'dialogue-loop-v2-workbench',
    prompt_version: 'v2',
    provider: 'deepseek',
    model: 'deepseek-chat',
    offline: false,
    snapshot_at: '2026-09-07T12:00:00Z',
    snapshot_fingerprint: 'abc123',
    status: 'ready',
    unsafe_reason: null,
    storage_path: '/private/records/workbench.json',
    serial_execution: true,
  },
  budget: {
    text_requests_per_batch: 192,
    embedding_requests_per_batch: 64,
    text_requests_per_turn: 8,
    embedding_requests_per_turn: 4,
    tool_calls_per_turn: 12,
    model_input_tokens_per_request: 8192,
    input_estimate_soft_limit: 6500,
    solve_seconds_per_turn: 120,
    finalize_seconds: 15,
    used: { text_requests: 1, embedding_requests: 0 },
    remaining: { text_requests: 191, embedding_requests: 64 },
  },
  active_turn_id: null,
  sessions: [
    {
      id: 'session-1',
      active: true,
      created_at: '2026-09-07T12:00:00Z',
      experiment_version: 'dialogue-loop-v2-workbench',
      provider: 'deepseek',
      model: 'deepseek-chat',
      offline: false,
      conversations: [
        {
          id: 'conversation-1',
          session_id: 'session-1',
          title: '装修记录',
          created_at: '2026-09-07T12:00:00Z',
          updated_at: '2026-09-07T12:01:00Z',
          read_only: false,
          turns: [
            {
              id: 'turn-1',
              request_id: 'request-1',
              user_message: '列出装修记录',
              status: 'completed',
              stage: 'completed',
              created_at: '2026-09-07T12:00:00Z',
              completed_at: '2026-09-07T12:01:00Z',
              answer: '共找到 2 条正式记录。',
              duration_ms: 1234,
              blocks: [
                { kind: 'statistic', text: '正式记录总数：2', value: 2 },
                  {
                    kind: 'list',
                    label: '相关记录',
                    items: [
                    { entry_id: 1, title: '第一条', project_name: '房子装修', excerpt: '第一条正文摘录' },
                    { entry_id: 2, title: '第二条', project_name: '房子装修' },
                    ],
                  },
                {
                  kind: 'entry',
                  title: '第一条',
                  content: '第一条完整正文',
                  project_name: '房子装修',
                  node_path: '装修/材料',
                  completeness: 'limited',
                },
                { kind: 'evidence', text: '已核验原文', entry_id: 1, source_id: 2 },
              ],
              tool_calls: [
                { tool: 'query_entries', status: 'completed', params: { project: '房子装修' } },
              ],
              model_calls: [
                {
                  provider: 'deepseek',
                  model: 'deepseek-chat',
                  actual_input_tokens: 320,
                  estimated_input_tokens: 380,
                },
              ],
              budget: {},
              finalization: { status: 'not_needed' },
            },
          ],
        },
      ],
    },
  ],
}

describe('知识 Agent 实验工作台', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    vi.mocked(api.bootstrap).mockResolvedValue(structuredClone(state))
    vi.mocked(api.fetchState).mockResolvedValue(structuredClone(state))
    vi.mocked(api.submitTurn).mockResolvedValue(state.sessions[0].conversations[0].turns[0])
    vi.mocked(api.saveFeedback).mockResolvedValue({
      kind: 'omitted',
      note: '漏了条件',
      saved_at: '2026-09-07T12:02:00Z',
    })
  })

  it('展示真实元数据、准确列表顺序、来源和折叠执行记录', async () => {
    render(<WorkbenchApp />)

    expect(await screen.findByRole('heading', { name: '装修记录' })).toBeInTheDocument()
    expect(screen.getByText('deepseek-chat')).toBeInTheDocument()
    expect(screen.getByText('正式记录总数：2')).toBeInTheDocument()
    const items = screen.getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('第一条')
    expect(items[1]).toHaveTextContent('第二条')
    expect(screen.getByText('房子装修 · 第一条正文摘录')).toBeInTheDocument()
    expect(screen.getByText('第一条完整正文')).toBeInTheDocument()
    expect(screen.getByText('查看已核验来源')).toBeInTheDocument()
    expect(screen.getByText('执行记录')).toBeInTheDocument()
    expect(screen.queryByText('实际输入 token：320')).not.toBeVisible()
  })

  it('发送任意消息时只提交一次客户端请求标识', async () => {
    const user = userEvent.setup()
    render(<WorkbenchApp />)
    const input = await screen.findByLabelText('输入消息')

    await user.type(input, '换到另一个项目{enter}')

    await waitFor(() => expect(api.submitTurn).toHaveBeenCalledTimes(1))
    expect(api.submitTurn).toHaveBeenCalledWith(
      'conversation-1',
      '换到另一个项目',
      expect.any(String),
    )
  })

  it('保存三类之一的轮次反馈和说明', async () => {
    const user = userEvent.setup()
    render(<WorkbenchApp />)
    await user.click(await screen.findByText('反馈这轮回答'))
    await user.click(screen.getByRole('button', { name: '漏答' }))
    await user.type(screen.getByPlaceholderText('补充具体问题（可选）'), '漏了条件')
    await user.click(screen.getByRole('button', { name: '保存反馈' }))

    await waitFor(() =>
      expect(api.saveFeedback).toHaveBeenCalledWith(
        'conversation-1',
        'turn-1',
        'omitted',
        '漏了条件',
      ),
    )
  })

  it('窄屏提示存在且预算耗尽时输入禁用', async () => {
    const exhausted = structuredClone(state)
    exhausted.budget.remaining.text_requests = 0
    vi.mocked(api.bootstrap).mockResolvedValue(exhausted)
    render(<WorkbenchApp />)

    expect(await screen.findByText('请使用电脑访问实验工作台')).toBeInTheDocument()
    expect(screen.getByText('本批文本请求预算已用尽，不会自动重置。')).toBeInTheDocument()
    expect(screen.getByLabelText('输入消息')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    expect(api.submitTurn).not.toHaveBeenCalled()
  })

  it('刷新后优先选择当前运行并把离线历史明确放在后面', async () => {
    const withHistory = structuredClone(state)
    const oldSession = structuredClone(withHistory.sessions[0])
    oldSession.id = 'old-session'
    oldSession.active = false
    oldSession.offline = true
    oldSession.created_at = '2026-09-07T11:00:00Z'
    oldSession.conversations[0].id = 'old-conversation'
    oldSession.conversations[0].title = '旧离线对话'
    oldSession.conversations[0].read_only = true
    withHistory.sessions.unshift(oldSession)
    vi.mocked(api.bootstrap).mockResolvedValue(withHistory)

    render(<WorkbenchApp />)

    expect(await screen.findByRole('heading', { name: '装修记录' })).toBeInTheDocument()
    expect(screen.getByText(/离线验收/)).toBeInTheDocument()
    const conversationButtons = screen.getByRole('navigation').querySelectorAll('button')
    expect(conversationButtons[0]).toHaveTextContent('装修记录')
    expect(conversationButtons[1]).toHaveTextContent('旧离线对话')
  })

  it('诊断缺失时显示未知，并区分隔离检查失败', async () => {
    const failed = structuredClone(state)
    const turn = failed.sessions[0].conversations[0].turns[0]
    turn.status = 'failed'
    turn.stage = 'failed'
    turn.error = 'RuntimeError: 执行层意外失败'
    turn.solve_error = 'BudgetExceeded: 本轮工具动作预算已耗尽'
    turn.tool_calls = null
    turn.model_calls = null
    turn.persistence = { status: 'failed', category: 'run_persistence' }
    turn.isolation_check = { status: 'failed' }
    vi.mocked(api.bootstrap).mockResolvedValue(failed)

    render(<WorkbenchApp />)

    expect(await screen.findByText(/隔离检查失败，无法核验业务数据是否变化/)).toBeInTheDocument()
    expect(screen.getByText(/求解提前停止：BudgetExceeded/)).toBeInTheDocument()
    expect(screen.getByText(/工具记录未知 · 模型调用记录未知/)).toBeInTheDocument()
    expect(screen.queryByText(/0 个工具 · 0 次模型调用/)).not.toBeInTheDocument()
  })

  it('部分完成轮次展示权威停止原因与可继续提示', async () => {
    const partial = structuredClone(state)
    const turn = partial.sessions[0].conversations[0].turns[0]
    turn.status = 'partial_completed'
    turn.stage = 'partial_completed'
    turn.completion = {
      status: 'partial_completed',
      reason_code: 'tool_action_budget',
      reason: '本轮工具动作预算已耗尽',
      incomplete_steps: ['未核验剩余目录'],
      can_continue: true,
    }
    vi.mocked(api.bootstrap).mockResolvedValue(partial)

    render(<WorkbenchApp />)

    expect((await screen.findAllByText('部分完成')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('本轮工具动作预算已耗尽')).toBeInTheDocument()
    expect(screen.getByText(/未完成：未核验剩余目录/)).toBeInTheDocument()
    expect(screen.getByText('可以下一轮继续未完成步骤。')).toBeInTheDocument()
  })

  it('直接相关集合使用专用标题且读取失败显示精确状态', async () => {
    const partial = structuredClone(state)
    const turn = partial.sessions[0].conversations[0].turns[0]
    const list = turn.blocks[1]
    list.semantics = {
      subject: 'entries',
      project_name: '房子装修',
      relevance_scope: 'direct',
      result_role: 'authorized',
      returned_count: 1,
      total_count: 1,
      completeness: 'limited',
      classification_counts: { direct: 1, indirect: 1, unrelated: 1 },
    }
    list.items = [{ entry_id: 1, title: '第一条', project_name: '房子装修' }]
    turn.status = 'partial_completed'
    turn.stage = 'partial_completed'
    turn.completion = {
      status: 'partial_completed',
      reason_code: 'search_succeeded_read_failed',
      reason: '搜索成功，但 Entry 正文读取失败',
      incomplete_steps: ['搜索已完成；正文尚未完整读取'],
      can_continue: true,
    }
    vi.mocked(api.bootstrap).mockResolvedValue(partial)

    render(<WorkbenchApp />)

    expect(await screen.findByText('房子装修 · 直接相关正式记录')).toBeInTheDocument()
    expect(screen.getByText('搜索成功但读取失败')).toBeInTheDocument()
    expect(screen.getByText('搜索成功，但 Entry 正文读取失败')).toBeInTheDocument()
  })

  it('纯参数错误显示未执行而不是部分完成', async () => {
    const notExecuted = structuredClone(state)
    const turn = notExecuted.sessions[0].conversations[0].turns[0]
    turn.status = 'not_executed'
    turn.stage = 'not_executed'
    turn.answer = ''
    turn.blocks = []
    turn.completion = {
      status: 'not_executed',
      reason_code: 'invalid_tool_params',
      reason: '工具参数非法：1 项',
      incomplete_steps: ['查询未执行：模型未能提交合法参数'],
      can_continue: true,
    }
    vi.mocked(api.bootstrap).mockResolvedValue(notExecuted)

    render(<WorkbenchApp />)

    expect((await screen.findAllByText('未执行')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('查询未执行')).toBeInTheDocument()
    expect(screen.queryByText('部分完成')).not.toBeInTheDocument()
  })
})
