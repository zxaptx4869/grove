/** 来源库的接口响应类型：字段与后端 `SourceOut` / `AttachmentOut` / `CandidateOut` 一致。 */

export type SourceAttachment = {
  id: number;
  kind: string;
  position: number;
  mime_type: string | null;
  file_name: string | null;
  text_content: string | null;
  ocr_text: string | null;
};

export type SourceOut = {
  id: number;
  title: string;
  note: string | null;
  project_id: number | null;
  status: string;
  created_at: string;
  updated_at: string;
  attachments: SourceAttachment[];
  failure_reason: string | null;
  retry_count: number;
  /** 是否存在处理任务：等待处理 + 无任务表示处理未启动，不能靠等待时长推断。 */
  has_processing_task: boolean;
  project_locked: boolean;
  evidence_entry_count: number;
  pending_candidate_count: number;
  candidate_count: number;
};

export type CandidateOut = {
  id: number;
  candidate_kind: string;
  title: string;
  content: string;
  main_type: string;
  note: string | null;
  reason: string | null;
  status: string;
  recommended_node_id: number | null;
  node_reason: string | null;
  routing_status: string;
  relation_status: string;
  new_node_suggestion: { name: string; parent_id: number | null; reason: string | null } | null;
  node_alternatives: { node_id: number; reason: string }[];
};

/** 列表筛选：与原型「全部 / 未归属」两态对应。 */
export type SourceFilter = "all" | "unassigned";
