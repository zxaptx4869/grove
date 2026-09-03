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

export type RunKind = "answer" | "draft_candidate" | "entry_revision";

export type DraftStatus =
  | "generating"
  | "draft"
  | "confirming"
  | "confirmed"
  | "cancelled"
  | "failed";

export type RevisionDraftStatus =
  | "generating"
  | "draft"
  | "confirming"
  | "applied"
  | "cancelled"
  | "failed"
  | "undone";

export type RevisionExecutionStatus = "applied" | "undoing" | "undone";

export type ContextMode = "auto" | "continue" | "new_topic";
export type ContextDecision = "continue" | "new_topic" | "clarify";
export type AnswerMode = "auto" | "quick" | "investigate";
export type ResultMode = "auto" | "answer" | "entries";
export type ActualResultMode = "answer" | "entries";
export type BasisMode = "auto" | "knowledge_only";
export type ResultCompleteness = "complete" | "limited" | "unknown";
export type StructuredQueryToolStatus =
  | "completed"
  | "empty"
  | "limited"
  | "partial"
  | "denied"
  | "error"
  | "cancelled";
export type StructuredQuerySortField = "relevance" | "updated_at" | "created_at";
export type StructuredQuerySortDirection = "asc" | "desc";
export type StructuredQueryGroupField =
  | "main_type"
  | "info_nature"
  | "updated_month";
/** snake_case 对象键经 API 适配后使用 camelCase。 */
export type StructuredQueryGroupKey = "mainType" | "infoNature" | "updatedMonth";
export type ExternalMaterialStatus = "not_used" | "required_unavailable";
export type CompositeRequirementKind =
  | "explain"
  | "retrieve"
  | "aggregate"
  | "compare"
  | "recommend"
  | "other";
export type CompositeBasisPolicy =
  | "grove_only"
  | "grove_required"
  | "model_allowed"
  | "external_required";
export type CompositeCoverageStatus =
  | "answered"
  | "partial"
  | "insufficient"
  | "failed";
export type CompositeBasisKind =
  | "grove_evidence"
  | "structured_result"
  | "user_statement"
  | "model_knowledge"
  | "external_gap";

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
  /** 旧服务端响应可能缺失依据字段：按 null 兼容，不伪造依据。 */
  requestBasisMode?: BasisMode | null;
  answerBasis?: KnowledgeAnswerBasis | null;
  compositeAnswerPlan?: KnowledgeCompositeAnswerPlan | null;
  compositeAnswerCoverage?: KnowledgeCompositeAnswerCoverage | null;
  /** 旧服务端响应可能缺失结果形态字段：按 null 兼容（answer 语义）。 */
  requestResultMode?: ResultMode | null;
  actualResultMode?: ActualResultMode | null;
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
  /** 旧服务端响应可能缺失该集合：兼容按空处理。 */
  entryRevisionDrafts?: KnowledgeEntryRevisionDraft[];
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
  /** 复合回答的可选义务绑定；旧 point 缺省按空处理。 */
  requirementIds?: string[];
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

export interface KnowledgeCompositeRequirementSummary {
  id: string;
  order: number;
  summary: string;
  kind: CompositeRequirementKind;
  basisPolicy: CompositeBasisPolicy;
}

export interface KnowledgeCompositeAnswerPlan {
  schemaVersion: "v1";
  requirements: KnowledgeCompositeRequirementSummary[];
  inputKinds: ("retrieval" | "structured")[];
}

export interface KnowledgeCompositeRequirementCoverage {
  requirementId: string;
  summary: string;
  status: CompositeCoverageStatus;
  basisKinds: CompositeBasisKind[];
  note: string | null;
}

export interface KnowledgeCompositeAnswerCoverage {
  schemaVersion: "v1";
  requirements: KnowledgeCompositeRequirementCoverage[];
}

/** 服务端校验后的实际回答依据（AnswerBasis v1），展示层只读使用。 */
export interface KnowledgeAnswerBasisGrove {
  used: boolean;
  citationCount: number;
  entryCount: number;
}

export interface KnowledgeAnswerBasisUserStatements {
  messageIds: number[];
}

export interface KnowledgeAnswerBasisModelKnowledge {
  used: boolean;
}

export interface KnowledgeAnswerBasisExternalMaterial {
  status: ExternalMaterialStatus;
}

export interface KnowledgeAnswerBasis {
  schemaVersion: "v1";
  grove: KnowledgeAnswerBasisGrove;
  userStatements: KnowledgeAnswerBasisUserStatements;
  modelKnowledge: KnowledgeAnswerBasisModelKnowledge;
  externalMaterial: KnowledgeAnswerBasisExternalMaterial;
}

/** 结构化 Entry 查找结果项：正式知识对象快照，不是 Citation。 */
export interface KnowledgeEntryResultItem {
  entryId: number;
  title: string;
  excerpt: string;
  projectId: number | null;
  projectName: string | null;
  nodeId: number | null;
  nodePath: string | null;
  mainType: string | null;
  infoNature: string | null;
  updatedAt: string;
  sourceCount: number;
  /** 生成时内容/归属指纹：与当前 Entry 对比判断「已更新」。 */
  /** 生成时内容/归属指纹：与当前 Entry 对比判断「已更新」；旧快照可能缺失。 */
  /** 内容/归属指纹（服务端计算）；旧服务端响应可能缺失。 */
  fingerprint?: string | null;
  matchHint: string | null;
  matchedFields: string[];
}

export interface KnowledgeEntrySetSummary {
  schemaVersion: "v1";
  scopeType: KnowledgeScopeType;
  projectId: number | null;
  projectName: string | null;
  semanticQuery: string | null;
  mainTypes: string[];
  infoNatures: string[];
  updatedAtFrom: string | null;
  updatedAtTo: string | null;
  completeness: ResultCompleteness;
}

export interface KnowledgeEntrySort {
  field: StructuredQuerySortField;
  direction: StructuredQuerySortDirection;
  tieBreaker: "entry_id";
}

export interface KnowledgeCountResult {
  value: number;
  completeness: ResultCompleteness;
  status: StructuredQueryToolStatus;
}

export interface KnowledgeGroupBucket {
  key: string;
  count: number;
}

export interface KnowledgeGroupCountResult {
  groupBy: StructuredQueryGroupField;
  buckets: KnowledgeGroupBucket[];
  completeness: ResultCompleteness;
  status: StructuredQueryToolStatus;
  truncated: boolean;
}

export interface KnowledgeOutputCompleteness {
  entries: ResultCompleteness | null;
  count: ResultCompleteness | null;
  groupCount: Partial<Record<StructuredQueryGroupKey, ResultCompleteness>>;
}

export interface KnowledgeStructuredUpdatedAt {
  from: string | null;
  to: string | null;
}

export interface KnowledgeStructuredEntrySetPlan {
  schemaVersion: "v1";
  semanticQuery: string | null;
  mainTypes: string[];
  infoNatures: string[];
  updatedAt: KnowledgeStructuredUpdatedAt | null;
}

export interface KnowledgeStructuredEntriesOutput {
  kind: "entries";
  limit: number;
  sort: Pick<KnowledgeEntrySort, "field" | "direction">;
}

export interface KnowledgeStructuredCountOutput {
  kind: "count";
}

export interface KnowledgeStructuredGroupCountOutput {
  kind: "group_count";
  groupBy: StructuredQueryGroupField;
}

export type KnowledgeStructuredOutput =
  | KnowledgeStructuredEntriesOutput
  | KnowledgeStructuredCountOutput
  | KnowledgeStructuredGroupCountOutput;

export interface KnowledgeStructuredQueryPlan {
  schemaVersion: "v1";
  promptVersion: "v1";
  entrySet: KnowledgeStructuredEntrySetPlan;
  outputs: KnowledgeStructuredOutput[];
}

export interface KnowledgeEntryResultSnapshot {
  schemaVersion: string;
  query: string;
  status: "completed" | "partial";
  completeness: ResultCompleteness;
  items: KnowledgeEntryResultItem[];
  returnedCount: number;
  candidateLimit: number;
  warning: string | null;
  snapshotUpdatedAt: string;
  /** v2 字段均可缺省，兼容旧服务端与历史 v1 快照。 */
  setSummary?: KnowledgeEntrySetSummary | null;
  sort?: KnowledgeEntrySort | null;
  count?: KnowledgeCountResult | null;
  groupCounts?: KnowledgeGroupCountResult[];
  outputCompleteness?: KnowledgeOutputCompleteness | null;
  warnings?: string[];
}

export interface KnowledgeEntryResultsPage {
  schemaVersion: string;
  status: "completed" | "partial";
  completeness: ResultCompleteness;
  items: KnowledgeEntryResultItem[];
  returnedCount: number;
  totalInSnapshot: number;
  candidateLimit: number;
  hasMore: boolean;
  nextCursor: string | null;
  warning: string | null;
  snapshotUpdatedAt: string;
  setSummary?: KnowledgeEntrySetSummary | null;
  sort?: KnowledgeEntrySort | null;
  count?: KnowledgeCountResult | null;
  groupCounts?: KnowledgeGroupCountResult[];
  outputCompleteness?: KnowledgeOutputCompleteness | null;
  warnings?: string[];
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
  targetEntryId?: number | null;
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
  /** 旧服务端响应可能缺失依据字段：按 null 兼容。 */
  requestBasisMode?: BasisMode | null;
  answerBasis?: KnowledgeAnswerBasis | null;
  compositeAnswerPlan?: KnowledgeCompositeAnswerPlan | null;
  compositeAnswerCoverage?: KnowledgeCompositeAnswerCoverage | null;
  /** 旧服务端响应可能缺失结果形态与结构化结果：按 answer 语义兜底。 */
  requestResultMode?: ResultMode | null;
  actualResultMode?: ActualResultMode | null;
  currentRound: number;
  inputContextVersionId: number | null;
  outputContextVersionId: number | null;
  contextDegraded: boolean;
  fallbackSummary: FallbackSummary | null;
  investigationSummary: InvestigationSummary | null;
  structuredQueryPlan?: KnowledgeStructuredQueryPlan | null;
  answer: KnowledgeAnswer | null;
  entryResult?: KnowledgeEntryResultSnapshot | null;
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

/** 单 Entry 修订：服务端按 base snapshot 计算的字段差异。 */
export interface KnowledgeRevisionFieldDiff {
  field: string;
  label: string;
  before: string | null;
  after: string | null;
}

export interface KnowledgeRevisionExecution {
  id: number;
  draftId: number;
  entryId: number | null;
  status: RevisionExecutionStatus;
  beforeVersionNumber: number | null;
  afterVersionNumber: number | null;
  addedEvidenceCount: number;
  error: string | null;
  undoneAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeEntryRevisionDraft {
  id: number;
  conversationId: number;
  operationRunId: number;
  sourceRunId: number | null;
  targetEntryId: number | null;
  targetProjectId: number | null;
  targetProjectName: string | null;
  instruction: string;
  status: RevisionDraftStatus;
  title: string | null;
  content: string | null;
  mainType: string | null;
  infoNature: string | null;
  applicableCondition: string | null;
  note: string | null;
  changeSummary: string | null;
  reason: string | null;
  selectedEvidenceHandles: string[];
  evidenceSummaries: KnowledgeDraftEvidence[];
  changedFields: KnowledgeRevisionFieldDiff[];
  generationDegraded: boolean;
  generationError: string | null;
  execution: KnowledgeRevisionExecution | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeRevisionEntry {
  id: number;
  title: string;
  projectId: number;
  projectName: string | null;
  nodeId: number;
  nodeName: string | null;
  versionNumber: number | null;
  updatedAt: string;
}

/** 引用弹窗展示的当前正式知识（服务端 /api/entries/{id} 归一化结果）。 */
export interface KnowledgeEntryCurrent {
  id: number;
  projectId: number;
  nodeId: number;
  nodeName: string;
  title: string;
  content: string;
  mainType: string;
  infoNature: string | null;
  applicableCondition: string | null;
  note: string | null;
  createdAt: string;
  updatedAt: string;
  /** 生成时内容/归属指纹：与当前 Entry 对比判断「已更新」；旧快照可能缺失。 */
  fingerprint?: string | null;
  /** 当前 Entry 的真实来源摘要（服务端 /api/entries/{id} 归一化结果）。 */
  evidences?: {
    id: number;
    sourceId: number;
    sourceTitle: string;
    quote: string | null;
  }[];
}

export interface KnowledgeRevisionActionRequest {
  clientMessageId: string;
  sourceRunId: number;
  targetEntryId: number;
  instruction: string;
}

export interface KnowledgeRevisionAction {
  userMessage: KnowledgeMessage;
  run: KnowledgeRun;
  draft: KnowledgeEntryRevisionDraft;
}

export interface KnowledgeRevisionEditRequest {
  title?: string | null;
  content?: string | null;
  mainType?: string | null;
  infoNature?: string | null;
  applicableCondition?: string | null;
  note?: string | null;
  changeSummary?: string | null;
}

export interface KnowledgeRevisionConfirmRequest {
  clientOperationId: string;
}

export interface KnowledgeRevisionConfirm {
  draft: KnowledgeEntryRevisionDraft;
  execution: KnowledgeRevisionExecution;
  entry: KnowledgeRevisionEntry;
}

export interface KnowledgeRevisionUndoRequest {
  clientOperationId: string;
}

export interface KnowledgeRevisionUndo {
  draft: KnowledgeEntryRevisionDraft;
  execution: KnowledgeRevisionExecution;
  entry: KnowledgeRevisionEntry;
}

export interface KnowledgeRunSubmitRequest {
  clientMessageId: string;
  message: string;
  contextMode: ContextMode;
  answerMode: AnswerMode;
  resultMode: ResultMode;
  /** 新客户端显式提交依据模式；缺省由服务端按 knowledge_only 兼容。 */
  basisMode: BasisMode;
  /** 模式纠正时由服务端恢复原问题、范围和输入工作集。 */
  sourceRunId?: number;
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
