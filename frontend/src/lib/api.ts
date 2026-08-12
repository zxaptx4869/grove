/** 后端 API 客户端：骨架阶段仅提供健康检查。 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export interface HealthPayload {
  status: string
  service?: string
  version?: string
}

/** 调用后端 GET /healthz。 */
export async function fetchHealth(): Promise<HealthPayload> {
  const response = await fetch(`${API_BASE_URL}/healthz`)
  if (!response.ok) {
    throw new Error(`健康检查失败：HTTP ${response.status}`)
  }
  return (await response.json()) as HealthPayload
}

export interface UserPayload {
  id: number
  username: string
  created_at: string
}

export interface WorkspacePayload {
  id: number
  name: string
}

export interface MePayload {
  user: UserPayload
  workspace: WorkspacePayload
}

export interface CredentialsPayload {
  username: string
  password: string
}

/** API 请求错误：携带 HTTP 状态码与后端 detail。 */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const data = (await response.json()) as { detail?: string }
      if (data?.detail) detail = String(data.detail)
    } catch {
      // 响应体不是 JSON 时保留默认信息
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

export const registerUser = (payload: CredentialsPayload) =>
  request<UserPayload>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const loginUser = (payload: CredentialsPayload) =>
  request<UserPayload>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const logoutUser = () =>
  request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' })

export const fetchMe = () => request<MePayload>('/api/me')
