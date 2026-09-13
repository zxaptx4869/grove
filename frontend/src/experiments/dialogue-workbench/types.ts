export type TurnStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'not_executed'
  | 'partial_completed'
  | 'unsupported'
  | 'denied'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface Feedback {
  kind: 'wrong' | 'misunderstood' | 'omitted'
  note: string
  saved_at: string
}

export interface ToolCall {
  tool?: string
  shared_tool?: string
  status?: string
  completeness?: string
  params?: Record<string, unknown>
  result_summary?: Record<string, unknown>
  result_handle?: string
  result_role?: 'candidate' | 'authorized'
  error?: string | null
  duration_ms?: number
}

export interface ModelCall {
  kind?: string
  provider?: string
  model?: string | null
  request_scope?: string
  duration_ms?: number
  estimated_input_tokens?: number | null
  actual_input_tokens?: number | null
  usage?: Record<string, number | string | null> | null
  finalize_only?: boolean
  error?: string | null
  error_kind?: string | null
}

export interface AnswerBlock {
  kind: 'text' | 'statistic' | 'list' | 'entry' | 'evidence' | 'insufficient'
  text?: string
  label?: string
  handle?: string
  result_type?: 'projects' | 'list' | 'directories' | 'statistic' | 'entries'
  position?: number
  title?: string
  content?: string
  project_name?: string
  node_path?: string
  value?: number | string | null
  buckets?: Array<{ label?: string; key?: string; count?: number }>
  items?: Array<Record<string, unknown>>
  status?: string
  completeness?: string
  source_id?: number
  entry_id?: number
  semantics?: {
    subject?: 'entries' | 'directories' | 'projects'
    query_object?: string
    project_id?: number | null
    project_name?: string | null
    project_scope?: string
    display_name?: string
    group_by?: string | null
    group_by_display_name?: string | null
    type_display_names?: string[]
    main_types?: string[]
    total_count?: number | null
    returned_count?: number | null
    has_more?: boolean
    completeness?: string
    result_role?: 'candidate' | 'authorized'
    relevance_scope?: 'direct'
    classification_counts?: {
      direct?: number
      indirect?: number
      unrelated?: number
    }
  }
}

export interface Turn {
  id: string
  request_id: string
  user_message: string
  status: TurnStatus
  stage: string
  created_at: string
  completed_at?: string | null
  answer: string
  blocks: AnswerBlock[]
  error?: string | null
  error_details?: Record<string, unknown> | null
  solve_error?: string | null
  solve_failure?: Record<string, unknown> | null
  solve_status?: TurnStatus
  duration_ms: number
  tool_calls: ToolCall[] | null
  model_calls: ModelCall[] | null
  budget?: Record<string, unknown> | null
  context?: Record<string, unknown> | null
  finalization?: Record<string, unknown> | null
  completion?: {
    status?: string
    reason_code?: string
    reason?: string
    incomplete_steps?: string[]
    can_continue?: boolean
    continuation?: {
      task_type?: string
      pending_steps?: Array<Record<string, unknown>>
      material_summary?: {
        answer_basis?: 'grove_material' | 'model_only'
        result_handles?: string[]
        evidence_handles?: string[]
        entry_ids?: number[]
        source_ids?: number[]
        fingerprint_count?: number
      }
      [key: string]: unknown
    } | null
  } | null
  persistence?: Record<string, unknown> | null
  isolation_check?: Record<string, unknown> | null
  feedback?: Feedback | null
}

export interface Conversation {
  id: string
  session_id: string
  title: string
  created_at: string
  updated_at: string
  read_only: boolean
  recovery_notice?: string | null
  turns: Turn[]
}

export interface WorkbenchSession {
  id: string
  active: boolean
  created_at: string
  experiment_version: string
  provider: string
  model: string
  offline: boolean
  conversations: Conversation[]
}

export interface WorkbenchState {
  metadata: {
    experiment_version: string
    prompt_version: string
    provider: string
    model: string
    offline: boolean
    snapshot_at: string
    snapshot_fingerprint: string
    status: string
    unsafe_reason?: string | null
    storage_path: string
    serial_execution: boolean
  }
  budget: {
    text_requests_per_batch: number
    embedding_requests_per_batch: number
    text_requests_per_turn: number
    embedding_requests_per_turn: number
    tool_calls_per_turn: number
    model_input_tokens_per_request: number
    input_estimate_soft_limit: number
    history_answer_chars_per_turn?: number
    history_input_tokens_target?: number
    solve_seconds_per_turn: number
    finalize_seconds: number
    used: { text_requests: number; embedding_requests: number }
    remaining: { text_requests: number; embedding_requests: number }
  }
  active_turn_id?: string | null
  sessions: WorkbenchSession[]
}
