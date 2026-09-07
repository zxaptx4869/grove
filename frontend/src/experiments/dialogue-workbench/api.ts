import type { Feedback, Turn, WorkbenchState } from './types'

class WorkbenchApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const value = (await response.json()) as { detail?: string }
      if (value.detail) detail = value.detail
    } catch {
      // 非 JSON 错误保留状态码。
    }
    throw new WorkbenchApiError(detail, response.status)
  }
  return (await response.json()) as T
}

export const bootstrap = () =>
  request<WorkbenchState>('/api/workbench/bootstrap', { method: 'POST' })
export const fetchState = () => request<WorkbenchState>('/api/workbench/state')
export const createConversation = () => request('/api/workbench/conversations', { method: 'POST' })
export const submitTurn = (conversationId: string, message: string, requestId: string) =>
  request<Turn>(`/api/workbench/conversations/${conversationId}/turns`, {
    method: 'POST',
    body: JSON.stringify({ message, request_id: requestId }),
  })
export const cancelTurn = (conversationId: string, turnId: string) =>
  request<Turn>(`/api/workbench/conversations/${conversationId}/turns/${turnId}/cancel`, {
    method: 'POST',
  })
export const saveFeedback = (
  conversationId: string,
  turnId: string,
  kind: Feedback['kind'],
  note: string,
) =>
  request<Feedback>(`/api/workbench/conversations/${conversationId}/turns/${turnId}/feedback`, {
    method: 'PUT',
    body: JSON.stringify({ kind, note }),
  })

export async function downloadExport(): Promise<void> {
  const response = await fetch('/api/workbench/export', { credentials: 'include' })
  if (!response.ok) throw new Error(`导出失败：HTTP ${response.status}`)
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = 'grove-dialogue-workbench.json'
  link.click()
  URL.revokeObjectURL(href)
}

export { WorkbenchApiError }
