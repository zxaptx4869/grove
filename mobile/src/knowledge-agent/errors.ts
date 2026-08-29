/** 知识 Agent 请求错误分类：鉴权、网络、409、取消与未知。 */

export type ApiErrorKind =
  | "auth"
  | "network"
  | "conflict"
  | "not_found"
  | "validation"
  | "server"
  | "cancelled"
  | "unknown";

export interface KnowledgeAgentErrorShape {
  kind: ApiErrorKind;
  status?: number;
  message: string;
  retryable: boolean;
}

export class KnowledgeAgentError extends Error implements KnowledgeAgentErrorShape {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly retryable: boolean;

  constructor(shape: KnowledgeAgentErrorShape) {
    super(shape.message);
    this.name = "KnowledgeAgentError";
    this.kind = shape.kind;
    this.status = shape.status;
    this.retryable = shape.retryable;
  }
}

function isAbortError(error: unknown): boolean {
  if (error instanceof Error && error.name === "AbortError") return true;
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

export function classifyKnowledgeAgentError(
  error: unknown,
  fallbackMessage = "请求失败，请检查网络后重试",
): KnowledgeAgentError {
  if (error instanceof KnowledgeAgentError) return error;
  if (isAbortError(error)) {
    // 当前客户端没有用户主动取消的请求；AbortError 全部来自 12s 超时，
    // 按可重试的网络类错误展示，避免把超时误报成“请求已取消”。
    return new KnowledgeAgentError({
      kind: "network",
      message: "连接超时，请检查网络后重试",
      retryable: true,
    });
  }
  const status = (error as { status?: unknown })?.status;
  const rawMessage =
    error instanceof Error ? error.message : String(error ?? fallbackMessage);
  if (status === 401) {
    return new KnowledgeAgentError({
      kind: "auth",
      status: 401,
      message: "登录已失效，请重新登录",
      retryable: false,
    });
  }
  if (status === 409) {
    return new KnowledgeAgentError({
      kind: "conflict",
      status: 409,
      message: rawMessage || "对话存在进行中的问答",
      retryable: false,
    });
  }
  if (status === 404) {
    return new KnowledgeAgentError({
      kind: "not_found",
      status: 404,
      message: rawMessage || "内容不存在或已删除",
      retryable: false,
    });
  }
  if (typeof status === "number" && status >= 400 && status < 500) {
    return new KnowledgeAgentError({
      kind: "validation",
      status,
      message: rawMessage || "请求内容不符合要求",
      retryable: false,
    });
  }
  if (typeof status === "number") {
    return new KnowledgeAgentError({
      kind: "server",
      status,
      message: rawMessage || "服务暂时不可用",
      retryable: true,
    });
  }
  return new KnowledgeAgentError({
    kind: "network",
    message: rawMessage || fallbackMessage,
    retryable: true,
  });
}

export function toUserErrorMessage(error: unknown): string {
  return classifyKnowledgeAgentError(error).message;
}
