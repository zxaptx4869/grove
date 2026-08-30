/** 幂等提交状态：稳定 client_message_id、懒创建对话与结果未知重试。 */

import * as Crypto from "expo-crypto";

import type { AnswerMode, ContextMode } from "@/src/knowledge-agent/types";

export type PendingPhase =
  | "creating_conversation"
  | "submitting"
  | "confirmed"
  | "conflict";

export interface PendingSubmission {
  clientMessageId: string;
  text: string;
  contextMode: ContextMode;
  answerMode: AnswerMode;
  /** 创建成功但提交结果未知时保留；网络重试不得再建对话或换幂等键。 */
  conversationId: number | null;
  phase: PendingPhase;
}

export function nextClientMessageId(random: () => string = Crypto.randomUUID): string {
  return random();
}

/** 确认操作的稳定幂等键：首次生成后未知结果重试必须复用同一键。 */
export function nextClientOperationId(random: () => string = Crypto.randomUUID): string {
  return random();
}

export function createPendingSubmission(input: {
  text: string;
  contextMode: ContextMode;
  answerMode: AnswerMode;
  random?: () => string;
}): PendingSubmission {
  return {
    clientMessageId: nextClientMessageId(input.random),
    text: input.text,
    contextMode: input.contextMode,
    answerMode: input.answerMode,
    conversationId: null,
    phase: "creating_conversation",
  };
}

export function attachConversation(
  pending: PendingSubmission,
  conversationId: number,
): PendingSubmission {
  return { ...pending, conversationId, phase: "submitting" };
}

export function markConfirmed(pending: PendingSubmission): PendingSubmission {
  return { ...pending, phase: "confirmed" };
}

export function markConflict(pending: PendingSubmission): PendingSubmission {
  return { ...pending, phase: "conflict" };
}

export function canRetrySubmission(pending: PendingSubmission | null): boolean {
  if (!pending) return false;
  return (
    pending.phase === "creating_conversation" || pending.phase === "submitting"
  );
}

/** 终态 failed 的重新提问必须使用新标识创建新 Run。 */
export function retrySubmissionWithNewId(
  pending: PendingSubmission,
  random?: () => string,
): PendingSubmission {
  return createPendingSubmission({
    text: pending.text,
    contextMode: pending.contextMode,
    answerMode: pending.answerMode,
    random,
  });
}
