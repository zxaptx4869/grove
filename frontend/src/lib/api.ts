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

export type ProjectStatus = 'active' | 'paused' | 'completed' | 'archived'

export interface ProjectPayload {
  id: number
  name: string
  description: string | null
  status: ProjectStatus
  template: string
  node_count: number
  created_at: string
}

export interface TreeNodePayload {
  id: number
  name: string
  description: string | null
  position: number
  entry_count: number
  children: TreeNodePayload[]
}

export interface ProjectCreatePayload {
  name: string
  description?: string | null
}

export interface NodeCreatePayload {
  name: string
  description?: string | null
  parent_id?: number | null
}

export interface NodeUpdatePayload {
  name?: string
  description?: string | null
  parent_id?: number | null
}

export const fetchProjects = (status?: ProjectStatus | 'all') =>
  request<ProjectPayload[]>(
    `/api/projects${status && status !== 'all' ? `?status_filter=${status}` : ''}`,
  )

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

export const updateProject = (projectId: number, payload: { name?: string; description?: string | null }) =>
  request<ProjectPayload>(`/api/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const updateProjectStatus = (projectId: number, status: ProjectStatus) =>
  request<ProjectPayload>(`/api/projects/${projectId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
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

export type AttachmentKind = 'image' | 'text'

export type SourceStatus = 'waiting' | 'processing' | 'done' | 'failed'

export interface AttachmentPayload {
  id: number
  kind: AttachmentKind
  position: number
  mime_type: string | null
  file_name: string | null
  text_content: string | null
  ocr_text?: string | null
}

export interface SourcePayload {
  id: number
  title: string
  note: string | null
  project_id: number | null
  status: SourceStatus
  recommended_project_id: number | null
  project_recommendation_reason: string | null
  created_at: string
  updated_at: string
  attachments: AttachmentPayload[]
}

export const fetchSources = (params?: { projectId?: number; unassigned?: boolean }) => {
  const search = new URLSearchParams()
  if (params?.projectId != null) search.set('project_id', String(params.projectId))
  if (params?.unassigned) search.set('unassigned', 'true')
  const query = search.toString()
  return request<SourcePayload[]>(`/api/sources${query ? `?${query}` : ''}`)
}

export const createSource = async (formData: FormData): Promise<SourcePayload> => {
  const response = await fetch(`${API_BASE_URL}/api/sources`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
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
  return (await response.json()) as SourcePayload
}

export const updateSource = (
  sourceId: number,
  payload: { note?: string | null; project_id?: number | null },
) =>
  request<SourcePayload>(`/api/sources/${sourceId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const deleteSource = (sourceId: number) =>
  request<{ ok: boolean }>(`/api/sources/${sourceId}`, { method: 'DELETE' })

export const triggerProcessing = (sourceId: number) =>
  request<SourcePayload>(`/api/sources/${sourceId}/process`, { method: 'POST' })

export const sourceImageUrl = (sourceId: number, attachmentId: number) =>
  `${API_BASE_URL}/api/sources/${sourceId}/attachments/${attachmentId}/file`

export type ProjectContextStatus = 'pending' | 'ready' | 'failed'

export interface ProjectContextCorrectionsPayload {
  project_summary: string | null
  current_focus: string | null
}

export interface EntryRecentPayload {
  entry_id: number
  title: string
  node_name: string
  updated_at: string | null
}

export interface EntryTopNodeCoveragePayload {
  node_id: number
  name: string
  count: number
}

export interface EntrySummaryPayload {
  total: number
  by_type: Record<string, number>
  by_top_node: EntryTopNodeCoveragePayload[]
  recent: EntryRecentPayload[]
  truncated_count: number
}

export interface ProjectContextPayload {
  project_id: number
  user_description: string | null
  project_summary: string | null
  current_focus: string | null
  directory_topics: string[]
  lifecycle_status: ProjectStatus
  generated_at: string | null
  version: number
  last_update_reason: string | null
  entries_summary: EntrySummaryPayload | null
  recent_themes: string[]
  provider: string | null
  model: string | null
  is_fallback: boolean
  status: ProjectContextStatus
  error: string | null
  corrections: ProjectContextCorrectionsPayload
}

export interface ProjectContextCorrectionPayload {
  project_summary?: string | null
  current_focus?: string | null
}

export const fetchProjectContext = (projectId: number) =>
  request<ProjectContextPayload>(`/api/projects/${projectId}/context`)

export const updateProjectContext = (
  projectId: number,
  payload: ProjectContextCorrectionPayload,
) =>
  request<ProjectContextPayload>(`/api/projects/${projectId}/context`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const refreshProjectContext = (projectId: number) =>
  request<ProjectContextPayload>(`/api/projects/${projectId}/context/refresh`, {
    method: 'POST',
  })

export interface AIProviderSettingsPayload {
  text_provider: string
  text_model: string
  text_configured: boolean
  text_key_tail: string | null
  text_available: boolean
  vision_provider: string
  vision_model: string
  vision_configured: boolean
  vision_key_tail: string | null
  vision_available: boolean
}

export interface ConnectionTestPayload {
  ok: boolean
  message: string
}

export interface ProviderSettingsSavePayload {
  api_key: string
  model?: string | null
}

export const fetchAISettings = () =>
  request<AIProviderSettingsPayload>('/api/settings/ai')

export const saveTextAISettings = (payload: ProviderSettingsSavePayload) =>
  request<AIProviderSettingsPayload>('/api/settings/ai/text', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const saveVisionAISettings = (payload: ProviderSettingsSavePayload) =>
  request<AIProviderSettingsPayload>('/api/settings/ai/vision', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })

export const clearTextAISettings = () =>
  request<AIProviderSettingsPayload>('/api/settings/ai/text', { method: 'DELETE' })

export const clearVisionAISettings = () =>
  request<AIProviderSettingsPayload>('/api/settings/ai/vision', { method: 'DELETE' })

export const testTextAISettings = () =>
  request<ConnectionTestPayload>('/api/settings/ai/text/test', { method: 'POST' })

export const testVisionAISettings = () =>
  request<ConnectionTestPayload>('/api/settings/ai/vision/test', { method: 'POST' })

export interface CandidateEvidencePayload {
  attachment_id: number
  quote: string
}

export interface NodeAlternativePayload {
  node_id: number
  reason: string
}

export interface NewNodeSuggestionPayload {
  name: string
  parent_id: number | null
  reason: string | null
}

export type RoutingStatus = 'pending' | 'recommended' | 'needs_review' | 'no_suitable'

export type RelationStatus = 'pending' | 'new' | 'duplicate' | 'supplement' | 'conflict'

export interface EntryRevisionDraftPayload {
  title: string | null
  content: string | null
  main_type: 'knowledge' | 'method' | 'parameter' | 'reminder' | null
  info_nature: string | null
  applicable_condition: string | null
  note: string | null
  change_summary: string
}

export interface CandidatePayload {
  id: number
  source_id: number
  candidate_kind: 'recommended' | 'other'
  title: string
  content: string
  main_type: 'knowledge' | 'method' | 'parameter' | 'reminder'
  info_nature: string | null
  applicable_condition: string | null
  note: string | null
  evidence: CandidateEvidencePayload[]
  reason: string | null
  risk_flags: string[]
  status: CandidateDecisionStatus
  recommended_node_id: number | null
  node_alternatives: NodeAlternativePayload[]
  node_reason: string | null
  routing_status: RoutingStatus
  new_node_suggestion: NewNodeSuggestionPayload | null
  relation_status: RelationStatus
  relation_target_entry_id: number | null
  relation_target_entry_title: string | null
  relation_target_entry_node_name: string | null
  relation_reason: string | null
  revision_draft: EntryRevisionDraftPayload | null
}

export const fetchSourceCandidates = (sourceId: number) =>
  request<CandidatePayload[]>(`/api/sources/${sourceId}/candidates`)

export type CandidateDecisionStatus = 'pending' | 'confirmed' | 'rejected'

export interface ReviewSourcePayload {
  id: number
  title: string
  note: string | null
  status: SourceStatus
  review_status: string
  pending_candidate_count: number
  created_at: string
}

export interface CandidateUpdatePayload {
  title?: string | null
  content?: string | null
  main_type?: 'knowledge' | 'method' | 'parameter' | 'reminder' | null
  info_nature?: 'fact' | 'experience' | 'advice' | 'speculation' | 'other' | null
  applicable_condition?: string | null
  note?: string | null
}

export const fetchSource = (sourceId: number) =>
  request<SourcePayload>(`/api/sources/${sourceId}`)

export const fetchReviewSources = (projectId: number) =>
  request<ReviewSourcePayload[]>(`/api/projects/${projectId}/review/sources`)

export const updateCandidate = (candidateId: number, payload: CandidateUpdatePayload) =>
  request<CandidatePayload>(`/api/candidates/${candidateId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const decideCandidate = (candidateId: number, status: CandidateDecisionStatus) =>
  request<CandidatePayload>(`/api/candidates/${candidateId}/decision`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })

export const batchDecideCandidates = (
  sourceId: number,
  candidateIds: number[],
  status: 'confirmed' | 'rejected',
) =>
  request<CandidatePayload[]>(`/api/sources/${sourceId}/candidates/batch-decision`, {
    method: 'POST',
    body: JSON.stringify({ candidate_ids: candidateIds, status }),
  })

export type ReviewBand = 'quick' | 'detailed'

export interface ReviewCandidatePayload extends CandidatePayload {
  source_title: string
  source_note: string | null
  review_band: ReviewBand
  user_node_id: number | null
}

export interface ProjectBatchDecisionPayload {
  candidate_ids: number[]
  action: 'confirm' | 'reject'
  node_id?: number | null
}

export interface ProjectBatchDecisionResult {
  candidate_id: number
  status: 'confirmed' | 'rejected' | 'failed'
  error: string | null
}

export const fetchReviewCandidates = (projectId: number) =>
  request<ReviewCandidatePayload[]>(`/api/projects/${projectId}/review/candidates`)

export const batchDecideProjectCandidates = (
  projectId: number,
  payload: ProjectBatchDecisionPayload,
) =>
  request<ProjectBatchDecisionResult[]>(
    `/api/projects/${projectId}/review/candidates/batch-decision`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )

export const batchUpdateCandidatesDirectory = (
  projectId: number,
  payload: { candidate_ids: number[]; node_id: number },
) =>
  request<{ updated: number }>(
    `/api/projects/${projectId}/review/candidates/batch-update-directory`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )

export interface EntryEvidencePayload {
  id: number
  source_id: number
  attachment_id: number | null
  quote: string | null
  source_title: string
}

export interface EntryPayload {
  id: number
  project_id: number
  node_id: number
  node_name: string
  title: string
  content: string
  main_type: 'knowledge' | 'method' | 'parameter' | 'reminder'
  info_nature: string | null
  applicable_condition: string | null
  note: string | null
  created_at: string
  updated_at: string
  evidences: EntryEvidencePayload[]
}

export interface SearchEntryPayload extends EntryPayload {
  project_name: string
}

export interface EntryUpdatePayload {
  title?: string | null
  content?: string | null
  main_type?: 'knowledge' | 'method' | 'parameter' | 'reminder' | null
  info_nature?: 'fact' | 'experience' | 'advice' | 'speculation' | 'other' | null
  applicable_condition?: string | null
  note?: string | null
  node_id?: number | null
}

export const archiveCandidate = (candidateId: number, nodeId: number) =>
  request<EntryPayload>(`/api/candidates/${candidateId}/archive`, {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId }),
  })

export interface ArchiveCandidateWithNewNodePayload {
  name: string
  parent_id?: number | null
  description?: string | null
}

export const archiveCandidateWithNewNode = (
  candidateId: number,
  payload: ArchiveCandidateWithNewNodePayload,
) =>
  request<EntryPayload>(`/api/candidates/${candidateId}/archive-with-new-node`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface AddEvidencePayload {
  entry_id: number
}

export const addEvidence = (candidateId: number, payload: AddEvidencePayload) =>
  request<EntryPayload>(`/api/candidates/${candidateId}/add-evidence`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export interface ApplyRevisionPayload {
  entry_id: number
  title?: string | null
  content?: string | null
  main_type?: 'knowledge' | 'method' | 'parameter' | 'reminder' | null
  info_nature?: 'fact' | 'experience' | 'advice' | 'speculation' | 'other' | null
  applicable_condition?: string | null
  note?: string | null
}

export const applyRevision = (candidateId: number, payload: ApplyRevisionPayload) =>
  request<EntryPayload>(`/api/candidates/${candidateId}/apply-revision`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const fetchEntry = (entryId: number) => request<EntryPayload>(`/api/entries/${entryId}`)

export const updateEntry = (entryId: number, payload: EntryUpdatePayload) =>
  request<EntryPayload>(`/api/entries/${entryId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })

export const fetchNodeEntries = (
  projectId: number,
  nodeId: number,
  scope: 'direct' | 'descendants' = 'direct',
) =>
  request<EntryPayload[]>(
    `/api/projects/${projectId}/nodes/${nodeId}/entries?scope=${scope}`,
  )

export const searchEntries = (q: string, projectId?: number) => {
  const params = new URLSearchParams({ q })
  if (projectId != null) params.set('project_id', String(projectId))
  return request<SearchEntryPayload[]>(`/api/search?${params.toString()}`)
}
