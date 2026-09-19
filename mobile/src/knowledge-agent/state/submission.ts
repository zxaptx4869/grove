/** 正式消息幂等提交：结果未知重试沿用同一 client_message_id。 */

import * as Crypto from "expo-crypto";

import type { ContextMode } from "@/src/knowledge-agent/types";

export type PendingPhase =
  | "creating_conversation"
  | "submitting"
  | "confirmed"
  | "conflict";

export interface PendingSubmission {
  clientMessageId: string;
  text: string;
  contextMode: ContextMode;
  conversationId: number | null;
  phase: PendingPhase;
}

export function nextClientMessageId(random: () => string = Crypto.randomUUID): string {
  return random();
}

export function createPendingSubmission(input: {
  text: string;
  contextMode: ContextMode;
  random?: () => string;
}): PendingSubmission {
  return {
    clientMessageId: nextClientMessageId(input.random),
    text: input.text,
    contextMode: input.contextMode,
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

export function canRetrySubmission(pending: PendingSubmission | null): boolean {
  return Boolean(
    pending &&
      (pending.phase === "creating_conversation" || pending.phase === "submitting"),
  );
}

/** 终态失败重新提问与 continuation 都必须生成新的消息标识。 */
export function retrySubmissionWithNewId(
  pending: PendingSubmission,
  random?: () => string,
): PendingSubmission {
  return createPendingSubmission({
    text: pending.text,
    contextMode: pending.contextMode,
    random,
  });
}
