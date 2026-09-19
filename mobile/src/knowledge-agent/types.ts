/** 知识 Agent 原生端合同：只描述正式对话与只读 Entry 展示。 */

export type KnowledgeScopeType = "workspace" | "project";
export type RunStatus =
  | "waiting"
  | "processing"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";
export type DialogueLoopStatus =
  | "waiting"
  | "processing"
  | "completed"
  | "partial_completed"
  | "failed"
  | "cancelled"
  | "not_executed"
  | "unsupported";
export type ContextMode = "auto" | "continue" | "new_topic";
export type ContextDecision = "continue" | "new_topic" | "clarify";
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
  createdAt: string;
}

export type KnowledgeBlockKind =
  | "text"
  | "list"
  | "statistic"
  | "entry"
  | "evidence"
  | "candidate"
  | "candidate_text_only"
  | "insufficient";

export interface KnowledgeBlockSemantics {
  subject?: string;
  queryObject?: string;
  projectName?: string | null;
  displayName?: string;
  totalCount?: number | null;
  returnedCount?: number | null;
  completeness?: string;
  resultRole?: "candidate" | "authorized";
  relevanceScope?: string;
  groupBy?: string | null;
  groupByDisplayName?: string | null;
}

export interface KnowledgeBlockBucket {
  key?: string;
  label?: string;
  count?: number;
}

export interface KnowledgeAnswerBlock {
  /** 服务端未来可能增加类型；渲染器必须逐块安全降级。 */
  kind: KnowledgeBlockKind | (string & {});
  text?: string;
  label?: string;
  title?: string;
  content?: string;
  projectName?: string | null;
  nodePath?: string | null;
  sourceId?: number | null;
  sourceTitle?: string | null;
  entryId?: number | null;
  entryTitle?: string | null;
  value?: number | string | null;
  resultType?: string | null;
  completeness?: string | null;
  status?: string | null;
  items?: Record<string, unknown>[];
  buckets?: KnowledgeBlockBucket[];
  semantics?: KnowledgeBlockSemantics;
}

export interface KnowledgeRun extends KnowledgeScope {
  id: number;
  conversationId: number;
  runKind?: string;
  status: RunStatus;
  currentStep: string | null;
  userMessageId: number | null;
  assistantMessageId: number | null;
  cancelRequested: boolean;
  error: string | null;
  requestContextMode: ContextMode | null;
  contextDecision: ContextDecision | null;
  standaloneQuery: string | null;
  topicLabel: string | null;
  answer: { answer?: string | null; status?: string | null } | null;
  dialogueLoopStatus: DialogueLoopStatus | string | null;
  dialogueStage: string | null;
  dialogueBlocks: KnowledgeAnswerBlock[];
  canContinue: boolean;
  /** 客户端不得读取或修改内部续执行数据，只以 canContinue 决定入口。 */
  continuation: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface KnowledgeMessagePage {
  items: KnowledgeMessage[];
  nextCursor: string | null;
  runs: KnowledgeRun[];
}

/** `/api/entries/{id}` 返回的当前正式知识与当前来源摘要。 */
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
  evidences?: {
    id: number;
    sourceId: number;
    sourceTitle: string;
    quote: string | null;
  }[];
}

export interface KnowledgeRunSubmitRequest {
  clientMessageId: string;
  message: string;
  contextMode: ContextMode;
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

export function isRunActive(status: RunStatus | null | undefined): boolean {
  return status === "waiting" || status === "processing";
}

export function dialogueStatusOf(run: KnowledgeRun): string {
  if (run.dialogueLoopStatus) return run.dialogueLoopStatus;
  return run.status === "partial" ? "partial_completed" : run.status;
}
