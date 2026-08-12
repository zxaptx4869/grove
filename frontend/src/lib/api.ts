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
    // 会话基于 Cookie：跨源部署时也需携带凭据
    credentials: 'include',
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

export interface ProjectPayload {
  id: number
  name: string
  template: string
  node_count: number
  created_at: string
}

export interface TreeNodePayload {
  id: number
  name: string
  description: string | null
  position: number
  children: TreeNodePayload[]
}

export interface ProjectCreatePayload {
  name: string
  template: 'decoration' | 'empty'
}

export interface NodeCreatePayload {
  name: string
  description?: string | null
  parent_id?: number | null
}

export interface NodeUpdatePayload {
  name?: string
  description?: string | null
}

export const fetchProjects = () => request<ProjectPayload[]>('/api/projects')

export const createProject = (payload: ProjectCreatePayload) =>
  request<ProjectPayload>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const renameProject = (projectId: number, name: string) =>
  request<ProjectPayload>(`/api/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })

export const deleteProject = (projectId: number) =>
  request<{ ok: boolean }>(`/api/projects/${projectId}`, { method: 'DELETE' })

export const fetchProjectTree = (projectId: number) =>
  request<TreeNodePayload[]>(`/api/projects/${projectId}/tree`)

export const createNode = (projectId: number, payload: NodeCreatePayload) =>
  request<TreeNodePayload>(`/api/projects/${projectId}/nodes`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const updateNode = (
  projectId: number,
  nodeId: number,
  payload: NodeUpdatePayload,
) =>
  request<TreeNodePayload>(`/api/projects/${projectId}/nodes/${nodeId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteNode = (projectId: number, nodeId: number) =>
  request<{ ok: boolean }>(`/api/projects/${projectId}/nodes/${nodeId}`, {
    method: 'DELETE',
  })

export const reorderNodes = (
  projectId: number,
  parentId: number | null,
  orderedIds: number[],
) =>
  request<{ ok: boolean }>(`/api/projects/${projectId}/nodes/reorder`, {
    method: 'POST',
    body: JSON.stringify({ parent_id: parentId, ordered_ids: orderedIds }),
  })
