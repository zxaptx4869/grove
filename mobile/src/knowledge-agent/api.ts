/** 知识 Agent Bearer API 客户端：统一注入会话令牌并分类错误。 */

import { request } from "@/src/api";
import {
  classifyKnowledgeAgentError,
  KnowledgeAgentError,
} from "@/src/knowledge-agent/errors";
import type {
  KnowledgeCandidateDraft,
  KnowledgeDraftAction,
  KnowledgeDraftActionRequest,
  KnowledgeDraftConfirm,
  KnowledgeDraftConfirmRequest,
  KnowledgeDraftEditRequest,
  KnowledgeEntryRevisionDraft,
  KnowledgeRevisionAction,
  KnowledgeRevisionActionRequest,
  KnowledgeRevisionConfirm,
  KnowledgeRevisionConfirmRequest,
  KnowledgeRevisionEditRequest,
  KnowledgeRevisionUndo,
  KnowledgeRevisionUndoRequest,
  KnowledgeConversation,
  KnowledgeMessagePage,
  KnowledgeRun,
  KnowledgeRunSubmit,
  KnowledgeRunSubmitRequest,
  KnowledgeScopeChangeRequest,
} from "@/src/knowledge-agent/types";

const MESSAGE_PAGE_LIMIT = 30;

/** 后端返回 snake_case JSON；统一转换为前端 camelCase 类型。 */
function toCamel(key: string): string {
  return key.replace(/_([a-z])/g, (_match, letter: string) =>
    letter.toUpperCase(),
  );
}

function normalizePayload<T>(value: unknown): T {
  if (Array.isArray(value)) {
    return value.map((item) => normalizePayload(item)) as T;
  }
  if (value !== null && typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      output[toCamel(key)] = normalizePayload(item);
    }
    return output as T;
  }
  return value as T;
}

function serializeScope(
  scope: KnowledgeScopeChangeRequest,
): Record<string, unknown> {
  return {
    scope_type: scope.scopeType,
    project_id: scope.projectId ?? null,
  };
}

function serializeSubmit(
  payload: KnowledgeRunSubmitRequest,
): Record<string, unknown> {
  return {
    client_message_id: payload.clientMessageId,
    message: payload.message,
    context_mode: payload.contextMode,
    answer_mode: payload.answerMode,
  };
}

function serializeDraftAction(
  payload: KnowledgeDraftActionRequest,
): Record<string, unknown> {
  return {
    client_message_id: payload.clientMessageId,
    source_run_id: payload.sourceRunId,
    target_project_id: payload.targetProjectId ?? null,
  };
}

function serializeDraftEdit(
  payload: KnowledgeDraftEditRequest,
): Record<string, unknown> {
  return {
    title: payload.title ?? null,
    content: payload.content ?? null,
    main_type: payload.mainType ?? null,
    info_nature: payload.infoNature ?? null,
  };
}

function serializeDraftConfirm(
  payload: KnowledgeDraftConfirmRequest,
): Record<string, unknown> {
  return {
    client_operation_id: payload.clientOperationId,
  };
}

function serializeRevisionAction(
  payload: KnowledgeRevisionActionRequest,
): Record<string, unknown> {
  return {
    client_message_id: payload.clientMessageId,
    source_run_id: payload.sourceRunId,
    target_entry_id: payload.targetEntryId,
    instruction: payload.instruction,
  };
}

function serializeRevisionEdit(
  payload: KnowledgeRevisionEditRequest,
): Record<string, unknown> {
  return {
    title: payload.title ?? null,
    content: payload.content ?? null,
    main_type: payload.mainType ?? null,
    info_nature: payload.infoNature ?? null,
    applicable_condition: payload.applicableCondition ?? null,
    note: payload.note ?? null,
    change_summary: payload.changeSummary ?? null,
  };
}

function serializeRevisionConfirm(
  payload: KnowledgeRevisionConfirmRequest,
): Record<string, unknown> {
  return {
    client_operation_id: payload.clientOperationId,
  };
}

function serializeRevisionUndo(
  payload: KnowledgeRevisionUndoRequest,
): Record<string, unknown> {
  return {
    client_operation_id: payload.clientOperationId,
  };
}

function withToken(
  token: string | null,
  run: (token: string) => Promise<unknown>,
): Promise<unknown> {
  if (!token) {
    return Promise.reject(
      new KnowledgeAgentError({
        kind: "auth",
        message: "登录已失效，请重新登录",
        retryable: false,
      }),
    );
  }
  return run(token)
    .then((result) => normalizePayload(result))
    .catch((error: unknown) => {
      throw classifyKnowledgeAgentError(error);
    });
}

export const knowledgeAgentApi = {
  listConversations(token: string): Promise<KnowledgeConversation[]> {
    return withToken(token, (t) =>
      request<KnowledgeConversation[]>("/api/knowledge-agent/conversations", {}, t),
    ) as Promise<KnowledgeConversation[]>;
  },

  createConversation(
    token: string,
    scope: KnowledgeScopeChangeRequest,
  ): Promise<KnowledgeConversation> {
    return withToken(token, (t) =>
      request<KnowledgeConversation>(
        "/api/knowledge-agent/conversations",
        { method: "POST", body: JSON.stringify(serializeScope(scope)) },
        t,
      ),
    ) as Promise<KnowledgeConversation>;
  },

  getConversation(token: string, conversationId: number): Promise<KnowledgeConversation> {
    return withToken(token, (t) =>
      request<KnowledgeConversation>(
        `/api/knowledge-agent/conversations/${conversationId}`,
        {},
        t,
      ),
    ) as Promise<KnowledgeConversation>;
  },

  changeScope(
    token: string,
    conversationId: number,
    scope: KnowledgeScopeChangeRequest,
  ): Promise<KnowledgeConversation> {
    return withToken(token, (t) =>
      request<KnowledgeConversation>(
        `/api/knowledge-agent/conversations/${conversationId}/scope`,
        { method: "PATCH", body: JSON.stringify(serializeScope(scope)) },
        t,
      ),
    ) as Promise<KnowledgeConversation>;
  },

  listMessages(
    token: string,
    conversationId: number,
    cursor: string | null,
  ): Promise<KnowledgeMessagePage> {
    const query = cursor
      ? `?cursor=${encodeURIComponent(cursor)}&limit=${MESSAGE_PAGE_LIMIT}`
      : `?limit=${MESSAGE_PAGE_LIMIT}`;
    return withToken(token, (t) =>
      request<KnowledgeMessagePage>(
        `/api/knowledge-agent/conversations/${conversationId}/messages${query}`,
        {},
        t,
      ),
    ) as Promise<KnowledgeMessagePage>;
  },

  submitMessage(
    token: string,
    conversationId: number,
    payload: KnowledgeRunSubmitRequest,
  ): Promise<KnowledgeRunSubmit> {
    return withToken(token, (t) =>
      request<KnowledgeRunSubmit>(
        `/api/knowledge-agent/conversations/${conversationId}/messages`,
        { method: "POST", body: JSON.stringify(serializeSubmit(payload)) },
        t,
      ),
    ) as Promise<KnowledgeRunSubmit>;
  },

  submitDraftAction(
    token: string,
    conversationId: number,
    payload: KnowledgeDraftActionRequest,
  ): Promise<KnowledgeDraftAction> {
    return withToken(token, (t) =>
      request<KnowledgeDraftAction>(
        `/api/knowledge-agent/conversations/${conversationId}/drafts`,
        { method: "POST", body: JSON.stringify(serializeDraftAction(payload)) },
        t,
      ),
    ) as Promise<KnowledgeDraftAction>;
  },

  getDraft(token: string, draftId: number): Promise<KnowledgeCandidateDraft> {
    return withToken(token, (t) =>
      request<KnowledgeCandidateDraft>(
        `/api/knowledge-agent/drafts/${draftId}`,
        {},
        t,
      ),
    ) as Promise<KnowledgeCandidateDraft>;
  },

  editDraft(
    token: string,
    draftId: number,
    payload: KnowledgeDraftEditRequest,
  ): Promise<KnowledgeCandidateDraft> {
    return withToken(token, (t) =>
      request<KnowledgeCandidateDraft>(
        `/api/knowledge-agent/drafts/${draftId}`,
        { method: "PATCH", body: JSON.stringify(serializeDraftEdit(payload)) },
        t,
      ),
    ) as Promise<KnowledgeCandidateDraft>;
  },

  cancelDraft(token: string, draftId: number): Promise<KnowledgeCandidateDraft> {
    return withToken(token, (t) =>
      request<KnowledgeCandidateDraft>(
        `/api/knowledge-agent/drafts/${draftId}/cancel`,
        { method: "POST" },
        t,
      ),
    ) as Promise<KnowledgeCandidateDraft>;
  },

  confirmDraft(
    token: string,
    draftId: number,
    payload: KnowledgeDraftConfirmRequest,
  ): Promise<KnowledgeDraftConfirm> {
    return withToken(token, (t) =>
      request<KnowledgeDraftConfirm>(
        `/api/knowledge-agent/drafts/${draftId}/confirm`,
        { method: "POST", body: JSON.stringify(serializeDraftConfirm(payload)) },
        t,
      ),
    ) as Promise<KnowledgeDraftConfirm>;
  },

  submitEntryRevision(
    token: string,
    conversationId: number,
    payload: KnowledgeRevisionActionRequest,
  ): Promise<KnowledgeRevisionAction> {
    return withToken(token, (t) =>
      request<KnowledgeRevisionAction>(
        `/api/knowledge-agent/conversations/${conversationId}/entry-revision-drafts`,
        { method: "POST", body: JSON.stringify(serializeRevisionAction(payload)) },
        t,
      ),
    ) as Promise<KnowledgeRevisionAction>;
  },

  getEntryRevisionDraft(
    token: string,
    draftId: number,
  ): Promise<KnowledgeEntryRevisionDraft> {
    return withToken(token, (t) =>
      request<KnowledgeEntryRevisionDraft>(
        `/api/knowledge-agent/entry-revision-drafts/${draftId}`,
        {},
        t,
      ),
    ) as Promise<KnowledgeEntryRevisionDraft>;
  },

  editEntryRevisionDraft(
    token: string,
    draftId: number,
    payload: KnowledgeRevisionEditRequest,
  ): Promise<KnowledgeEntryRevisionDraft> {
    return withToken(token, (t) =>
      request<KnowledgeEntryRevisionDraft>(
        `/api/knowledge-agent/entry-revision-drafts/${draftId}`,
        { method: "PATCH", body: JSON.stringify(serializeRevisionEdit(payload)) },
        t,
      ),
    ) as Promise<KnowledgeEntryRevisionDraft>;
  },

  cancelEntryRevisionDraft(
    token: string,
    draftId: number,
  ): Promise<KnowledgeEntryRevisionDraft> {
    return withToken(token, (t) =>
      request<KnowledgeEntryRevisionDraft>(
        `/api/knowledge-agent/entry-revision-drafts/${draftId}/cancel`,
        { method: "POST" },
        t,
      ),
    ) as Promise<KnowledgeEntryRevisionDraft>;
  },

  confirmEntryRevision(
    token: string,
    draftId: number,
    payload: KnowledgeRevisionConfirmRequest,
  ): Promise<KnowledgeRevisionConfirm> {
    return withToken(token, (t) =>
      request<KnowledgeRevisionConfirm>(
        `/api/knowledge-agent/entry-revision-drafts/${draftId}/confirm`,
        { method: "POST", body: JSON.stringify(serializeRevisionConfirm(payload)) },
        t,
      ),
    ) as Promise<KnowledgeRevisionConfirm>;
  },

  undoEntryRevision(
    token: string,
    draftId: number,
    payload: KnowledgeRevisionUndoRequest,
  ): Promise<KnowledgeRevisionUndo> {
    return withToken(token, (t) =>
      request<KnowledgeRevisionUndo>(
        `/api/knowledge-agent/entry-revision-drafts/${draftId}/undo`,
        { method: "POST", body: JSON.stringify(serializeRevisionUndo(payload)) },
        t,
      ),
    ) as Promise<KnowledgeRevisionUndo>;
  },

  getRun(token: string, runId: number): Promise<KnowledgeRun> {
    return withToken(token, (t) =>
      request<KnowledgeRun>(`/api/knowledge-agent/runs/${runId}`, {}, t),
    ) as Promise<KnowledgeRun>;
  },

  cancelRun(token: string, runId: number): Promise<KnowledgeRun> {
    return withToken(token, (t) =>
      request<KnowledgeRun>(
        `/api/knowledge-agent/runs/${runId}/cancel`,
        { method: "POST" },
        t,
      ),
    ) as Promise<KnowledgeRun>;
  },
};

export { MESSAGE_PAGE_LIMIT };
