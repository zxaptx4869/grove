import {
  attachConversation,
  canRetrySubmission,
  createPendingSubmission,
  retrySubmissionWithNewId,
} from "@/src/knowledge-agent/state/submission";

test("结果未知重试保留同一消息标识和上下文", () => {
  const pending = attachConversation(
    createPendingSubmission({
      text: "继续分析",
      contextMode: "continue",
      random: () => "stable-id",
    }),
    9,
  );
  expect(pending).toMatchObject({
    clientMessageId: "stable-id",
    conversationId: 9,
    contextMode: "continue",
    phase: "submitting",
  });
  expect(canRetrySubmission(pending)).toBe(true);
});

test("失败后重新提问或 continuation 使用新标识", () => {
  const pending = createPendingSubmission({
    text: "原问题",
    contextMode: "auto",
    random: () => "old-id",
  });
  const retried = retrySubmissionWithNewId(pending, () => "new-id");
  expect(retried.clientMessageId).toBe("new-id");
  expect(retried.text).toBe("原问题");
  expect(retried.conversationId).toBeNull();
});
