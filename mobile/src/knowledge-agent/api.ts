/** 知识 Agent Bearer API：原生端只保留正式对话和 Entry 只读请求。 */

import { request } from "@/src/api";
import {
  classifyKnowledgeAgentError,
  KnowledgeAgentError,
} from "@/src/knowledge-agent/errors";
import type {
  KnowledgeConversation,
  KnowledgeEntryCurrent,
  KnowledgeMessagePage,
  KnowledgeRun,
  KnowledgeRunSubmit,
  KnowledgeRunSubmitRequest,
  KnowledgeScopeChangeRequest,
} from "@/src/knowledge-agent/types";

const MESSAGE_PAGE_LIMIT = 30;

function toCamel(key: string): string {
  return key.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase());
}

function normalizePayload<T>(value: unknown): T {
  if (Array.isArray(value)) return value.map((item) => normalizePayload(item)) as T;
  if (value !== null && typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      output[toCamel(key)] = normalizePayload(item);
    }
    return output as T;
  }
  return value as T;
}

function serializeScope(scope: KnowledgeScopeChangeRequest): Record<string, unknown> {
  return { scope_type: scope.scopeType, project_id: scope.projectId ?? null };
}

function serializeSubmit(payload: KnowledgeRunSubmitRequest): Record<string, unknown> {
  return {
    client_message_id: payload.clientMessageId,
    message: payload.message,
    context_mode: payload.contextMode,
  };
}

function withToken<T>(token: string | null, run: (value: string) => Promise<T>): Promise<T> {
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
    .then((result) => normalizePayload<T>(result))
    .catch((error: unknown) => {
      throw classifyKnowledgeAgentError(error);
    });
}

export const knowledgeAgentApi = {
  listConversations: (token: string) =>
    withToken(token, (value) =>
      request<KnowledgeConversation[]>("/api/knowledge-agent/conversations", {}, value),
    ),

  createConversation: (token: string, scope: KnowledgeScopeChangeRequest) =>
    withToken(token, (value) =>
      request<KnowledgeConversation>(
        "/api/knowledge-agent/conversations",
        { method: "POST", body: JSON.stringify(serializeScope(scope)) },
        value,
      ),
    ),

  getConversation: (token: string, conversationId: number) =>
    withToken(token, (value) =>
      request<KnowledgeConversation>(
        `/api/knowledge-agent/conversations/${conversationId}`,
        {},
        value,
      ),
    ),

  changeScope: (
    token: string,
    conversationId: number,
    scope: KnowledgeScopeChangeRequest,
  ) =>
    withToken(token, (value) =>
      request<KnowledgeConversation>(
        `/api/knowledge-agent/conversations/${conversationId}/scope`,
        { method: "PATCH", body: JSON.stringify(serializeScope(scope)) },
        value,
      ),
    ),

  listMessages: (token: string, conversationId: number, cursor: string | null) => {
    const query = cursor
      ? `?cursor=${encodeURIComponent(cursor)}&limit=${MESSAGE_PAGE_LIMIT}`
      : `?limit=${MESSAGE_PAGE_LIMIT}`;
    return withToken(token, (value) =>
      request<KnowledgeMessagePage>(
        `/api/knowledge-agent/conversations/${conversationId}/messages${query}`,
        {},
        value,
      ),
    );
  },

  submitMessage: (
    token: string,
    conversationId: number,
    payload: KnowledgeRunSubmitRequest,
  ) =>
    withToken(token, (value) =>
      request<KnowledgeRunSubmit>(
        `/api/knowledge-agent/conversations/${conversationId}/messages`,
        { method: "POST", body: JSON.stringify(serializeSubmit(payload)) },
        value,
      ),
    ),

  getEntryCurrent: (token: string, entryId: number) =>
    withToken(token, (value) =>
      request<KnowledgeEntryCurrent>(`/api/entries/${entryId}`, {}, value),
    ),

  getRun: (token: string, runId: number) =>
    withToken(token, (value) =>
      request<KnowledgeRun>(`/api/knowledge-agent/runs/${runId}`, {}, value),
    ),

  cancelRun: (token: string, runId: number) =>
    withToken(token, (value) =>
      request<KnowledgeRun>(
        `/api/knowledge-agent/runs/${runId}/cancel`,
        { method: "POST" },
        value,
      ),
    ),
};

export { MESSAGE_PAGE_LIMIT };
