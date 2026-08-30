/** 知识 Agent 领域类型：与后端 knowledge_agent schema 保持一一对应。 */

export type KnowledgeScopeType = "workspace" | "project";

export type RunStatus =
  | "waiting"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export type AnswerStatus =
  | "completed"
  | "partial"
  | "insufficient"
  | "failed"
  | "clarification";

export type RunKind = "answer" | "draft_candidate";

export type DraftStatus =
  | "generating"
  | "draft"
  | "confirming"
  | "confirmed"
  | "cancelled"
  | "failed";

export type ContextMode = "auto" | "continue" | "new_topic";
export type ContextDecision = "continue" | "new_topic" | "clarify";
export type AnswerMode = "auto" | "quick" | "investigate";

export type InvestigationStopReason =
  | "controller_complete"
  | "insufficient"
  | "no_progress"
  | "max_rounds"
  | "query_budget"
  | "entry_budget"
  | "evidence_budget"
  | "cancelled"
  | "failed";

export type MessageType = "user" | "assistant" | "scope_change";
export type MessageRole = "user" | "assistant" | "system";

export interface KnowledgeScope {
  scopeType: KnowledgeScopeType;
  projectId?: number | null;
  projectName?: string | null;
}

export interface KnowledgeConversation extends KnowledgeScope {
  id: number;
  title: string;
  activeTopicLabel: string | null;
  activeContextVersionId: number | null;
  activeEntryCount: number;
  recentRunId: number | null;
  recentRunStatus: RunStatus | null;
  recentRunCurrentStep: string | null;
  recentRunUpdatedAt: string | null;
  lastActivityAt: string;
  createdAt: string;
}

export interface KnowledgeMessage extends KnowledgeScope {
  id: number;
  conversationId: number;
  role: MessageRole;
  messageType: MessageType;
  content: string;
  clientMessageId: string | null;
  runId: number | null;
  requestContextMode: ContextMode | null;
  contextDecision: ContextDecision | null;
  standaloneQuery: string | null;
  topicLabel: string | null;
  requestAnswerMode: AnswerMode | null;
  actualAnswerMode: AnswerMode | null;
  currentRound: number;
  inputContextVersionId: number | null;
  outputContextVersionId: number | null;
  createdAt: string;
}

export interface KnowledgeMessagePage {
  items: KnowledgeMessage[];
  nextCursor: string | null;
  runs: KnowledgeRun[];
  candidateDrafts: KnowledgeCandidateDraft[];
}

export interface KnowledgeRunCitation extends KnowledgeScope {
  evidenceId: number;
  evidenceHandle: string;
  entryId: number;
  entryTitle: string;
  sourceId: number;
  sourceTitle: string;
  attachmentId: number | null;
  quote: string;
  nodePath: string | null;
}

export interface KnowledgeConflict {
  summary: string;
  evidenceIdA: number;
  entryIdA: number;
  entryTitleA: string;
  evidenceIdB: number;
  entryIdB: number;
  entryTitleB: string;
  citationA: KnowledgeRunCitation | null;
  citationB: KnowledgeRunCitation | null;
}

export interface KnowledgeAnswerPoint {
  /** 可选分组标题（如「客厅/卧室区域」）；服务端重验后输出。 */
  section: string | null;
  text: string;
  /** 该要点采用的逐条引用（服务端重验后的当前可核验 Evidence）。 */
  citations: KnowledgeRunCitation[];
}

export interface KnowledgeAnswer {
  answer: string;
  status: AnswerStatus;
  insufficientNote: string | null;
  /** v3 可选结构化要点；历史回答与旧模型输出缺省为空。 */
  points?: KnowledgeAnswerPoint[];
  citations: KnowledgeRunCitation[];
  conflicts: KnowledgeConflict[];
}

export interface FallbackStage {
  purpose: string;
  isFallback: boolean;
  provider: string | null;
  model: string | null;
  error: string | null;
}

export interface FallbackSummary {
  hasFallback: boolean;
  stages: FallbackStage[];
}

export interface InvestigationSummary {
  requestedAnswerMode: AnswerMode;
  actualAnswerMode: AnswerMode | null;
  roundsCompleted: number;
  queriesExecuted: number;
  stopReason: InvestigationStopReason | null;
  coverage: string[];
  gaps: string[];
  conflicts: string[];
}

export interface KnowledgeRun extends KnowledgeScope {
  id: number;
  conversationId: number;
  /** 旧客户端/历史缓存可能缺省：缺省按 answer 处理 */
  runKind?: RunKind;
  sourceRunId?: number | null;
  status: RunStatus;
  currentStep: string | null;
  userMessageId: number | null;
  assistantMessageId: number | null;
  cancelRequested: boolean;
  retryCount: number;
  maxRetries: number;
  error: string | null;
  requestContextMode: ContextMode | null;
  contextDecision: ContextDecision | null;
  standaloneQuery: string | null;
  topicLabel: string | null;
  requestAnswerMode: AnswerMode | null;
  actualAnswerMode: AnswerMode | null;
  currentRound: number;
  inputContextVersionId: number | null;
  outputContextVersionId: number | null;
  contextDegraded: boolean;
  fallbackSummary: FallbackSummary | null;
  investigationSummary: InvestigationSummary | null;
  answer: KnowledgeAnswer | null;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeDraftEvidence {
  handle: string;
  entryId: number;
  entryTitle: string;
  sourceId: number;
  sourceTitle: string;
  quote: string;
}

export interface KnowledgeCandidateDraft {
  id: number;
  conversationId: number;
  operationRunId: number;
  sourceRunId: number | null;
  targetProjectId: number | null;
  targetProjectName: string | null;
  status: DraftStatus;
  title: string | null;
  content: string | null;
  mainType: string | null;
  infoNature: string | null;
  evidenceHandles: string[];
  evidenceSummaries: KnowledgeDraftEvidence[];
  generationDegraded: boolean;
  generationError: string | null;
  confirmedCandidateId: number | null;
  /** 确认后目录推荐/关系判断状态：pending 表示对应辅助步骤尚未完成。 */
  routingStatus: string | null;
  relationStatus: string | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface CandidateReceipt {
  id: number;
  title: string;
  status: string;
  sourceId: number;
  routingStatus: string;
  recommendedNodeId: number | null;
  relationStatus: string;
  relationTargetEntryId: number | null;
  createdAt: string;
}

export interface KnowledgeDraftActionRequest {
  clientMessageId: string;
  sourceRunId: number;
  targetProjectId?: number | null;
}

export interface KnowledgeDraftAction {
  userMessage: KnowledgeMessage;
  run: KnowledgeRun;
  draft: KnowledgeCandidateDraft;
}

export interface KnowledgeDraftEditRequest {
  title?: string | null;
  content?: string | null;
  mainType?: string | null;
  infoNature?: string | null;
}

export interface KnowledgeDraftConfirmRequest {
  clientOperationId: string;
}

export interface KnowledgeDraftConfirm {
  draft: KnowledgeCandidateDraft;
  candidate: CandidateReceipt;
}

export interface KnowledgeRunSubmitRequest {
  clientMessageId: string;
  message: string;
  contextMode: ContextMode;
  answerMode: AnswerMode;
}

export interface KnowledgeRunSubmit {
  userMessage: KnowledgeMessage;
  run: KnowledgeRun;
}

export interface KnowledgeScopeChangeRequest {
  scopeType: KnowledgeScopeType;
  projectId?: number | null;
  projectName?: string | null;
}

export type RunTerminalStatus = Extract<
  RunStatus,
  "completed" | "partial" | "failed" | "cancelled"
>;

export function isRunActive(status: RunStatus | null | undefined): boolean {
  return status === "waiting" || status === "processing";
}
